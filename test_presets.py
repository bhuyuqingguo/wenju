import copy,json,tempfile,zipfile,shutil
from pathlib import Path
import xml.etree.ElementTree as ET
from preset_store import PresetStore,normalize,BASE,sections,fields,checked
from worker import execute

ROOT=Path(__file__).resolve().parent
def expect_error(fn):
    try:fn()
    except (ValueError,TypeError):return
    raise AssertionError('expected invalid input rejection')

with tempfile.TemporaryDirectory(prefix='wenju-presets-') as tmp:
    d=Path(tmp);s=PresetStore(d/'data')
    assert len(s.items())==115
    # Every original editable leaf has a form field, including all nine heading levels.
    def leaves(obj,prefix=''):
        for k,v in obj.items():
            if k.startswith('_'):continue
            p=(prefix+'.'+k).strip('.')
            if isinstance(v,dict):yield from leaves(v,p)
            else:yield p
    paths={f['path'] for section in sections(s.rules) for f in fields(s.rules,section['key'])}
    assert set(leaves(BASE))==paths
    print('PASS: all',len(paths),'editable fields mapped to forms')
    original=copy.deepcopy(s.builtins['unit']['rules'])
    s.rules['正文']['字号']=19;s.rules['页面']['上边距']=3.25
    s.rules['标题']['九级']['格式']='圈数字'
    s.rules['页码'].update({'左侧字符':'第 <& ','右侧字符':' 页','字间距':1.25,'位置':'底部右侧'})
    s.rules['输出']['后缀']='_测试成品'
    s.dirty=True;s.persist()
    assert PresetStore(d/'data').rules==s.rules
    personal=s.save_as('个人模板')
    assert s.builtins['unit']['rules']==original
    s.rules['正文']['行距值']=29;s.save()
    assert PresetStore(d/'data').find(personal)['rules']['正文']['行距值']==29
    expect_error(lambda:s.save_as('个人模板'))
    snapshot=copy.deepcopy(s.rules)
    s.export_current(d/'single.json');s.export_all(d/'bundle.json')
    other=PresetStore(d/'other')
    added=other.import_files([d/'single.json']);assert added[0]['rules']==snapshot
    again=other.import_files([d/'single.json']);assert again[0]['name']!=added[0]['name']
    all_added=other.import_files([d/'bundle.json']);assert len(all_added)==116
    with zipfile.ZipFile(d/'legacy.zip','w') as z:
        z.writestr('../legacy.json',json.dumps(original,ensure_ascii=False))
    assert len(other.import_files([d/'legacy.zip']))==1
    assert not (d/'legacy.json').exists()
    before=(d/'other/templates.json').read_bytes()
    (d/'bad.json').write_text('{"正文":{"字号":-8}}','utf-8')
    expect_error(lambda:other.import_files([d/'single.json',d/'bad.json']))
    assert (d/'other/templates.json').read_bytes()==before
    expect_error(lambda:normalize({'正文':{'加粗':'yes'}}))
    expect_error(lambda:normalize({'标题':{'级数':3.5}}))
    expect_error(lambda:normalize({'输出':{'后缀':'../evil'}}))
    expect_error(lambda:normalize({'页码':{'字号':float('nan')}}))
    expect_error(lambda:normalize({'页码':{'左侧字符':'\x01'}}))
    legacy=copy.deepcopy(original)
    for key in ('左侧字符','右侧字符','字间距','统一字体'):legacy['页码'].pop(key,None)
    legacy['页码']['格式']='第 1 页'
    assert normalize(legacy)['页码']['左侧字符']=='第 '
    expect_error(lambda:s.delete('unit'))
    print('PASS: save/restart, immutable builtins, export/import roundtrip, bundle, legacy ZIP, duplicate names, transactional invalid import')
    # Verify the exact edited snapshot, not regenerated built-in rules, reaches the DOCX engine.
    src=d/'sample.docx';shutil.copy2(ROOT/'core/样例/样例_整理前.docx',src)
    r=execute({'source':str(src),'rules':snapshot})
    assert r['ok'] and r['output'].endswith('_测试成品.docx')
    ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'};w='{'+ns['w']+'}'
    with zipfile.ZipFile(r['output']) as z:
        for n in z.namelist():
            if n.endswith('.xml'):ET.fromstring(z.read(n))
        doc=ET.fromstring(z.read('word/document.xml'))
        assert any(int(x.get(w+'top'))==round(3.25/2.54*1440) for x in doc.findall('.//w:pgMar',ns))
        footers=[ET.fromstring(z.read(n)) for n in z.namelist() if n.startswith('word/footer') and n.endswith('.xml')]
        assert any('第 <& 1 页'==''.join(e.text or '' for e in f.findall('.//w:t',ns)) for f in footers)
    inferred=execute({'action':'infer','source':r['output']})
    assert inferred['ok'] and inferred['notes'] and inferred['rules']['正文']['字号']==19
    assert inferred['rules']['页码']['左侧字符']=='第 <& '
    assert inferred['rules']['页码']['字间距']==1.25
    s.delete(personal);assert not s.find(personal) and s.selected=='wudi-official'
    print('PASS: actual DOCX margins/footer/output suffix, sample inference, template deletion')
