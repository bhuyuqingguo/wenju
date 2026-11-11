import tempfile,copy,zipfile,sys,os
from pathlib import Path
import xml.etree.ElementTree as ET
from preset_store import PresetStore,normalize
from worker import execute
from platform_support import data_directory
sys.path.insert(0,'core')
from docx_fmt import NS,q
with tempfile.TemporaryDirectory() as tmp:
 d=Path(tmp);s=PresetStore(d/'data')
 assert len(s.items())==115 and len({t['id'] for t in s.items()})==115
 for t in s.items():normalize(t['rules'])
 assert len([t for t in s.items() if t.get('redhead')])==10
 r=copy.deepcopy(s.find('scene-01-01')['rules']);r['字体嵌入']['启用']=False
 r['红头'].update({'机关名称':'示例技术中心文件','发文字号':'示例〔2026〕1号','签发人':'示例'})
 src=d/'sample.docx';src.write_bytes(Path('core/样例/样例_整理前.docx').read_bytes())
 for n in range(2):
  out=execute({'source':str(src),'rules':r});assert out['ok'];src=Path(out['output'])
  with zipfile.ZipFile(src) as z:
   doc=ET.fromstring(z.read('word/document.xml'))
   paras=doc.findall('w:body/w:p',NS)
   marks=[p for p in paras if p.find('w:pPr/w:pStyle',NS) is not None and p.find('w:pPr/w:pStyle',NS).get(q('val'))=='WenJuLetterhead']
   assert len(marks)==2
   assert '示例技术中心文件'==''.join(t.text or '' for t in marks[0].iter(q('t')))
   assert marks[0].find('w:r/w:rPr/w:color',NS).get(q('val'))=='C00000'
   assert marks[1].find('w:pPr/w:pBdr/w:bottom',NS).get(q('color'))=='C00000'
 r['红头']['机关名称']=''
 try:execute({'source':str(src),'rules':r})
 except ValueError as e:assert '机关名称' in str(e)
 else:raise AssertionError('missing name accepted')
 # A file prevents creation of portable directory, testing fallback without admin privileges.
 blocked=d/'blocked';blocked.mkdir();(blocked/'工作数据').write_text('not a directory')
 old={k:os.environ.get(k) for k in ('WENJU_DATA_DIR','LOCALAPPDATA','XDG_DATA_HOME')}
 try:
  os.environ.pop('WENJU_DATA_DIR',None);os.environ['LOCALAPPDATA']=str(d/'user');os.environ['XDG_DATA_HOME']=str(d/'user')
  assert data_directory(blocked)==d/'user'/'WenJu'
 finally:
  for k,v in old.items():
   if v is None:os.environ.pop(k,None)
   else:os.environ[k]=v
print('PASS: 115 valid unique scenario IDs, 10 redhead templates, real redhead output/idempotence/name validation, unprivileged path fallback')
