import tempfile,zipfile,sys,copy
from pathlib import Path
import xml.etree.ElementTree as ET
from preset_store import BASE,normalize,PresetStore
from templates import apply_official_photo
from worker import execute
sys.path.insert(0,str(Path(__file__).resolve().parent/'core'))
from docx_fmt import q,NS,parse_keep_ns
r=normalize(apply_official_photo(BASE));r['字体嵌入']['启用']=False;r['页码']['起始位置']='全文'
with tempfile.TemporaryDirectory(prefix='wenju-photo-') as d:
 store=PresetStore(Path(d)/'data')
 assert store.selected=='wudi-official' and store.rules['正文']['字号']=='四号'
 assert store.rules['标题']['级数']==3
 p=Path(d)/'official.docx'
 with zipfile.ZipFile('core/样例/样例_整理前.docx') as z:parts={n:z.read(n) for n in z.namelist()}
 doc,_=parse_keep_ns(parts['word/document.xml']);body=doc.find('w:body',NS);sp=copy.deepcopy(body.find('w:sectPr',NS));body.clear()
 for text,center in [('秘密★10年',False),('关于推进科技创新工作的通知',True),('一、总体要求',False),('（一）工作目标',False),('1.实施步骤',False),('按照计划落实各项工作。',False)]:
  para=ET.SubElement(body,q('p'))
  if center:ET.SubElement(ET.SubElement(para,q('pPr')),q('jc'),{q('val'):'center'})
  ET.SubElement(ET.SubElement(para,q('r')),q('t')).text=text
 if sp is not None:body.append(sp)
 parts['word/document.xml']=ET.tostring(doc,encoding='utf-8')
 with zipfile.ZipFile(p,'w') as z:
  for name,data in parts.items():z.writestr(name,data)
 out=execute({'source':str(p),'rules':r});assert out['ok'],out
 with zipfile.ZipFile(out['output']) as z:
  doc=ET.fromstring(z.read('word/document.xml'));styles=ET.fromstring(z.read('word/styles.xml'))
  mar=doc.find('.//w:pgMar',NS)
  for key,cm in [('top',3.7),('bottom',3.5),('left',2.8),('right',2.6),('header',1.5),('footer',2.5)]:
   assert int(mar.get(q(key)))==round(cm/2.54*1440)
  ps=doc.findall('w:body/w:p',NS)
  assert ps[0].find('w:pPr/w:pStyle',NS).get(q('val'))=='SecurityMark'
  assert ps[1].find('w:pPr/w:pStyle',NS).get(q('val'))=='OfficialTitle'
  for sid,font,size in [('OfficialTitle','方正小标宋简体','44'),('SecurityMark','黑体','32'),('Normal','仿宋','28')]:
   st=next(x for x in styles.findall('w:style',NS) if x.get(q('styleId'))==sid)
   assert st.find('w:rPr/w:rFonts',NS).get(q('eastAsia'))==font
   assert st.find('w:rPr/w:sz',NS).get(q('val'))==size
   assert st.find('w:pPr/w:spacing',NS).get(q('line'))=='579'
  footer=ET.fromstring(z.read(next(n for n in z.namelist() if n.startswith('word/footer') and n.endswith('.xml'))))
  assert ''.join(t.text or '' for t in footer.findall('.//w:t',NS))=='—1—'
  assert footer.find('.//w:jc',NS).get(q('val'))=='both'
 print('PASS: official title, existing security mark, body typography and 28.95pt line spacing in actual DOCX')
