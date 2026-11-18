"""Assemble a release from fresh Windows builds and the published Kylin runtimes."""
from pathlib import Path
import argparse
import hashlib
from io import BytesIO
import re
import shutil
import struct
import tarfile
import tempfile
import zipfile

import app_files
import package_win7

ROOT = app_files.ROOT
OUT = ROOT / 'dist'
VERSION = package_win7.VERSION
ARCHITECTURES = {'arm64': 183, 'x86_64': 62}
APP = '文矩'
ENTRY = '打开文矩.sh'


def stage_linux(work):
    app = work / APP
    for name in (*app_files.names(ROOT), 'launcher/start-kylin.sh',
                 'launcher/diagnose-kylin.sh', 'launcher/wenju.desktop'):
        dest = app / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, dest)

    def excluded(_directory, entries):
        return [name for name in entries if name == '__pycache__' or name.endswith('.pyc')
                or re.search(r'_(?:已整理(?: \(\d+\))?\.docx|整理报告(?: \(\d+\))?\.txt)$', name)]

    shutil.copytree(ROOT / 'core', app / 'core', ignore=excluded)
    shutil.copytree(ROOT / 'launcher/icons', app / 'launcher/icons')
    shutil.copy2(app / 'launcher/icons/hicolor/256x256/apps/wenju.png', app / '.DirIcon')
    shutil.copy2(ROOT / 'launcher' / ENTRY, work / ENTRY)
    app_files.require_tree(ROOT, app)


def linux_archive(source, work, dest, arch):
    prefix = APP + '/runtime'
    python_name = prefix + '/bin/python3'
    saw_python = False
    with tarfile.open(source, 'r|gz') as original, tarfile.open(dest, 'w:gz') as output:
        def app_mode(info):
            info.uid, info.gid = 0, 0
            info.uname = info.gname = ''
            info.mode = 0o755 if info.isdir() or info.name.endswith('.sh') else 0o644
            return info

        output.add(work / APP, arcname=APP, filter=app_mode)
        output.add(work / ENTRY, arcname=ENTRY, filter=app_mode)
        for member in original:
            if member.name != prefix and not member.name.startswith(prefix + '/'):
                continue
            if member.name == python_name:
                if not member.isfile() or not member.mode & 0o111:
                    raise ValueError(f'Python entry is not an executable file in {source}')
                with original.extractfile(member) as stream:
                    header = stream.read(20)
                    if (header[:6] != b'\x7fELF\x02\x01'
                            or struct.unpack_from('<H', header, 18)[0] != ARCHITECTURES[arch]):
                        raise ValueError(f'Wrong Python architecture in {source}')
                    output.addfile(member, BytesIO(header + stream.read()))
                    saw_python = True
            elif member.isfile():
                with original.extractfile(member) as stream:
                    output.addfile(member, stream)
            else:
                output.addfile(member)
    if not saw_python:
        raise ValueError(f'Missing {python_name} in {source}')


def verify_tutorial(archive_names):
    chapters = ('quick', 'templates', 'pagination', 'convert', 'filesize', 'output', 'appearance')
    expected = {APP + '/tutorial.py', APP + '/core/tutorial/chapters.json'}
    expected.update(f'{APP}/core/tutorial/{chapter}.wav' for chapter in chapters)
    missing = expected.difference(archive_names)
    if missing:
        raise ValueError('Release is missing: ' + ', '.join(sorted(missing)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kylin-cache', required=True, type=Path,
                        help='directory containing both published v3.3.0 Kylin portable archives')
    args = parser.parse_args()
    modern = OUT / f'文矩_{VERSION}_Windows_x64_免NET.zip'
    windows = {
        modern: f'WenJu_{VERSION}_Windows_x64_Portable.zip',
        package_win7.ARCHIVE: f'WenJu_{VERSION}_Windows7_SP1_x64_Portable_Test.zip',
    }
    published = []
    for source, target in windows.items():
        with zipfile.ZipFile(source, metadata_encoding='gbk') as archive:
            verify_tutorial(archive.namelist())
            if APP + '/文矩.exe' not in archive.namelist() or archive.testzip() is not None:
                raise ValueError(f'Windows ZIP verification failed: {source}')
        dest = OUT / target
        shutil.copy2(source, dest)
        published.append(dest)
    with tempfile.TemporaryDirectory(prefix='wenju-kylin-') as directory:
        work = Path(directory)
        stage_linux(work)
        for arch in ARCHITECTURES:
            source = args.kylin_cache / f'WenJu_3.3.0_KylinV10_{arch}.tar.gz'
            dest = OUT / f'WenJu_{VERSION}_KylinV10_{arch}_Portable.tar.gz'
            linux_archive(source, work, dest, arch)
            with tarfile.open(dest, 'r|gz') as archive:
                names = [item.name for item in archive]
            verify_tutorial(names)
            if ENTRY not in names or len(names) != len(set(names)):
                raise ValueError(f'Kylin archive verification failed: {dest}')
            published.append(dest)
    sums = []
    for path in published:
        with path.open('rb') as stream:
            checksummed = hashlib.file_digest(stream, 'sha256').hexdigest()
        sums.append(f'{checksummed}  {path.name}')
    (OUT / 'SHA256SUMS').write_text('\n'.join(sums) + '\n', encoding='ascii')
    print('\n'.join(sums))


if __name__ == '__main__':
    main()
