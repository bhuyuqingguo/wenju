import sys, json, tempfile, shutil, zipfile
from pathlib import Path
import xml.etree.ElementTree as ET
from worker import execute

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'core'))
from docx_fmt import Formatter, NS, q

rules=json.loads((ROOT/'core/rules.json').read_text('utf-8-sig'))
sample=ROOT/'core/样例/样例_整理前.docx'
with zipfile.ZipFile(sample) as z: original={n:z.read(n) for n in z.namelist()}
for prefix,suffix,align in [('','', '底部居中'),('- ',' -','底部左侧'),('— ',' —','底部右侧'),('第 <& ',' 页','底部居中')]:
    items=dict(original)
    Formatter(rules)._add_footer_part(items,{'左侧字符':prefix,'右侧字符':suffix,'字体':'宋体','字号':12,'字间距':1.5,'位置':align})
    name=next(n for n in items if n not in original and n.startswith('word/footer'))
    root=ET.fromstring(items[name])
    assert ''.join(t.text or '' for t in root.findall('.//w:t',NS)) == prefix+'1'+suffix
    assert root.find('.//w:instrText',NS).text.strip()=='PAGE'
    assert root.find('.//w:jc',NS).get(q('val'))=={'底部居中':'center','底部左侧':'left','底部右侧':'right'}[align]
    for rp in root.findall('.//w:rPr',NS):
        assert rp.find('w:spacing',NS).get(q('val'))=='30'
        assert rp.find('w:sz',NS).get(q('val'))=='24'
        assert all(rp.find('w:rFonts',NS).get(q(k))=='宋体' for k in ('ascii','hAnsi','cs','eastAsia'))
with tempfile.TemporaryDirectory(prefix='wenju-test-') as tmp:
    src=Path(tmp)/'sample.docx';shutil.copy2(sample,src)
    before=src.read_bytes()
    result=execute({'source':str(src),'settings':{'prefix':'— ','suffix':' —','font':'宋体','size':10.5,'spacing':0.5,'alignment':'底部居中','start':'全文'}})
    assert result['ok'] and src.read_bytes()==before
    with zipfile.ZipFile(result['output']) as z:
        assert z.testzip() is None
        for n in z.namelist():
            if n.endswith('.xml'):ET.fromstring(z.read(n))
print('PASS: 4 footer styles, XML escaping, uniform typography, alignment, PAGE field, full sample processing, original preserved')
