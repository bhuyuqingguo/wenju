"""Versioned preset storage, legacy-compatible import/export and field metadata."""
import copy
import json
import math
import uuid
import zipfile
from pathlib import Path
from templates import CATALOG, apply_template
from rule_schema import OPTIONS, GROUP_TIPS, FONT_CHOICES

ROOT = Path(__file__).resolve().parent
BASE = json.loads((ROOT/'core/rules.json').read_text('utf-8-sig'))
SIZES = {'初号':42,'小初':36,'一号':26,'小一':24,'二号':22,'小二':18,'三号':16,'小三':15,'四号':14,'小四':12,'五号':10.5,'小五':9,'六号':7.5,'小六':6.5,'七号':5.5,'八号':5}
BASE['页码'].update({'左侧字符':'','右侧字符':'','字间距':0.0,'统一字体':True})

def atomic_json(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),'utf-8')
        tmp.replace(path)
    finally:
        if tmp.exists():tmp.unlink()

def options_for(path):
    opt=OPTIONS.get(path)
    if opt is not None:return opt
    if path.endswith('.字号'):return list(SIZES)
    return None

def checked(path,value,default):
    key=path.split('.')[-1]
    if isinstance(value,str) and any(ord(c)<32 and c not in '\t\r\n' for c in value):raise ValueError(path+' 包含非法控制字符')
    if key=='字号':
        if isinstance(value,str) and value in SIZES:return value
        if isinstance(value,bool):raise ValueError(path+' 必须是字号名或磅数')
        try:v=float(value)
        except (ValueError,TypeError):raise ValueError(path+' 必须是字号名或磅数')
        if not math.isfinite(v) or not 1<=v<=200:raise ValueError(path+' 请填写 1～200 磅')
        return v
    if isinstance(default,bool):
        if not isinstance(value,bool):raise ValueError(path+' 必须为开关值')
    elif isinstance(default,(int,float)):
        if isinstance(value,bool):raise ValueError(path+' 必须是数值')
        try:value=float(value)
        except (ValueError,TypeError):raise ValueError(path+' 必须是数值')
        if not math.isfinite(value):raise ValueError(path+' 必须是有限数值')
        lo=-100 if ('缩进' in key or key=='字间距') else 0
        hi=2000
        if key in ('上边距','下边距','左边距','右边距','页眉距','页脚距'):hi=30
        if not lo<=value<=hi:raise ValueError(f'{path} 范围为 {lo}～{hi}')
        if path=='标题.级数':
            if not value.is_integer() or not 1<=value<=9:raise ValueError('标题级数必须为 1～9 的整数')
            value=int(value)
    elif isinstance(default,list):
        if not isinstance(value,list) or not all(isinstance(x,str) for x in value):raise ValueError(path+' 必须为文字列表')
    elif not isinstance(value,str):raise ValueError(path+' 必须是文字')
    opt=OPTIONS.get(path)
    if opt is not None and value not in opt:raise ValueError(path+' 的选项无效')
    if path=='输出.后缀' and (not value.strip() or any(c in value for c in '\\/:*?"<>|') or any(ord(c)<32 for c in value)):
        raise ValueError('输出后缀不能为空，也不能包含路径或文件名非法字符')
    if isinstance(value,str) and (key in ('字体','中文字体') or path.startswith('字体.') and key!='模式') and not value.strip():raise ValueError(path+' 不能为空')
    return value

def normalize(raw):
    if not isinstance(raw,dict) or not any(k in raw for k in BASE if not k.startswith('_')):
        raise ValueError('不是文矩规则文件：未发现页面、正文等规则分组')
    out=copy.deepcopy(BASE)
    def merge(dst,src,path=''):
        for k,v in src.items():
            if k.startswith('_'):continue
            p=(path+'.'+k).strip('.')
            if k not in dst:raise ValueError('未知规则：'+p)
            if isinstance(dst[k],dict):
                if not isinstance(v,dict):raise ValueError(p+' 必须是规则分组')
                merge(dst[k],v,p)
            else:dst[k]=checked(p,v,dst[k])
    merge(out,raw)
    pn=raw.get('页码',{})
    if '左侧字符' not in pn and '右侧字符' not in pn:
        a,b={'1':('',''),'- 1 -':('- ',' -'),'第 1 页':('第 ',' 页')}.get(pn.get('格式','1'),('',''))
        out['页码']['左侧字符']=a;out['页码']['右侧字符']=b
    if '统一字体' not in pn:out['页码']['统一字体']=False # preserve original Chinese font choice
    return out

def sections(rules):
    rows=[]
    for group,obj in rules.items():
        if group.startswith('_'):continue
        rows.append({'key':group,'name':group,'tip':GROUP_TIPS.get(group,'')})
        for sub,val in obj.items():
            if isinstance(val,dict):rows.append({'key':group+'.'+sub,'name':'　'+sub,'tip':GROUP_TIPS.get(group,'')})
    return rows

def fields(rules,section):
    obj=rules
    for k in section.split('.'):obj=obj[k]
    rows=[]
    for key,value in obj.items():
        if key.startswith('_') or isinstance(value,dict):continue
        path=section+'.'+key;opt=options_for(path)
        kind='bool' if isinstance(value,bool) else 'array' if isinstance(value,list) else 'number' if isinstance(value,(int,float)) else 'text'
        editable=key=='字号' or (key=='字体' or section=='字体' and key!='模式' or key=='中文字体')
        if opt is None and editable and key!='字号':opt=FONT_CHOICES
        if opt is not None:kind='choice'
        values=list(opt) if opt is not None else []
        labels=list(opt.values()) if isinstance(opt,dict) else [str(v) for v in values]
        unit='cm' if key in ('上边距','下边距','左边距','右边距','页眉距','页脚距') else '字符' if '缩进字符' in key else '磅' if key in ('段前','段后','字间距') else ''
        rows.append({'path':path,'label':key,'value':value,'display':'、'.join(value) if isinstance(value,list) else str(value),
            'kind':kind,'values':values,'labels':labels,'editable':editable,'unit':unit})
    return rows

class PresetStore:
    def __init__(self,data):
        self.data=Path(data);self.data.mkdir(parents=True,exist_ok=True)
        self.custom=[];self.builtins={}
        for item in CATALOG:
            rules=apply_template(BASE,item['id'])
            a,b={'1':('',''),'— 1 —':('— ',' —'),'第 1 页':('第 ',' 页')}[item['page']]
            rules['页码'].update({'左侧字符':a,'右侧字符':b,'统一字体':True,'字体':'Times New Roman' if not a else '宋体','中文字体':'宋体','起始位置':'全文' if item['category']=='公文办公' else '目录后'})
            self.builtins[item['id']]={**item,'rules':rules,'builtin':True}
        for i,path in enumerate(sorted((ROOT/'core/预设').glob('*.json'))):
            item={'id':'legacy-'+str(i),'name':'原版 · '+path.stem,'category':'原版预设','desc':'完整保留 2.1.0 随包规则，可编辑后另存。','builtin':True,'rules':normalize(json.loads(path.read_text('utf-8-sig')))}
            self.builtins[item['id']]=item
        custom_path=self.data/'templates.json'
        if custom_path.exists():
            self.custom=json.loads(custom_path.read_text('utf-8-sig'))
            for item in self.custom:item['rules']=normalize(item['rules'])
        self.selected='unit';self.rules=copy.deepcopy(self.builtins['unit']['rules']);self.dirty=False
        current=self.data/'current.json'
        if current.exists():
            x=json.loads(current.read_text('utf-8-sig'));self.rules=normalize(x['rules']);self.selected=x.get('selected','unit');self.dirty=x.get('dirty',False)
    def persist(self):atomic_json(self.data/'current.json',{'selected':self.selected,'rules':self.rules,'dirty':self.dirty})
    def items(self):return list(self.builtins.values())+self.custom
    def find(self,id):
        return next((t for t in self.items() if t['id']==id),None)
    def select(self,id):
        t=self.find(id)
        if not t:raise ValueError('模板不存在')
        self.rules=copy.deepcopy(t['rules']);self.selected=id;self.dirty=False;self.persist()
    def save_as(self,name):
        name=name.strip()
        if not name or len(name)>80:raise ValueError('模板名称请填写 1～80 个字符')
        if any(t['name']==name for t in self.items()):raise ValueError('已有同名模板，请换一个名称，或使用“保存修改”')
        item={'id':'user-'+uuid.uuid4().hex,'name':name,'category':'我的模板','desc':'个人模板 · 可编辑、导入和导出','builtin':False,'rules':normalize(self.rules)}
        atomic_json(self.data/'templates.json',self.custom+[item]);self.custom.append(item)
        self.selected=item['id'];self.dirty=False;self.persist();return item['id']
    def save(self):
        item=self.find(self.selected)
        if not item or item.get('builtin'):raise ValueError('内置模板请使用“另存为模板”保存为个人版本')
        updated=copy.deepcopy(self.custom)
        next(t for t in updated if t['id']==self.selected)['rules']=normalize(self.rules)
        atomic_json(self.data/'templates.json',updated);self.custom=updated;self.dirty=False;self.persist()
    def delete(self,id):
        t=self.find(id)
        if not t or t.get('builtin'):raise ValueError('内置模板不能删除')
        updated=[x for x in self.custom if x['id']!=id]
        atomic_json(self.data/'templates.json',updated);self.custom=updated
        if id==self.selected:self.select('unit')
    def import_files(self,paths):
        incoming=[]
        def parse(raw,name):
            if isinstance(raw,dict) and raw.get('wenju_bundle')==1:
                for item in raw['templates']:parse(item['rules'],item['name'])
            else:
                title=raw.get('_meta',{}).get('预设名',name) if isinstance(raw,dict) else name
                incoming.append((str(title),normalize(raw)))
        for path in map(Path,paths):
            if path.suffix.lower()=='.zip':
                with zipfile.ZipFile(path) as z:
                    infos=[i for i in z.infolist() if i.filename.lower().endswith('.json')]
                    if not infos:raise ValueError('压缩包中没有 JSON 模板')
                    if len(infos)>200 or sum(i.file_size for i in infos)>10_000_000:raise ValueError('模板包过大')
                    for i in infos:parse(json.loads(z.read(i).decode('utf-8-sig')),Path(i.filename).stem)
            else:
                if path.stat().st_size>10_000_000:raise ValueError('模板文件过大')
                parse(json.loads(path.read_text('utf-8-sig')),path.stem)
        if not incoming:raise ValueError('未发现模板')
        names={t['name'] for t in self.items()};added=[]
        for name,rules in incoming:
            base=name[:70] or '导入模板';name=base;n=2
            while name in names:name=f'{base}（{n}）';n+=1
            names.add(name)
            added.append({'id':'user-'+uuid.uuid4().hex,'name':name,'category':'我的模板','desc':'导入的完整规则模板','builtin':False,'rules':rules})
        atomic_json(self.data/'templates.json',self.custom+added);self.custom+=added
        return added
    def export_current(self,path):
        out=normalize(self.rules);t=self.find(self.selected)
        out['_meta']={'预设名':t['name'] if t else '当前方案','工具':'文矩','版本':'3.0'}
        atomic_json(path,out)
    def export_all(self,path):
        atomic_json(path,{'wenju_bundle':1,'templates':[{'name':t['name'],'rules':t['rules']} for t in self.items()]})
