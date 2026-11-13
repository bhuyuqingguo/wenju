"""Overlay the current sources onto the Win10/11 and Kylin runtimes and pack them.

The Win7 zip is built by package_win7.py. This script does not rebuild Qt.
Icon checks run on every tree and a missing size fails the build.
"""
from pathlib import Path
import hashlib, io, os, shutil, stat, subprocess, sys, tarfile, zipfile

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'dist'
sys.path.insert(0, str(ROOT / 'launcher'))
import package_win7

VERSION = '3.4.0'
APP_NAMES = package_win7.APP_FILES + (
    'launcher/打开文矩.sh', 'launcher/start-kylin.sh', 'launcher/diagnose-kylin.sh',
    'launcher/wenju.desktop', 'launcher/win7-vm.ps1',
)


def overlay(app):
    app.mkdir(parents=True, exist_ok=True)
    for name in APP_NAMES:
        src = ROOT / name
        if not src.is_file():
            continue
        dest = app / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        if dest.suffix == '.sh':
            dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    for path in (ROOT / 'core').rglob('*'):
        if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc':
            continue
        dest = app / path.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    icons = ROOT / 'launcher' / 'icons'
    if icons.exists():
        target = app / 'launcher' / 'icons'
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(icons, target)
    mark = icons / 'hicolor' / '256x256' / 'apps' / 'wenju.png'
    if mark.exists():
        shutil.copy2(mark, app / '.DirIcon')


def show_failure():
    bad = OUT / '_bad.ico'
    OUT.mkdir(exist_ok=True)
    bad.write_bytes(b'\x00\x00\x01\x00\x00\x00')
    proc = subprocess.run([sys.executable, str(ROOT / 'launcher' / 'check_icons.py'), 'ico', str(bad)], capture_output=True, text=True)
    bad.unlink()
    print('missing-icon check exit', proc.returncode)
    print(proc.stdout or proc.stderr)
    if proc.returncode == 0:
        raise SystemExit('icon check did not fail on an empty ico')


def pack_zip(work, archive):
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in work.rglob('*'):
            if path.is_file():
                z.write(path, path.relative_to(work).as_posix())
    return hashlib.sha256(archive.read_bytes()).hexdigest()


def pack_tar(work, archive):
    if archive.exists():
        archive.unlink()
    with tarfile.open(archive, 'w:gz') as tar:
        for path in work.rglob('*'):
            info = tar.gettarinfo(path, path.relative_to(work).as_posix())
            if path.is_file():
                info.mode |= 0o644
                if path.suffix == '.sh' or path.name.startswith('python'):
                    info.mode |= 0o111
                with path.open('rb') as fh:
                    tar.addfile(info, fh)
            elif path.is_dir():
                tar.addfile(info)
    return hashlib.sha256(archive.read_bytes()).hexdigest()


def windows_tree(src_zip, work):
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    with zipfile.ZipFile(src_zip) as z:
        z.extractall(work / '_raw')
    raw_app = next(p for p in (work / '_raw').iterdir() if p.is_dir())
    app = work / '文矩'
    shutil.move(str(raw_app), str(app))
    shutil.rmtree(work / '_raw')
    overlay(app)
    package_win7.build_launcher(app)
    shutil.copy2(app / '文矩.exe', work / '打开文矩.exe')
    subprocess.check_call([sys.executable, str(ROOT / 'launcher' / 'check_icons.py'), 'exe', str(work / '打开文矩.exe')])
    subprocess.check_call([sys.executable, str(ROOT / 'launcher' / 'check_icons.py'), 'exe', str(app / '文矩.exe')])


def linux_tree(src_tar, work):
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    with tarfile.open(src_tar) as tar:
        tar.extractall(work / '_raw')
    raw_app = next(p for p in (work / '_raw').iterdir() if p.is_dir())
    app = work / '文矩'
    shutil.move(str(raw_app), str(app))
    shutil.rmtree(work / '_raw')
    overlay(app)
    entry = work / '打开文矩.sh'
    shutil.copy2(ROOT / 'launcher' / '打开文矩.sh', entry)
    entry.chmod(0o755)
    subprocess.check_call([sys.executable, str(ROOT / 'launcher' / 'check_icons.py'), 'linux', str(work)])


def main():
    show_failure()
    package_win7.assemble()
    cache = Path('/tmp/wenju-release')
    cache.mkdir(exist_ok=True)
    win = cache / 'win.zip'
    if not win.exists():
        shutil.copy2('/tmp/wenju-audit/win.zip', win)
    windows_tree(win, OUT / 'win10-root')
    digest = pack_zip(OUT / 'win10-root', OUT / f'WenJu_{VERSION}_Windows_Portable.zip')
    sums = [f'{digest}  WenJu_{VERSION}_Windows_Portable.zip']
    win7 = OUT / f'WenJu_{VERSION}_Windows7_x64_Portable.zip'
    sums.append(f'{hashlib.sha256(win7.read_bytes()).hexdigest()}  {win7.name}')
    # These 3.3.0 archives are the glibc 2.17 runtimes. VERSION names the new packages.
    for arch, name in (('x86_64', 'WenJu_3.3.0_KylinV10_x86_64.tar.gz'), ('arm64', 'WenJu_3.3.0_KylinV10_arm64.tar.gz')):
        src = cache / name
        if not src.exists():
            subprocess.check_call(['curl', '-fL', '-o', str(src), f'https://github.com/bhuyuqingguo/wenju/releases/download/v3.3.0/{name}'])
        linux_tree(src, OUT / f'kylin-{arch}')
        out_name = f'WenJu_{VERSION}_KylinV10_{arch}.tar.gz'
        digest = pack_tar(OUT / f'kylin-{arch}', OUT / out_name)
        sums.append(f'{digest}  {out_name}')
    text = '\n'.join(sums) + '\n'
    (OUT / 'SHA256SUMS').write_text(text, encoding='ascii')
    for line in sums:
        digest, name = line.split('  ')
        path = OUT / name
        blob = path.read_bytes()
        if hashlib.sha256(blob).hexdigest() != digest:
            raise SystemExit('checksum mismatch ' + name)
        if VERSION not in name:
            raise SystemExit('filename has no version ' + name)
        note = b''
        if name.endswith('.zip'):
            with zipfile.ZipFile(path) as z:
                note = z.read('文矩/使用说明.txt')
                roots = {n.split('/')[0] for n in z.namelist()}
        else:
            with tarfile.open(path) as tar:
                member = tar.extractfile('文矩/使用说明.txt')
                note = member.read()
                roots = {n.split('/')[0] for n in tar.getnames() if n}
        if VERSION.encode() not in note:
            raise SystemExit(name + ' content version is not ' + VERSION)
        if roots != {'文矩', '打开文矩.exe'} and roots != {'文矩', '打开文矩.sh'}:
            raise SystemExit(name + ' outer entries are ' + ' '.join(sorted(roots)))
    art = Path('/opt/cursor/artifacts')
    art.mkdir(parents=True, exist_ok=True)
    for line in sums:
        name = line.split('  ', 1)[1]
        shutil.copy2(OUT / name, art / name)
    shutil.copy2(OUT / 'SHA256SUMS', art / 'SHA256SUMS')
    print(text)


if __name__ == '__main__':
    main()
