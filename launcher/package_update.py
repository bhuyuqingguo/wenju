"""Build rollback-capable offline deltas from all supported portable releases."""
import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import zipfile
import zlib
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from offline_update import MINIMUM, safe_name, version

ROOT = Path(__file__).resolve().parent
PLATFORMS = {
    'windows-x64': 'Windows_x64_Portable.zip',
    'win7-x64': 'Windows7_SP1_x64_Portable_Test.zip',
    'kylin-arm64': 'KylinV10_arm64_Portable.tar.gz',
    'kylin-x64': 'KylinV10_x86_64_Portable.tar.gz',
}

BAT = r'''@echo off
setlocal
chcp 65001 >nul
set "APP="
for /d %%D in ("%~dp0*") do if exist "%%~fD\app.py" if exist "%%~fD\runtime\python.exe" set "APP=%%~fD"
if not defined APP goto missing
set "UPGRADE_TMP=%TEMP%\WenJuUpgrade-%RANDOM%-%RANDOM%"
mkdir "%UPGRADE_TMP%" || goto failed
xcopy "%APP%\runtime\*" "%UPGRADE_TMP%\" /Y /Q >nul || goto failed
"%UPGRADE_TMP%\python.exe" -B -I "%~dp0update\apply.py" "%~dp0."
set "RESULT=%ERRORLEVEL%"
del /q "%UPGRADE_TMP%\*" 2>nul
rmdir "%UPGRADE_TMP%" 2>nul
pause
exit /b %RESULT%
:missing
echo Extract this update beside the original WenJu launcher, then retry.
pause
exit /b 1
:failed
echo Could not prepare the update runtime.
pause
exit /b 1
'''.encode('ascii')

SHELL = '''#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
app="$root/文矩"
if [ ! -x "$app/runtime/bin/python3" ]; then
    printf '%s\\n' '请将升级包解压到旧版文矩入口所在目录。' >&2
    exit 1
fi
export LD_LIBRARY_PATH="$app/runtime/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$app/runtime/bin/python3" -B -I "$root/update/apply.py" "$root"
'''


def open_zip(file, mode='r', metadata_encoding=None, **kwargs):
    """Open a zip. Python 3.11+ accepts metadata_encoding; 3.8 decodes cp437 names itself."""
    if metadata_encoding and sys.version_info >= (3, 11):
        kwargs['metadata_encoding'] = metadata_encoding
    archive = zipfile.ZipFile(file, mode, **kwargs)
    if metadata_encoding and sys.version_info < (3, 11) and 'r' in mode:
        renamed = []
        for info in archive.infolist():
            if info.flag_bits & 0x800:
                continue
            try:
                name = info.filename.encode('cp437').decode(metadata_encoding)
            except UnicodeError:
                continue
            if name != info.filename:
                renamed.append((info, name))
        for info, name in renamed:
            archive.NameToInfo.pop(info.filename, None)
            # orig_filename stays the cp437 form. ZipFile.open compares the
            # local header against it; filename is the path extractall writes.
            info.filename = name
            archive.NameToInfo[name] = info
    return archive


@contextmanager
def members(path):
    if path.suffix == '.zip':
        with open_zip(path, metadata_encoding='gbk') as archive:
            yield ((entry.filename, archive.read(entry), None, None)
                   for entry in archive.infolist() if not entry.is_dir())
    else:
        with tarfile.open(path, 'r|gz') as archive:
            def entries():
                for entry in archive:
                    if entry.isfile():
                        with archive.extractfile(entry) as stream:
                            yield entry.name, stream.read(), None, entry.mode & 0o777
                    elif entry.issym():
                        yield entry.name, None, entry.linkname, None
                    elif not entry.isdir():
                        raise ValueError('Unsupported archive member: ' + entry.name)
            yield entries()


def inventory(path):
    files, modes = {}, {}
    with members(path) as entries:
        for name, data, link, mode in entries:
            safe_name(name)
            if name in files:
                raise ValueError('Duplicate archive member: ' + name)
            files[name] = ['link', link] if link is not None else ['file', hashlib.sha256(data).hexdigest()]
            if mode is not None:
                modes[name] = mode
    return files, modes


class PortableZipInfo(zipfile.ZipInfo):
    def _encodeFilenameFlags(self):
        return self.filename.encode('gbk'), self.flag_bits & ~0x800


def build(archives, output, platform, target, sources):
    def package(v):
        return archives / f'WenJu_{v}_{PLATFORMS[platform]}'

    target_files, modes = inventory(package(target))
    histories = {v: inventory(package(v))[0] for v in sources}
    paths = set(target_files)
    for snapshot in histories.values():
        paths.update(snapshot)
    changes = {name for name in paths if any(snapshot.get(name) != target_files.get(name)
                                              for snapshot in histories.values())}
    needed = {name for name in changes if target_files.get(name, [''])[0] == 'file'}
    manifest = {'schema': 1, 'platform': platform, 'version': target,
                'target': {n: target_files[n] for n in changes if n in target_files},
                'modes': {n: modes[n] for n in changes if n in modes},
                'sources': {v: {n: snapshot[n] for n in changes if n in snapshot}
                            for v, snapshot in histories.items()}}
    output.mkdir(parents=True, exist_ok=True)
    dest = output / f'文矩_{target}_{platform}_离线升级.zip'
    windows = platform in ('windows-x64', 'win7-x64')
    with tempfile.TemporaryDirectory() as d:
        payload = Path(d) / 'update.zip'
        with zipfile.ZipFile(payload, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as delta:
            delta.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, separators=(',', ':')))
            written = set()
            with members(package(target)) as entries:
                for name, data, _, _ in entries:
                    if name in needed:
                        digest = target_files[name][1]
                        if digest not in written:
                            delta.writestr('payload/' + digest, data)
                            written.add(digest)
        with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            name = '升级文矩.bat' if windows else '升级文矩.sh'
            if windows:
                info = PortableZipInfo(name)
                raw = name.encode('gbk')
                extra = struct.pack('<BI', 1, zlib.crc32(raw)) + name.encode('utf-8')
                info.extra = struct.pack('<HH', 0x7075, len(extra)) + extra
            else:
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = 0o100755 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, BAT.replace(b'\n', b'\r\n') if windows else SHELL.encode('utf-8'))
            bundle.write(ROOT.parent/'offline_update.py', 'update/apply.py')
            bundle.write(payload, 'update/update.zip', compress_type=zipfile.ZIP_STORED)
    print(f'{dest.name}: {dest.stat().st_size:,} bytes, {len(written)} unique payload files')
    return dest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archives', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--from', dest='sources', nargs='+',
                        help='override the default: include every older portable release found in --archives')
    parser.add_argument('--platform', choices=PLATFORMS)
    args = parser.parse_args()
    output_files = []
    for platform in ([args.platform] if args.platform else PLATFORMS):
        suffix = '_' + PLATFORMS[platform]
        target = version(args.target)
        candidates = (p.name[6:-len(suffix)] for p in args.archives.glob('WenJu_*' + suffix))
        sources = sorted({v for v in (args.sources or candidates)
                          if MINIMUM <= version(v) < target}, key=version)
        if not sources or version(sources[0]) != MINIMUM:
            parser.error(f'{platform}: include the 3.4.5 baseline and archive every intermediate release.')
        output_files.append(build(args.archives, args.out, platform, args.target, sources))
    sums = [f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}' for path in output_files]
    (args.out / f'SHA256SUMS_{args.target}_离线升级.txt').write_text('\n'.join(sums) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
