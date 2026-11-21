"""Package an already prepared Windows runtime, excluding all user data."""
from pathlib import Path
import re,sys,zipfile,struct,zlib

ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'dist';OUT.mkdir(exist_ok=True)
ARCHIVE=OUT/'文矩_3.4.8_Windows_x64_免NET.zip'

class ChineseZipInfo(zipfile.ZipInfo):
    def _encodeFilenameFlags(self):
        return self.filename.encode('gbk'),self.flag_bits & ~0x800

def include(p):
    rel=p.relative_to(ROOT)
    if '__pycache__' in rel.parts or p.suffix=='.pyc':return False
    if rel.parts[0]=='core' and re.search(r'(?:_已整理(?: \(\d+\))?\.docx|_整理报告(?: \(\d+\))?\.txt)$',p.name):return False
    return True

sys.path.insert(0, str(ROOT / 'launcher'))
import app_files
from package_update import open_zip
from pe_imports import require_native_launcher
from check_icons import check_exe
require_native_launcher(ROOT / "文矩.exe")
check_exe(ROOT / "文矩.exe")
app_files.require_tree(ROOT)
files=[p for name in ('runtime','core') for p in (ROOT/name).rglob('*') if p.is_file() and include(p)]
files += [ROOT / '文矩.exe']
files += [ROOT / name for name in app_files.names(ROOT)]
files += [p for p in (ROOT/'docs').glob('*.png')]
assert all(p.is_file() for p in files)
with zipfile.ZipFile(ARCHIVE,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    entries = [('打开文矩.exe', ROOT / '文矩.exe')]
    entries.extend(('文矩/' + p.relative_to(ROOT).as_posix(), p) for p in files)
    for name, p in entries:
        info=ChineseZipInfo(name);info.compress_type=zipfile.ZIP_DEFLATED
        # Unicode Path extra field for tools that support it; GBK bytes for old Chinese Windows tools.
        raw=name.encode('gbk');extra=struct.pack('<BI',1,zlib.crc32(raw))+name.encode('utf-8')
        info.extra=struct.pack('<HH',0x7075,len(extra))+extra
        z.writestr(info,p.read_bytes())
with open_zip(ARCHIVE, metadata_encoding='gbk') as z:
    assert z.testzip() is None
    assert '文矩/文矩.exe' in z.namelist()
    assert {name.split('/', 1)[0] for name in z.namelist()} == {'打开文矩.exe', '文矩'}
    assert z.read('打开文矩.exe') == z.read('文矩/文矩.exe')
    assert not any('/工作数据/' in n for n in z.namelist())
print(ARCHIVE)
print('Files:',len(files),'Bytes:',ARCHIVE.stat().st_size)
