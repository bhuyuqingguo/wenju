"""Assemble a release from fresh Windows builds and the published Kylin runtimes."""
from pathlib import Path
import argparse
import hashlib
import json
from io import BytesIO
import re
import shutil
import struct
import sys
import gzip
import tarfile
import tempfile
import zipfile
from contextlib import contextmanager

sys.path.insert(0, str(Path(__file__).resolve().parent))
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

    def copy_launcher(source, dest):
        if source.suffix == '.sh':
            dest.write_bytes(source.read_bytes().replace(b'\r\n', b'\n'))
        else:
            shutil.copy2(source, dest)

    for name in (*app_files.names(ROOT), 'launcher/start-kylin.sh',
                 'launcher/diagnose-kylin.sh', 'launcher/wenju.desktop'):
        dest = app / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        copy_launcher(ROOT / name, dest)

    def excluded(_directory, entries):
        return [name for name in entries if name == '__pycache__' or name.endswith('.pyc')
                or re.search(r'_(?:已整理(?: \(\d+\))?\.docx|整理报告(?: \(\d+\))?\.txt)$', name)]

    shutil.copytree(ROOT / 'core', app / 'core', ignore=excluded)
    shutil.copytree(ROOT / 'launcher/icons', app / 'launcher/icons')
    shutil.copy2(app / 'launcher/icons/hicolor/256x256/apps/wenju.png', app / '.DirIcon')
    copy_launcher(ROOT / 'launcher' / ENTRY, work / ENTRY)
    app_files.require_tree(ROOT, app)


@contextmanager
def deterministic_tar_gz(dest):
    """gzip stores the current time unless mtime is fixed, so two identical trees differ."""
    raw = open(dest, 'wb')
    gz = tar = None
    try:
        gz = gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0)
        tar = tarfile.open(fileobj=gz, mode='w')
        yield tar
    finally:
        if tar is not None:
            tar.close()
        if gz is not None:
            gz.close()
        raw.close()


def linux_archive(source, work, dest, arch):
    prefix = APP + '/runtime'
    python_name = prefix + '/bin/python3'
    python_binary = python_name + '.11'
    saw_python = False
    saw_launcher = False
    with tarfile.open(source, 'r|gz') as original, deterministic_tar_gz(dest) as output:
        def app_mode(info):
            info.uid, info.gid = 0, 0
            info.uname = info.gname = ''
            info.mtime = 0
            for key in ('mtime', 'atime', 'ctime'):
                info.pax_headers.pop(key, None)
            info.mode = 0o755 if info.isdir() or info.name.endswith('.sh') else 0o644
            return info

        output.add(work / APP, arcname=APP, filter=app_mode)
        output.add(work / ENTRY, arcname=ENTRY, filter=app_mode)
        for member in original:
            if member.name != prefix and not member.name.startswith(prefix + '/'):
                continue
            if member.name == python_name:
                if not member.issym() or member.linkname != 'python3.11':
                    raise ValueError(f'Unexpected Python launcher in {source}')
                saw_launcher = True
            if member.name == python_binary:
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
    if not (saw_python and saw_launcher):
        raise ValueError(f'Missing Python launcher or executable in {source}')


def verify_tutorial(archive_names):
    chapters = json.loads((ROOT / 'core/tutorial/chapters.json').read_text(encoding='utf-8'))
    expected = {APP + '/tutorial.py', APP + '/core/tutorial/chapters.json'}
    expected.update(f"{APP}/core/tutorial/{chapter['id']}.wav" for chapter in chapters)
    expected.update(f'{APP}/{path.relative_to(ROOT).as_posix()}'
                    for path in (ROOT / 'core/tutorial/cases').rglob('*') if path.is_file())
    expected.update(f"{APP}/core/tutorial/cases/{case['directory']}/{case['file']}"
                    for case in (chapter.get('case') for chapter in chapters) if case)
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
            names = archive.namelist()
            if ({name.split('/', 1)[0] for name in names} != {APP, '打开文矩.exe'}
                    or APP + '/文矩.exe' not in names
                    or archive.read('打开文矩.exe') != archive.read(APP + '/文矩.exe')
                    or archive.testzip() is not None):
                raise ValueError(f'Windows ZIP verification failed: {source}')
        dest = OUT / target
        if not dest.exists() or dest.read_bytes() != source.read_bytes():
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
            if ({name.split('/', 1)[0] for name in names} != {APP, ENTRY}
                    or ENTRY not in names or len(names) != len(set(names))):
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
