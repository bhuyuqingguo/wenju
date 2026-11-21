"""Check every upgrade route and execute one representative portable upgrade."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from package_update import PLATFORMS, inventory, open_zip
from offline_update import MINIMUM, version

APP = '文矩'
REPRESENTATIVE = 'windows-x64'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def full_archive(directory, platform, release):
    return directory / f'WenJu_{release}_{PLATFORMS[platform]}'


def historical_releases(directory, platform, target):
    suffix = '_' + PLATFORMS[platform]
    return sorted((path.name[6:-len(suffix)] for path in directory.glob('WenJu_*' + suffix)
                   if MINIMUM <= version(path.name[6:-len(suffix)]) < version(target)), key=version)


def verify_routes(directory, platform, target):
    sources = historical_releases(directory, platform, target)
    require(sources and version(sources[0]) == MINIMUM, f'{platform} 缺少 3.4.5 基线归档。')
    patch = directory / f'文矩_{target}_{platform}_离线升级.zip'
    windows = platform.startswith('win')
    with open_zip(patch, metadata_encoding='gbk' if windows else None) as outer:
        script = '升级文矩.bat' if windows else '升级文矩.sh'
        require(set(outer.namelist()) == {script, 'update/apply.py', 'update/update.zip'},
                f'{patch.name} 缺少升级入口或包含额外文件。')
        if windows:
            require(outer.read(script).isascii(), f'{patch.name} 的批处理含非 ASCII 字符。')
        else:
            require(b'\r' not in outer.read(script), f'{patch.name} 的脚本含 Windows 换行。')
        payload = outer.read('update/update.zip')
    with zipfile.ZipFile(io.BytesIO(payload)) as inner:
        manifest = json.loads(inner.read('manifest.json'))
        require(manifest['schema'] == 1 and manifest['platform'] == platform and manifest['version'] == target,
                f'{patch.name} 的清单与发行平台或版本不一致。')
        require(set(manifest['sources']) == set(sources), f'{patch.name} 未覆盖全部已归档旧版。')
        wanted = {'payload/' + entry[1] for entry in manifest['target'].values() if entry[0] == 'file'}
        require(set(inner.namelist()) == wanted | {'manifest.json'}, f'{patch.name} 的补丁文件清单不符。')
        for name in wanted:
            require(hashlib.sha256(inner.read(name)).hexdigest() == name.split('/')[-1],
                    f'{patch.name} 存在文件校验失败。')

    desired, modes = inventory(full_archive(directory, platform, target))
    for name, mode in manifest['modes'].items():
        require(mode == modes.get(name), f'{patch.name} 的文件权限不符：{name}')
    for release in sources:
        old, _ = inventory(full_archive(directory, platform, release))
        before = manifest['sources'][release]
        after = manifest['target']
        for name in before.keys() | after.keys():
            require(old.get(name) == before.get(name), f'{patch.name} 的 {release} 基线不符：{name}')
            if name in after:
                old[name] = after[name]
            else:
                old.pop(name, None)
        require(old == desired, f'{platform} 从 {release} 无法完整更新到 {target}。')
    print(f'PASS 清单与文件校验 {platform} · {len(sources)} 条跳升路径', flush=True)
    return patch, sources[0]


def representative_upgrade(directory, target, patch, baseline):
    with tempfile.TemporaryDirectory(prefix='文矩 升级验收 ') as tmp:
        root = Path(tmp)
        with open_zip(full_archive(directory, REPRESENTATIVE, baseline),
                       metadata_encoding='gbk') as base:
            base.extractall(root)
        with open_zip(patch, metadata_encoding='gbk') as update:
            update.extractall(root)
        data = root / APP / '工作数据'
        data.mkdir(exist_ok=True)
        evidence = data / '验收.txt'
        evidence.write_bytes(b'keep')
        launcher = root / '打开文矩.exe'
        env = dict(os.environ, WENJU_DATA_DIR=str(data))
        result = subprocess.run(['cmd.exe', '/d', '/c', '升级文矩.bat'], cwd=str(root), env=env,
                                input=b'\r\n', capture_output=True, timeout=120)
        if result.returncode:
            raise ValueError((result.stdout + result.stderr).decode('utf-8', errors='replace'))
        require(launcher.is_file() and evidence.read_bytes() == b'keep', '启动入口或工作数据未保留。')
        app = root / APP
        require(f'text:"{target}  /' in (app/'Main.qml').read_text(encoding='utf-8'), '升级后版本号不符。')
        subprocess.run([str(app/'runtime/python.exe'), '-B', str(app/'app.py'), '--safe-render', '--smoke-startup'],
                       cwd=str(app), env=env, check=True, timeout=35)
    print(f'PASS 实际升级一次 Windows x64 · {baseline} → {target} · 启动和工作数据正常', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archives', type=Path, default=Path('dist'))
    parser.add_argument('--target', required=True)
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('请在 Windows 发版机运行，实际升级验收使用 Windows x64。')
    directory = args.archives.resolve()
    try:
        routes = {p: verify_routes(directory, p, args.target) for p in PLATFORMS}
        representative_upgrade(directory, args.target, *routes[REPRESENTATIVE])
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, subprocess.SubprocessError) as exc:
        parser.exit(1, f'升级验收失败：{exc}\n')


if __name__ == '__main__':
    main()
