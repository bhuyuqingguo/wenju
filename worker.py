import sys, json, traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'core'))
import docx_fmt
from templates import apply_template
from preset_store import normalize

def execute(job):
    if job.get('action')=='infer':
        import infer
        source=job['source']
        if not source.lower().endswith('.docx'):
            source=docx_fmt.convert_to_docx(source)
            if not source:raise ValueError('无法转换样本：请安装 Word 或 LibreOffice，或先另存为 .docx')
        rules,notes=infer.infer(source)
        return {'ok':True,'rules':normalize(rules),'notes':notes}
    if job.get('action')=='environment':
        import fontembed, platform, shutil
        from platform_support import data_directory
        rules=job['rules']
        dirs=docx_fmt.paths.font_dirs(rules['字体嵌入']['字体目录'])
        index=fontembed.index_fonts(fontembed.font_dirs(dirs))
        lines=['文矩环境检测',f'系统：{platform.system()} {platform.machine()}',f'Python：{platform.python_version()}',f'libc：{platform.libc_ver()}',f'数据目录：{data_directory(ROOT)}',f'已识别字体家族：{len(index)}']
        fonts={v for k,v in rules['字体'].items() if not k.startswith('_') and k!='模式'}|{rules['页码']['字体'],rules['页码']['中文字体']}
        for group in ('公文','红头'):
            if rules.get(group,{}).get('启用'):fonts.update(v for k,v in rules[group].items() if k.endswith('字体'))
        import fontfallback
        fontfallback.reset_index()
        for font in sorted(fonts):
            chosen, found = fontfallback.choose(font)
            if found and chosen == font:
                lines.append('可用：' + font)
            elif found:
                lines.append('可用：' + font + ' → 本机使用 ' + chosen)
            else:
                lines.append('未找到：' + font + '（' + fontfallback.LICENSE.get(font, '请自行提供字体文件') + '）')
        lines.append('LibreOffice：'+(shutil.which('soffice') or shutil.which('libreoffice') or '未在 PATH 中发现'))
        if sys.platform.startswith('win'):
            import winreg
            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,'Word.Application'):lines.append('Microsoft Word：已注册')
            except OSError:lines.append('Microsoft Word：未检测到')
        lines.append('DOCX 整理不依赖 Office；旧 DOC 转换需要本机转换组件。')
        return {'ok':True,'reportText':'\n'.join(lines)}
    rules=json.loads((ROOT/'core/rules.json').read_text('utf-8-sig'))
    if 'rules' in job:rules=normalize(job['rules'])
    else:
        s=job['settings']
        rules=apply_template(rules,s.get('template','unit'))
        rules['页码'].update({'左侧字符':s['prefix'],'右侧字符':s['suffix'],
            '字体':s['font'],'中文字体':s['font'],'字号':float(s['size']),
            '字间距':float(s['spacing']),'位置':s['alignment'],'起始位置':s['start']})
    output, report=docx_fmt.process_file(job['source'],rules)
    if not output:raise ValueError(report or '文档处理失败')
    return {'ok':True,'output':output,'report':report}

if __name__=='__main__':
    path=Path(sys.argv[1])
    try: result=execute(json.loads(path.read_text('utf-8')))
    except Exception: result={'ok':False,'error':traceback.format_exc()}
    (path.parent/'result.json').write_text(json.dumps(result,ensure_ascii=False),'utf-8')
    sys.exit(0 if result['ok'] else 1)
