"""Package an already prepared Windows runtime, excluding all user data."""
from pathlib import Path
import shutil,zipfile,struct,zlib

ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'dist';OUT.mkdir(exist_ok=True)
ARCHIVE=OUT/'WenJu_3.4.0_Windows_Portable.zip'

class ChineseZipInfo(zipfile.ZipInfo):
    def _encodeFilenameFlags(self):
        return self.filename.encode('gbk'),self.flag_bits & ~0x800

def include(p):
    rel=p.relative_to(ROOT)
    if '__pycache__' in rel.parts or p.suffix=='.pyc':return False
    if rel.parts[0]=='core' and (p.name.endswith('_已整理.docx') or p.name.endswith('_整理报告.txt')):return False
    return True

files=[p for name in ('runtime','core') for p in (ROOT/name).rglob('*') if p.is_file() and include(p)]
files += [ROOT/n for n in ('文矩.exe','app.py','qt_compat.py','platform_support.py','template_library.py','appearance.py','templates.py','preset_store.py','rule_schema.py','worker.py','Main.qml','ProgressPanel.qml','Advanced.qml','AppearancePage.qml','Opening.qml','TemplateHome.qml','使用说明.txt','README.md','requirements-windows.txt','可选字体/README.txt','ui/ProgressPanel.qml','ui/qmldir')]
files += [p for p in (ROOT/'docs').glob('*.png')]
assert all(p.is_file() for p in files)
with zipfile.ZipFile(ARCHIVE,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for p in files:
        name='文矩/'+p.relative_to(ROOT).as_posix()
        info=ChineseZipInfo(name);info.compress_type=zipfile.ZIP_DEFLATED
        # Unicode Path extra field for tools that support it; GBK bytes for old Chinese Windows tools.
        raw=name.encode('gbk');extra=struct.pack('<BI',1,zlib.crc32(raw))+name.encode('utf-8')
        info.extra=struct.pack('<HH',0x7075,len(extra))+extra
        z.writestr(info,p.read_bytes())
with zipfile.ZipFile(ARCHIVE,metadata_encoding='gbk') as z:
    assert z.testzip() is None
    assert '文矩/文矩.exe' in z.namelist()
    assert not any('/工作数据/' in n for n in z.namelist())
print(ARCHIVE)
print('Files:',len(files),'Bytes:',ARCHIVE.stat().st_size)
