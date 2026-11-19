"""Prepare offline updates for the GUI and apply them after it exits."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

import offline_update

PAYLOAD = 'update/update.zip'
MAX_PAYLOAD = 1024 * 1024 * 1024
PLATFORM_NAMES = {'windows-x64': 'Windows 10/11 x64', 'win7-x64': 'Windows 7 SP1 x64',
                  'kylin-x64': '银河麒麟 V10 x86_64', 'kylin-arm64': '银河麒麟 V10 ARM64'}
# A malformed package can fail at either ZIP layer or while decoding its manifest.
PACKAGE_ERRORS = (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, RuntimeError, zipfile.BadZipFile)


def update_home(data):
    path = Path(data) / '离线升级'
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def result_file(root, data):
    identity = hashlib.sha256(os.path.normcase(str(root.resolve())).encode('utf-8')).hexdigest()[:16]
    return (Path(data) / '离线升级').resolve() / ('结果-' + identity + '.json')


def launcher(root):
    app = root / offline_update.APP
    if os.name == 'nt':
        path = app / '文矩.exe'
        command = [str(path)]
    else:
        path = app / 'launcher/start-kylin.sh'
        command = ['sh', str(path)]
    if not path.is_file():
        raise ValueError('未找到文矩的正式启动入口，请从完整的便携包启动。')
    return command


def prepare(root, data, package):
    root = root.resolve()
    if not (root / offline_update.APP / 'Main.qml').is_file():
        raise ValueError('请从完整的文矩便携目录启动，再导入升级包。')
    launcher(root)
    home = update_home(data)
    job = Path(tempfile.mkdtemp(prefix='任务-', dir=str(home)))
    try:
        with zipfile.ZipFile(package) as outer:
            item = outer.getinfo(PAYLOAD)
            if item.file_size > MAX_PAYLOAD:
                raise ValueError('升级包超过 1 GB，无法载入。')
            with outer.open(item) as source, (job/'update.zip').open('wb') as dest:
                shutil.copyfileobj(source, dest)
        with zipfile.ZipFile(job/'update.zip') as inner:
            old, new, manifest, count = offline_update.inspect_bundle(root, inner)
        return job, dict(current=old, target=new, count=count,
                         platform=PLATFORM_NAMES[manifest['platform']], name=Path(package).name)
    except BaseException:
        shutil.rmtree(job)
        raise


def launch_worker(root, data, job):
    target = launcher(root)
    shutil.copyfile(__file__, job/'apply_gui.py')
    shutil.copyfile(offline_update.__file__, job/'offline_update.py')
    python = Path(sys.executable)
    flags = 0
    if os.name == 'nt':
        runtime = root / offline_update.APP / 'runtime'
        shadow = job / 'runtime'
        shadow.mkdir()
        for file in runtime.iterdir():
            if file.is_file():
                shutil.copy2(file, shadow / file.name)
        pth = next(shadow.glob('python*._pth'))
        pth.write_text(pth.stem + '.zip\n.\n..\n', encoding='ascii')
        python = shadow / 'python.exe'
        flags = subprocess.CREATE_NO_WINDOW
    settings = {'root': str(root), 'receipt': str(result_file(root, data)),
                'parent': os.getpid(), 'restart': target}
    (job/'settings.json').write_text(json.dumps(settings, ensure_ascii=False), encoding='utf-8')
    with (job/'worker.log').open('wb') as log:
        subprocess.Popen([str(python), '-B', str(job/'apply_gui.py')], cwd=str(job),
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=flags)


def parent_exited(pid):
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 87
        try:
            return kernel.WaitForSingleObject(ctypes.c_void_p(handle), 20000) == 0
        finally:
            kernel.CloseHandle(ctypes.c_void_p(handle))
    end = time.monotonic() + 20
    while time.monotonic() < end:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)
    return False


def run_worker(job):
    config = json.loads((job/'settings.json').read_text(encoding='utf-8'))
    root = Path(config['root'])
    receipt = Path(config['receipt'])
    closed = parent_exited(config['parent'])
    details = {'job': job.name, 'ok': False}
    if closed:
        try:
            old, new, count = offline_update.apply(root, job/'update.zip')
            details.update(ok=True, message=f'文矩已从 {old} 升级到 {new}，更新了 {count} 个文件。')
        except PACKAGE_ERRORS as exc:
            details.update(message='未能完成升级。' + str(exc))
    else:
        details.update(message='文矩仍在运行。请完全退出后再试。')
    pending = receipt.with_suffix('.tmp')
    pending.write_text(json.dumps(details, ensure_ascii=False), encoding='utf-8')
    pending.replace(receipt)
    if closed and not (root / offline_update.MARKER).exists():
        subprocess.Popen(config['restart'], cwd=str(root),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    run_worker(Path(__file__).resolve().parent)
