"""Apply an offline WenJu update from the portable directory."""
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import zipfile

APP = '文矩'
MARKER = '.wenju-update-transaction'
MINIMUM = (3, 4, 5)
MANIFEST_LIMIT = 4 * 1024 * 1024


def inspect_bundle(root, archive):
    app = root / APP
    info = archive.getinfo('manifest.json')
    if info.file_size > MANIFEST_LIMIT:
        raise ValueError('升级清单过大。')
    manifest = json.loads(archive.read(info))
    if manifest.get('schema') != 1 or manifest['platform'] != product_platform(app):
        raise ValueError('升级包的平台或架构与旧版不一致。')
    current = re.search(r'text:\s*"([0-9]+\.[0-9]+\.[0-9]+)\s+/',
                        (app/'Main.qml').read_text(encoding='utf-8'))
    if current is None:
        raise ValueError('未能识别旧版文矩版本。')
    installed = current.group(1)
    target = manifest['version']
    if version(installed) < MINIMUM or version(installed) >= version(target):
        raise ValueError(f'此升级包适用于 3.4.5 起、早于 {target} 的版本。当前为 {installed}。')
    if installed not in manifest['sources']:
        raise ValueError(f'此包未收录 {installed} 的发行清单。')
    before, after = manifest['sources'][installed], manifest['target']
    changed = [name for name in set(before) | set(after) if before.get(name) != after.get(name)]
    for name in changed:
        safe_name(name)
        new = after.get(name)
        if new and new[0] == 'file':
            if not re.fullmatch('[0-9a-f]{64}', new[1]):
                raise ValueError('升级清单含无效文件校验值。')
            archive.getinfo('payload/' + new[1])
        elif new and new[0] != 'link':
            raise ValueError('升级清单含未知文件类型。')
    return installed, target, manifest, len(changed)


def version(value):
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', value):
        raise ValueError('无法读取版本号。')
    return tuple(map(int, value.split('.')))


def safe_name(name):
    parts = name.split('/')
    if (any(not p or p in {'.', '..'} or p[-1] in ' .' or re.search(r'[\\:\x00-\x1f]', p) for p in parts)
            or name not in {'打开文矩.exe', '打开文矩.sh'} and
            (len(parts) < 2 or parts[0] != APP or parts[1] == '工作数据')):
        raise ValueError('升级包含有不允许修改的路径：' + name)
    return PurePosixPath(name)


def product_platform(app):
    if (app / 'runtime/python.exe').is_file():
        return 'win7-x64' if (app / 'runtime/qt5.txt').is_file() else 'windows-x64'
    with (app / 'runtime/bin/python3').open('rb') as stream:
        hdr = stream.read(20)
    if hdr[:6] != b'\x7fELF\x02\x01':
        raise ValueError('无法识别此文矩运行库的架构。')
    return {62: 'kylin-x64', 183: 'kylin-arm64'}.get(int.from_bytes(hdr[18:20], 'little'))


def running(root):
    app = root / APP
    if os.name == 'nt':
        env = os.environ
        folders = [app/'工作数据', Path(env.get('LOCALAPPDATA', Path.home()))/'WenJu']
        if env.get('WENJU_DATA_DIR'):
            folders.append(Path(env['WENJU_DATA_DIR']))
        for folder in folders:
            lock = folder / 'session.lock'
            if not lock.exists():
                continue
            try:
                pid = int(lock.read_text(encoding='utf-8').splitlines()[0])
            except (OSError, ValueError, IndexError):
                return True
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.restype = ctypes.c_void_p
            handle = kernel.OpenProcess(0x1000, False, pid)
            if handle:
                kernel.CloseHandle(ctypes.c_void_p(handle))
                return True
            if ctypes.get_last_error() != 87:
                return True
        return False
    proc = Path('/proc')
    script = str(app / 'app.py')
    for entry in proc.glob('[0-9]*/cmdline'):
        try:
            args = entry.read_bytes().decode('utf-8', errors='replace').split('\0')
        except OSError:
            continue
        if script in args:
            return True
    return False


def present(path):
    return path.is_symlink() or path.exists()


def entry_id(path):
    if path.is_symlink():
        return ['link', os.readlink(path)]
    if not path.is_file():
        return None
    with path.open('rb') as stream:
        value = hashlib.sha256()
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(data)
    return ['file', value.hexdigest()]


def checked_path(root, name):
    rel = safe_name(name)
    target = root / rel
    if target.parent.resolve() != target.parent:
        raise ValueError('升级目录含有重定向路径：' + name)
    return target


def rollback(root, tx, changes):
    for name, was_present in reversed(changes):
        target = checked_path(root, name)
        backup = tx / 'backup' / name
        staged = tx / 'stage' / name
        if present(backup):
            os.replace(backup, target)
        elif not was_present and not present(staged) and present(target):
            target.unlink()


def apply(root, bundle):
    root = root.resolve()
    if not (root / APP).is_dir():
        raise ValueError('请将升级包解压到旧版文矩启动入口所在目录。')
    lockfile = root / '.wenju-upgrade.lock'
    if lockfile.resolve() != lockfile:
        raise ValueError('升级锁目录不可用。')
    with lockfile.open('a+b') as lock:
        try:
            if os.name == 'nt':
                import msvcrt
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError('另一个离线升级正在进行。') from None
        return _apply(root, bundle)


def _apply(root, bundle):
    root = root.resolve()
    app = root / APP
    if app.resolve() != app:
        raise ValueError('请将升级包解压到旧版文矩启动入口所在目录。')
    if running(root):
        raise ValueError('文矩仍在运行。请完全退出后再升级。')
    tx = root / MARKER
    if tx.resolve() != tx:
        raise ValueError('升级事务目录不可用。')
    if tx.exists():
        if (tx/'journal.json').is_file() and not (tx/'done').exists():
            rollback(root, tx, json.loads((tx/'journal.json').read_text(encoding='utf-8')))
        shutil.rmtree(tx)
    if not (app/'Main.qml').is_file():
        raise ValueError('旧版文矩文件不完整，未找到 Main.qml。')
    with zipfile.ZipFile(bundle) as z:
        installed, target_version, manifest, _ = inspect_bundle(root, z)
        before = manifest['sources'][installed]
        after = manifest['target']
        tx.mkdir()
        changes = []
        try:
            for name in sorted(set(before) | set(after)):
                target = checked_path(root, name)
                old, new = before.get(name), after.get(name)
                if old == new:
                    continue
                actual = entry_id(target)
                if actual == new:
                    continue
                if actual is not None and actual != old:
                    raise ValueError('文件已被修改，升级已停止：' + name)
                if present(target) and actual is None:
                    raise ValueError('升级文件与目录冲突：' + name)
                if new:
                    staged = tx / 'stage' / name
                    staged.parent.mkdir(parents=True, exist_ok=True)
                    if new[0] == 'link':
                        link = new[1]
                        if '/' in link or '\\' in link or link in {'.', '..'}:
                            raise ValueError('不支持的运行库链接：' + name)
                        staged.symlink_to(link)
                    else:
                        with z.open('payload/' + new[1]) as source, staged.open('wb') as output:
                            shutil.copyfileobj(source, output)
                        if entry_id(staged) != new:
                            raise ValueError('升级文件校验失败：' + name)
                        mode = manifest['modes'].get(name)
                        if os.name != 'nt' and mode is not None:
                            staged.chmod(mode)
                changes.append([name, present(target)])
            with (tx/'journal.json').open('w', encoding='utf-8') as stream:
                json.dump(changes, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            if running(root):
                raise ValueError('文矩在准备升级时被打开。请退出后重试。')
            try:
                for name, was_present in changes:
                    target = checked_path(root, name)
                    if was_present:
                        backup = tx/'backup'/name
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(target, backup)
                    staged = tx/'stage'/name
                    if present(staged):
                        target.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(staged, target)
                (tx/'done').touch()
            except BaseException:
                rollback(root, tx, changes)
                shutil.rmtree(tx)
                raise
        finally:
            # A failed rollback leaves its journal and backups for recovery on the next run.
            if tx.is_dir() and ((tx/'done').exists() or not (tx/'journal.json').exists()):
                shutil.rmtree(tx)
        return installed, target_version, len(changes)


if __name__ == '__main__':
    if os.name == 'nt' and sys.stdout is not None:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    try:
        old, new, count = apply(Path(sys.argv[1]), Path(__file__).with_name('update.zip'))
        print(f'文矩已从 {old} 升级到 {new}，更新 {count} 个文件。现在可以从原入口启动。')
    except (OSError, ValueError, KeyError, IndexError, zipfile.BadZipFile) as exc:
        print(f'升级未完成：{exc}', file=sys.stderr)
        sys.exit(1)
