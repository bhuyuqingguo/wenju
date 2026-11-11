"""Editable scenario presets. These are house styles, not certified standards."""
import copy
from template_library import extra_catalog, apply_profile

DEFAULT_TEMPLATE = 'wudi-official'

CATALOG = [
    dict(id=DEFAULT_TEMPLATE,name='无敌公文体',category='公文办公',desc='专属默认格式：仿宋四号、固定行距 28.95 磅；方正小标宋二号题目，宋体四号页码 —1—。',font='仿宋',size=14,line=28.95,number='汉字顿号',page='—1—'),
    dict(id='unit',name='单位通用报告',category='科技办公',desc='延续原版单位格式，适合内部报告与综合材料。',font='仿宋_GB2312',size=16,line=25,number='汉字顿号',page='— 1 —'),
    dict(id='research',name='科技研究报告',category='科技研发',desc='宋体正文、层级数字标题，适合研究成果与技术论证。',font='宋体',size=12,line=22,number='多级数字',page='1'),
    dict(id='technical',name='技术方案',category='科技研发',desc='突出章节层级，适合系统方案、总体设计和实施路线。',font='宋体',size=14,line=24,number='多级数字',page='— 1 —'),
    dict(id='spec',name='需求与规格说明',category='科技研发',desc='紧凑正文与多级编号，适合需求清单、接口及规格说明。',font='宋体',size=12,line=20,number='多级数字',page='1'),
    dict(id='test',name='测试与验收报告',category='科技研发',desc='强调表格可读性，适合测试记录、问题清单和验收材料。',font='宋体',size=12,line=21,number='多级数字',page='第 1 页'),
    dict(id='paper',name='学术论文初稿',category='科研写作',desc='适合论文初稿的单栏整理；投稿前按目标期刊要求调整。',font='宋体',size=10.5,line=18,number='多级数字',page='1'),
    dict(id='proposal',name='项目申报材料',category='科研写作',desc='较舒展的正文，适合立项依据、研究内容与项目计划。',font='宋体',size=14,line=25,number='汉字顿号',page='— 1 —'),
    dict(id='survey',name='调研分析报告',category='科研写作',desc='适合行业调研、对标分析、情报研判和成果总结。',font='仿宋',size=14,line=25,number='汉字顿号',page='— 1 —'),
    dict(id='official',name='公文正文基础',category='公文办公',desc='仿宋三号、汉字层级。仅为正文排版起点，不含红头版记及完整国标校验。',font='仿宋',size=16,line=28,number='汉字顿号',page='— 1 —'),
    dict(id='minutes',name='会议纪要',category='公文办公',desc='清晰分层、适度留白，适合议定事项与工作部署记录。',font='仿宋',size=14,line=24,number='汉字顿号',page='第 1 页'),
    dict(id='notice',name='通知与工作安排',category='公文办公',desc='适合内部通知、工作要求和实施安排，保留简洁版式。',font='仿宋',size=16,line=26,number='汉字顿号',page='— 1 —'),
    dict(id='brief',name='工作简报',category='公文办公',desc='更紧凑的阅读节奏，适合工作动态、阶段总结和短报告。',font='宋体',size=12,line=21,number='汉字顿号',page='1'),
]

CATALOG.extend(extra_catalog())

def apply_template(base, name):
    if name==DEFAULT_TEMPLATE:return apply_official_photo(base)
    r=copy.deepcopy(base)
    t=next((t for t in CATALOG if t['id']==name),CATALOG[0])
    r['字体']['正文']=t['font']; r['字体']['表格']=t['font']
    r['字体']['括号内']=t['font']; r['字体']['题注']='宋体'
    r['正文'].update({'字号':t['size'],'行距值':t['line']})
    for i,key in enumerate(['一级','二级','三级','四级']):
        r['标题'][key].update({'字号':t['size']+(2 if i==0 else 0),'行距值':t['line'],
            '段前':8 if t['number']=='多级数字' else 0,'段后':4 if t['number']=='多级数字' else 0})
        if t['number']=='多级数字':r['标题'][key]['格式']='多级数字'
    r['字体']['一级标题']='黑体'
    r['字体']['二级标题']='黑体' if t['number']=='多级数字' else '楷体'
    r['字体']['三级标题']=t['font'];r['字体']['四级标题']=t['font']
    r['表格'].update({'字号':10.5 if t['size']<=12 else 12,'首行加粗':True})
    # Do not modify technical symbols and percentages in scientific manuscripts.
    if t['category'] in ('科技研发','科研写作'):r['标点']['启用']=False
    if t['id'] in ('minutes','notice','brief','official'):r['题注']['缺失时自动补编号']=False
    if 'profile' in t:r=apply_profile(r,t)
    return r


def apply_official_photo(base):
    """The user's confirmed house style, including typography and pagination."""
    r=copy.deepcopy(base)
    r['页面'].update({'上边距':3.7,'下边距':3.5,'左边距':2.8,'右边距':2.6,'页眉距':1.5,'页脚距':2.5})
    r['字体'].update({'正文':'仿宋','括号内':'仿宋','一级标题':'黑体',
                    '二级标题':'楷体_GB2312','三级标题':'仿宋_GB2312','封面标题':'方正小标宋简体'})
    r['正文'].update({'字号':'四号','行距类型':'固定值','行距值':28.95,'对齐':'both'})
    for level in ('一级','二级','三级'):
        r['标题'][level].update({'字号':'三号','行距类型':'固定值','行距值':28.95,'段前':0,'段后':0})
    r['标题']['级数']=3
    r['标题']['一级']['字号']='三号'
    r['封面']['标题'].update({'字号':'二号','行距类型':'固定值','行距值':28.95})
    r['公文'].update({'启用':True,'题目字体':'方正小标宋简体','题目字号':'二号','密级字体':'黑体','密级字号':'三号'})
    r['页码'].update({'启用':True,'字体':'宋体','中文字体':'宋体','统一字体':True,'字号':'四号','位置':'底部两端对齐','左侧字符':'—','右侧字符':'—','字间距':0,'起始位置':'全文'})
    r['题注']['缺失时自动补编号']=False
    return r
