import sys, json, shutil, uuid, os, copy, re, datetime
from pathlib import Path
from platform_support import data_directory, configure_rendering
configure_rendering()
from qt_compat import (
    QObject, Signal, Slot, Property, QUrl, QProcess, QTimer, qInstallMessageHandler, Qt, QMimeData, QMetaObject,
    QGuiApplication, QDesktopServices, QIcon, QPalette, QColor, QFontDatabase, QFont,
    QQmlApplicationEngine, QQuickWindow, QQuickStyle, QApplication, QFileDialog,
    QTest, QPoint, QPointF, exec_app, delete_qobject, set_color_scheme, quick_style,
    failed_to_start,
)
from templates import CATALOG
from preset_store import PresetStore, normalize, checked, sections, fields, SIZES, BASE
from appearance import Appearance

ROOT = Path(__file__).resolve().parent
DATA = data_directory(ROOT)
sys.path.insert(0, str(ROOT / 'core'))
import fontfallback

def wenju_modules():
    core = str(ROOT / 'core')
    if core not in sys.path:
        sys.path.insert(0, core)
    import clipboard_import
    import wenju_format
    return clipboard_import, wenju_format

def wenju_api():
    return wenju_modules()[1]

def source_document(path):
    wenju_api()
    path = str(path)
    if path.lower().endswith(('.docx', '.wenju')): return path
    import docx_fmt
    converted = docx_fmt.convert_to_docx(path)
    if not converted: raise ValueError('无法读取 %s，请先另存为 .docx' % Path(path).name)
    return converted

def qt_log(kind, context, message):
    with (DATA/'界面日志.txt').open('a',encoding='utf-8') as log: log.write(message+'\n')
qInstallMessageHandler(qt_log)

class Bridge(QObject):
    changed = Signal()
    reportReady = Signal(str)
    batchFinished = Signal(str)
    rulesChanged = Signal()
    libraryChanged = Signal()
    errorRaised = Signal(str)
    convertFinished = Signal(str)
    importProgressChanged = Signal()
    clipboardStarted = Signal()
    clipboardFinished = Signal(str)
    def __init__(self):
        super().__init__()
        self.rows = []
        self.message = '准备就绪 · 文件仅在本机处理'
        self.running = False
        self.proc = None
        self.queue = []
        self.settings = {}
        try: self.settings = json.loads((DATA/'page.json').read_text('utf-8'))
        except (OSError, ValueError): pass
        self.store=PresetStore(DATA)
        self.font_notice=fontfallback.guidance(self.store.rules)
        self.section='页面'
        self.task_kind='process'
        self.overall_value=0
        self.progress_file=None
        self.progress_timer=QTimer(self)
        self.progress_timer.setInterval(120)
        self.progress_timer.timeout.connect(self.poll_progress)
        self.convert_rows=[]
        self.convert_overall=0
        self.convert_mode='preserve'
        self.convert_paste=''
        self.convert_queue=[]
        self.convert_total=0
        self.convert_pos=0
        self.convert_stopped=False
        self._convert_closed=False
        self._convert_succeeded=[]
        self._convert_failed=[]
        self._convert_skipped=[]
        self._convert_title='转换完成'
        self._convert_dir=None
        self._progress_path=None
        self._poll=None
        self.import_progress = 0
        self.clipboard_doc = None
        self.clipboard_docx = ''
        self.clipboard_wenju = ''
        self.clipboard_brush = False
        self._importing = False
        if not (DATA/'current.json').exists() and self.settings:
            if self.store.find(self.settings.get('template','unit')):self.store.select(self.settings.get('template','unit'))
            self.updatePage(self.settings)

    @Property('QVariantList', notify=changed)
    def files(self): return self.rows
    @Property('QVariantList', notify=changed)
    def convertFiles(self): return self.convert_rows
    @Property(int, notify=changed)
    def convertOverall(self): return int(self.convert_overall)
    @Property(str, notify=changed)
    def convertMode(self): return self.convert_mode
    @Property(str, notify=changed)
    def status(self): return self.message
    @Property(bool, notify=changed)
    def busy(self): return self.running
    @Property(int, notify=changed)
    def overall(self): return self.overall_value
    @Property(int, notify=importProgressChanged)
    def importProgress(self): return self.import_progress
    @Property('QVariantMap', constant=True)
    def saved(self): return self.settings
    @Property('QVariantList', notify=libraryChanged)
    def templates(self):
        rows=[]
        for t in self.store.items():
            r=t['rules'];p=r['页码'];body=r['正文'];size=body['字号']
            heading={'汉字顿号':'一、（一）','多级数字':'1 / 1.1','第X章':'第一章','数字点':'1.'}.get(r['标题']['一级']['格式'],r['标题']['一级']['格式'])
            page=p['左侧字符']+'1'+p['右侧字符'] if p['启用'] else '无页码'
            shown, found = fontfallback.choose(r['字体']['正文'])
            body_font = shown if found else shown + '（未安装）'
            rows.append({**{k:v for k,v in t.items() if k!='rules'},'font':body_font,'size':size,'line':body['行距值'],
                'bodySummary':body_font+' · '+(str(size)+' 磅' if isinstance(size,(float,int)) else size),
                'lineSummary':body['行距类型']+' '+str(body['行距值'])+(' 倍' if body['行距类型']=='多倍' else ' 磅' if body['行距类型'] in ('固定值','最小值') else ''),
                'headingSummary':heading+' · '+str(r['标题']['级数'])+' 级',
                'pageSummary':page+' · '+p['位置'].replace('底部','') if p['启用'] else page,
                'marginSummary':'上 '+str(r['页面']['上边距'])+' / 下 '+str(r['页面']['下边距'])+' / 左 '+str(r['页面']['左边距'])+' / 右 '+str(r['页面']['右边距'])+' cm'})
        return rows
    @Property(str, constant=True)
    def fontNotice(self): return self.font_notice
    @Slot(str)
    def installFont(self, path):
        try:
            self.message = fontfallback.install_user_font(path)
            self.font_notice = fontfallback.guidance(self.store.rules)
        except Exception as exc:
            self.message = '字体未能安装：' + str(exc)
        self.changed.emit()
    @Property(str,notify=rulesChanged)
    def selectedId(self):return self.store.selected
    @Property(str,notify=rulesChanged)
    def selectedName(self):
        t=self.store.find(self.store.selected);return t['name'] if t else '未命名方案'
    @Property(bool,notify=rulesChanged)
    def dirty(self):return self.store.dirty
    @Property(bool,notify=rulesChanged)
    def personal(self):
        t=self.store.find(self.store.selected);return bool(t and not t.get('builtin'))
    @Property('QVariantMap',notify=rulesChanged)
    def pageSettings(self):
        p=self.store.rules['页码']
        return dict(prefix=p['左侧字符'],suffix=p['右侧字符'],font=p['字体'],size=SIZES.get(p['字号'],p['字号']),spacing=p['字间距'],alignment=p['位置'],start=p['起始位置'],enabled=p['启用'],uniform=p['统一字体'])
    @Property('QVariantList',constant=True)
    def ruleSections(self):return sections(self.store.rules)
    @Property('QVariantList',notify=rulesChanged)
    def ruleFields(self):
        rows=fields(self.store.rules,self.section)
        for row in rows:
            if row['kind']=='choice' and row['editable'] and not row['path'].endswith('.字号'):
                row['values']=list(dict.fromkeys(row['values']+QFontDatabase.families()));row['labels']=row['values']
        return rows
    @Property('QStringList',constant=True)
    def fontNames(self):return list(dict.fromkeys(['宋体','仿宋','黑体','楷体','Times New Roman','Arial']+QFontDatabase.families()))
    @Slot(str, result=str)
    def paintFont(self, name):
        chosen, found = fontfallback.choose(name or "")
        return chosen if found else (name or "")
    @Property(str,notify=rulesChanged)
    def sectionName(self):return self.section.replace('.',' / ')
    @Property(str,notify=rulesChanged)
    def sectionTip(self):return next((s['tip'] for s in sections(self.store.rules) if s['key']==self.section),'')
    def error(self,exc):
        self.message=str(exc);self.errorRaised.emit(str(exc));self.changed.emit()
    def rule_update(self):
        self.store.persist();self.rulesChanged.emit();self.changed.emit()
    @Slot(str)
    def setSection(self,section):
        if any(s['key']==section for s in sections(self.store.rules)):
            self.section=section;self.rulesChanged.emit()
    @Slot(str,'QVariant',result=bool)
    def editRule(self,path,value):
        try:
            keys=path.split('.');obj=self.store.rules;default=BASE
            for k in keys[:-1]:obj=obj[k];default=default[k]
            if isinstance(default[keys[-1]],list) and isinstance(value,str):value=[x.strip() for x in re.split('[、,，;；\n]',value) if x.strip()]
            value=checked(path,value,default[keys[-1]])
            if obj[keys[-1]]==value:return True
            obj[keys[-1]]=value
            if path=='页码.格式':obj['左侧字符'],obj['右侧字符']={'1':('',''),'- 1 -':('- ',' -'),'第 1 页':('第 ',' 页')}[value]
            self.store.dirty=True;self.rule_update();return True
        except Exception as exc:self.error(exc);return False
    @Slot('QVariantMap')
    def updatePage(self,s):
        try:
            r=copy.deepcopy(self.store.rules);p=r['页码']
            for source,target in [('prefix','左侧字符'),('suffix','右侧字符'),('font','字体'),('size','字号'),('spacing','字间距'),('alignment','位置'),('start','起始位置')]:
                if source in s:p[target]=s[source]
            if 'enabled' in s:p['启用']=s['enabled']
            if 'uniform' in s:p['统一字体']=s['uniform']
            r=normalize(r)
            if r!=self.store.rules:self.store.rules=r;self.store.dirty=True;self.rule_update()
        except Exception as exc:self.error(exc)
    @Slot(str)
    def selectTemplate(self,id):
        try:self.store.select(id);self.rulesChanged.emit();self.changed.emit()
        except Exception as exc:self.error(exc)
    @Slot(str,result=bool)
    def saveAs(self,name):
        try:
            self.store.save_as(name);self.message='模板已另存：'+name;self.libraryChanged.emit();self.rulesChanged.emit();self.changed.emit();return True
        except Exception as exc:self.error(exc);return False
    @Slot()
    def saveTemplate(self):
        try:self.store.save();self.message='模板修改已保存';self.rulesChanged.emit();self.libraryChanged.emit();self.changed.emit()
        except Exception as exc:self.error(exc)
    @Slot(str)
    def deleteTemplate(self,id):
        try:self.store.delete(id);self.libraryChanged.emit();self.rulesChanged.emit();self.changed.emit()
        except Exception as exc:self.error(exc)
    @Slot()
    def importTemplates(self):
        paths,_=QFileDialog.getOpenFileNames(None,'导入文矩模板','','文矩模板 (*.json *.zip)')
        if paths:self.import_paths(paths)
    def import_paths(self,paths):
        try:
            added=self.store.import_files(paths);self.message=f'已导入 {len(added)} 套模板，同名模板自动编号';self.libraryChanged.emit();self.changed.emit()
        except Exception as exc:self.error(exc)
    @Slot(bool)
    def exportTemplates(self,all_templates):
        path,_=QFileDialog.getSaveFileName(None,'导出模板',str(DATA/('文矩全部模板.json' if all_templates else '文矩当前模板.json')),'JSON (*.json)')
        if path:
            try:
                (self.store.export_all if all_templates else self.store.export_current)(path)
                self.message='已导出：'+path;self.changed.emit()
            except Exception as exc:self.error(exc)
    @Slot(str)
    def addPaths(self,text):self.add([p.strip().strip('"') for p in text.splitlines() if p.strip()])
    @Slot()
    def fontDirectory(self):
        path=QFileDialog.getExistingDirectory(None,'添加字体目录')
        if path:
            dirs=list(self.store.rules['字体嵌入']['字体目录'])
            if path not in dirs:dirs.append(path)
            self.editRule('字体嵌入.字体目录',dirs)
    @Slot()
    def inferTemplate(self):
        if self.running:return
        path,_=QFileDialog.getOpenFileName(None,'选择已排好版的样本文档','','文档 (*.docx *.doc *.wps *.rtf)')
        if path:self.start_tool('infer',path)
    @Slot()
    def environment(self):
        if not self.running:return self.start_tool('environment')
    def start_tool(self,kind,source=None):
        self.task_kind=kind;self.running=True;self.queue=[]
        jobdir=DATA/'任务'/uuid.uuid4().hex;jobdir.mkdir(parents=True)
        job={'action':kind,'rules':copy.deepcopy(self.store.rules)}
        if source:
            dst=jobdir/Path(source).name;shutil.copy2(source,dst);job['source']=str(dst)
        self.message='正在识别样本文档…' if kind=='infer' else '正在检测运行环境和字体…'
        self.launch(jobdir,job);self.changed.emit()

    def add(self, paths):
        imports=[p for p in paths if Path(p).suffix.lower() in ('.json','.zip') and Path(p).is_file()]
        if imports:self.import_paths(imports)
        known = {r['path'] for r in self.rows}
        for p in paths:
            p = str(Path(p).resolve())
            if p not in known and Path(p).suffix.lower() in ('.docx','.doc','.wps','.rtf','.wenju') and Path(p).is_file():
                self.rows.append(dict(path=p, name=Path(p).name, state='等待整理', output='', report='', percent=0))
                known.add(p)
        self.changed.emit()

    @Slot()
    def choose(self):
        paths, _ = QFileDialog.getOpenFileNames(None, '选择文档', '', '文档 (*.docx *.doc *.wps *.rtf *.wenju)')
        self.add(paths)

    def _set_import_progress(self, value):
        self.import_progress = int(value)
        self.importProgressChanged.emit()
        app = QGuiApplication.instance()
        if app is not None:
            app.processEvents()

    def _write_clipboard(self, doc, brush, wenju_path, docx_path):
        clip, wenju = wenju_modules()
        wenju.save(doc, wenju_path)
        self._set_import_progress(90)
        rules = clip.brush_styles(copy.deepcopy(self.store.rules)) if brush else None
        wenju.to_docx(doc, docx_path, template=rules)
        self._set_import_progress(100)

    @Slot(bool)
    def importClipboard(self, brush):
        if self.running or self._importing:
            return
        clip, _wenju = wenju_modules()
        self._importing = True
        self.running = True
        self.clipboard_brush = bool(brush)
        self.import_progress = 0
        self.importProgressChanged.emit()
        self.message = '正在从剪贴板导入…'
        self.changed.emit()
        self.clipboardStarted.emit()
        QGuiApplication.processEvents()
        try:
            doc = clip.document_from_mime(QGuiApplication.clipboard().mimeData(), lambda value: self._set_import_progress(min(80, int(value * 0.8))))
            out = DATA / '输出'
            out.mkdir(parents=True, exist_ok=True)
            stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
            wenju_path = out / ('剪贴板-%s.wenju' % stamp)
            docx_path = out / ('剪贴板-%s.docx' % stamp)
            self._write_clipboard(doc, brush, wenju_path, docx_path)
            report_path = out / ('剪贴板-%s.txt' % stamp)
            report_path.write_text('已从剪贴板导入\n%s\n%s\n' % (wenju_path, docx_path), encoding='utf-8')
            self.clipboard_doc = doc
            self.clipboard_docx = str(docx_path)
            self.clipboard_wenju = str(wenju_path)
            self.rows.append(dict(path=str(docx_path), name=docx_path.name, state='已从剪贴板导入', output=str(docx_path), report=str(report_path), wenju=str(wenju_path)))
            self.message = '已从剪贴板导入'
            self.clipboardFinished.emit('已导入 %d 个块，并保存两份文件。\n%s\n%s' % (len(doc.blocks), wenju_path, docx_path))
        except clip.ClipboardEmpty as exc:
            self.error(exc)
        except Exception as exc:
            self.error(exc)
        finally:
            self.running = False
            self._importing = False
            self.changed.emit()

    @Slot(bool)
    def setClipboardBrush(self, brush):
        brush = bool(brush)
        if brush == self.clipboard_brush and self.clipboard_doc is None:
            return
        self.clipboard_brush = brush
        if self.clipboard_doc is None or not self.clipboard_docx:
            self.message = '按模板刷格式' if brush else '保留原格式'
            self.changed.emit()
            return
        try:
            self._write_clipboard(self.clipboard_doc, brush, self.clipboard_wenju, self.clipboard_docx)
            self.message = '已按模板重新导出' if brush else '已按原格式重新导出'
            self.clipboardFinished.emit(self.message + '\n' + self.clipboard_docx)
        except Exception as exc:
            self.error(exc)
        self.changed.emit()

    @Slot('QVariantList')
    def dropFiles(self, urls): self.add([QUrl(u).toLocalFile() for u in urls])

    @Slot()
    def sample(self): self.add([ROOT/'core/样例/样例_整理前.docx'])

    def _write_row(self, index, dest):
        if not 0 <= index < len(self.rows): raise IndexError('没有这份文档')
        wenju_api().convert_file(source_document(self.rows[index]['path']), dest)
        self.rows[index]['output'] = dest
        self.rows[index]['state'] = '已保存 · 点击打开'
        self.message = '已保存 ' + Path(dest).name
        self.changed.emit()

    def _ask_save(self, index, suffix, title, label):
        try:
            if self.running or not 0 <= index < len(self.rows): return
            stem = Path(self.rows[index]['name']).stem
            folder = DATA/'输出'
            folder.mkdir(parents=True, exist_ok=True)
            path, _ = QFileDialog.getSaveFileName(None, title, str(folder/(stem+suffix)), label)
            if not path: return
            if not path.lower().endswith(suffix): path += suffix
            self._write_row(index, path)
        except Exception as exc:
            self.error(exc)

    @Slot(int)
    def saveWenju(self, index):
        self._ask_save(index, '.wenju', '保存为文矩', '文矩文档 (*.wenju)')

    @Slot(int)
    def exportDocx(self, index):
        self._ask_save(index, '.docx', '导出 DOCX', 'Word 文档 (*.docx)')

    @Slot()
    def clear(self):
        if not self.running: self.rows = []; self.overall_value = 0; self.changed.emit()

    @Slot(int, int)
    def reorder(self, src, dst):
        if self.running or src == dst: return
        if not (0 <= src < len(self.rows) and 0 <= dst < len(self.rows)): return
        self.rows.insert(dst, self.rows.pop(src))
        self.changed.emit()

    @Slot()
    def mergeExport(self):
        if self.running: return
        picked = [(i, row) for i, row in enumerate(self.rows) if str(row['path']).lower().endswith('.wenju')]
        if not picked:
            self.message = '请先添加 .wenju 文档'; self.changed.emit(); return
        self.task_kind = 'merge'
        self.running = True
        self.overall_value = 0
        jobdir = DATA/'输出'/uuid.uuid4().hex[:10]
        jobdir.mkdir(parents=True)
        sources, indexes = [], []
        for i, row in picked:
            dest = jobdir/('%02d_%s' % (len(sources), Path(row['path']).name))
            try: shutil.copy2(row['path'], dest)
            except OSError as exc:
                row['state'] = '失败：无法读取源文件'; row['error'] = str(exc); continue
            sources.append(str(dest)); indexes.append(i)
            row['percent'] = 0; row['output'] = ''; row['state'] = '等待合稿'
        if not sources:
            self.running = False; self.error('没有可读的 .wenju 文档'); return
        font = self.store.rules.get('字体', {}).get('正文', '仿宋')
        self.merge_indexes = indexes
        self.message = '正在合稿 %d 份文档' % len(sources)
        self.launch(jobdir, {'action':'merge', 'sources':sources, 'indexes':indexes,
            'wenju':str(jobdir/'合稿.wenju'), 'docx':str(jobdir/'合稿.docx'),
            'template':{'font':font, 'number':'多级数字'}})

    def addConvert(self, paths):
        if self.running: return
        known={r.get('path') for r in self.convert_rows}
        for raw in paths:
            if not raw: continue
            path=Path(raw)
            if not path.is_file(): continue
            resolved=str(path.resolve())
            if resolved in known: continue
            self.convert_rows.append({'name':path.name,'path':resolved,'percent':0,'state':'等待','message':'','output':''})
            known.add(resolved)
        self.changed.emit()

    @Slot()
    def chooseConvert(self):
        paths,_=QFileDialog.getOpenFileNames(None,'选择要转换的文件','','文档 (*.docx *.doc *.xlsx *.xls *.txt *.md *.markdown *.wenju)')
        self.addConvert(paths)

    @Slot('QVariantList')
    def dropConvert(self, urls):
        self.addConvert([QUrl(u).toLocalFile() for u in urls])

    @Slot()
    def clearConvert(self):
        if self.running: return
        self.convert_rows=[]
        self.convert_overall=0
        self.changed.emit()

    @Slot(str)
    def setConvertMode(self, mode):
        if mode in ('preserve','template'):
            self.convert_mode=mode
            self.changed.emit()

    @Slot(str)
    def setConvertPaste(self, text):
        self.convert_paste=text or ''

    @Slot()
    def startConvert(self):
        self._begin_batch('convert')

    @Slot()
    def exportConvert(self):
        self._begin_batch('export')

    def _begin_batch(self, action):
        if self.running: return
        items=[]
        if action=='convert':
            text=(self.convert_paste or '').strip()
            if text: items.append({'name':'粘贴的内容','text':text})
            for row in list(self.convert_rows):
                if row.get('path'): items.append({'name':row['name'],'path':row['path']})
            self._convert_title='转换完成'
        else:
            for row in list(self.convert_rows):
                output=row.get('output') or ''
                if output.lower().endswith('.wenju') and Path(output).is_file():
                    items.append({'name':row['name'],'path':output})
            self._convert_title='导出完成'
        if not items:
            self.message='请先拖入文件，或粘贴要转换的文字' if action=='convert' else '没有可导出的文矩文件'
            self.changed.emit(); return
        self.task_kind=action
        self.running=True
        self.convert_stopped=False
        self._convert_closed=False
        self.convert_queue=items
        self.convert_total=len(items)
        self.convert_pos=0
        self.convert_overall=0
        self._convert_succeeded=[]
        self._convert_failed=[]
        self._convert_skipped=[]
        self.convert_rows=[]
        for item in items:
            self.convert_rows.append({'name':item['name'],'path':item.get('path') or '','percent':0,'state':'等待','message':'','output':item.get('path') if action=='export' else ''})
        self._convert_dir=DATA/'输出'/uuid.uuid4().hex[:10]
        self._convert_dir.mkdir(parents=True, exist_ok=True)
        self.message='正在转换' if action=='convert' else '正在导出'
        self.changed.emit()
        self._launch_convert()

    def _launch_convert(self):
        if not self.convert_queue:
            self._convert_finish(); return
        item=self.convert_queue.pop(0)
        row=self.convert_rows[self.convert_pos]
        row['state']='正在转换' if self.task_kind=='convert' else '正在导出'
        row['percent']=8
        row['message']='正在读取'
        self.convert_overall=int((self.convert_pos*100+8)/max(1,self.convert_total))
        self.message=row['state']+' '+row['name']
        progress=self._convert_dir/'progress.json'
        if progress.exists(): progress.unlink()
        template=copy.deepcopy(self.store.rules) if self.task_kind=='convert' and self.convert_mode=='template' else None
        self.changed.emit()
        self.launch(self._convert_dir,{
            'action':self.task_kind,
            'mode':self.convert_mode,
            'template':template,
            'items':[item],
            'outdir':str(self._convert_dir),
            'progress':str(progress),
        })

    def poll_progress(self):
        if self.task_kind in ('convert','export'):
            path=self._progress_path
            if path is None or not path.is_file(): return
            if not (0<=self.convert_pos<len(self.convert_rows)): return
            try: snap=json.loads(path.read_text('utf-8'))
            except (OSError, ValueError): return
            files=snap.get('files') or []
            if not files: return
            file=files[0]
            row=self.convert_rows[self.convert_pos]
            percent=int(file.get('percent') or 0)
            if percent >= int(row.get('percent') or 0):
                row['percent']=percent
            if file.get('message'): row['message']=file['message']
            if file.get('state') and file.get('state') != '等待':
                row['state']=file['state']
            self.convert_overall=int((self.convert_pos*100+row['percent'])/max(1,self.convert_total))
            self.changed.emit()
            return
        path=self.progress_file
        if not path or not Path(path).exists(): return
        try: data=json.loads(Path(path).read_text('utf-8'))
        except (OSError, ValueError): return
        if self.task_kind=='merge':
            for key, value in (data.get('rows') or {}).items():
                index=int(key)
                if 0<=index<len(self.rows):
                    self.rows[index]['percent']=int(value)
                    if int(value)<100: self.rows[index]['state']='正在处理 %d%%' % int(value)
            self.overall_value=int(data.get('overall') or 0)
        elif self.task_kind=='process' and self.rows:
            pct=int(data.get('percent') or 0)
            row=self.rows[self.current]
            row['percent']=pct
            row['state']='正在整理 %d%%' % pct
            self.overall_value=int(sum(int(item.get('percent') or 0) for item in self.rows)/len(self.rows))
        else:
            return
        self.changed.emit()

    def _apply_convert_result(self):
        if getattr(self, '_convert_closed', False): return
        self.progress_timer.stop()
        if self._poll: self._poll.stop()
        row=self.convert_rows[self.convert_pos] if 0<=self.convert_pos<len(self.convert_rows) else None
        try:
            result=json.loads(self.result_file.read_text('utf-8'))
            if not result.get('ok'): raise RuntimeError(result.get('error') or '转换失败')
            file=(result.get('snapshot') or {}).get('files',[{}])[0]
            if row is not None:
                row['percent']=100
                row['state']=file.get('state') or '失败'
                row['message']=file.get('message') or ''
                if self.task_kind=='convert': row['output']=file.get('output') or ''
                else: row['docx']=file.get('docx') or ''
            if file.get('state')=='成功':
                label=row['name'] if row is not None else '未命名'
                if self.task_kind=='export' and file.get('docx'):
                    label=label+' → '+Path(file['docx']).name
                self._convert_succeeded.append(label)
            else:
                self._convert_failed.append({'name':row['name'] if row is not None else '未命名','message':file.get('message') or '转换失败'})
        except Exception as exc:
            message=str(exc).splitlines()[-1][:180] or '转换失败'
            if row is not None:
                row['percent']=100; row['state']='失败'; row['message']=message
            self._convert_failed.append({'name':row['name'] if row is not None else '未命名','message':message})
        if self.proc: self.proc.deleteLater()
        self.convert_pos += 1
        self.convert_overall=int(self.convert_pos*100/max(1,self.convert_total))
        self.changed.emit()
        if self.convert_queue:
            QTimer.singleShot(0,self._launch_convert); return
        self._convert_finish()

    def _convert_finish(self):
        if getattr(self, '_convert_closed', False): return
        self._convert_closed=True
        self.progress_timer.stop()
        if self._poll: self._poll.stop()
        self.convert_queue=[]
        while self.convert_pos < len(self.convert_rows):
            row=self.convert_rows[self.convert_pos]
            if row.get('state') in ('等待','正在转换','正在导出'):
                row['state']='未开始'
                self._convert_skipped.append(row.get('name') or '未命名')
            self.convert_pos += 1
        self.running=False
        self.convert_overall=100
        title='转换已停止' if self.convert_stopped and self.task_kind=='convert' else ('导出已停止' if self.convert_stopped else self._convert_title)
        self.message=title
        core=str(ROOT/'core')
        if core not in sys.path: sys.path.insert(0, core)
        import convert
        self.convertFinished.emit(convert.summary({'succeeded':self._convert_succeeded,'failed':self._convert_failed,'skipped':self._convert_skipped}, title))
        self.changed.emit()

    @Slot('QVariantMap')
    def save(self, settings):
        self.updatePage(settings)
        self.store.persist()
        self.message = '当前方案已保存；可另存为模板重复使用'
        self.changed.emit()

    @Slot('QVariantMap')
    def start(self, settings):
        if self.running: return
        if not self.rows:
            self.message = '请先添加文档，或点击「体验样例」'; self.changed.emit(); return
        if self.store.rules.get('红头',{}).get('启用') and not self.store.rules['红头']['机关名称'].strip():
            self.error('请先在设置 → 红头中填写机关名称，再开始整理。');return
        self.save(settings)
        self.batch_rules = copy.deepcopy(self.store.rules)
        self.task_kind='process'
        self._did_work=False
        self.queue = list(range(len(self.rows)))
        self.running = True
        self.next_file()

    @Slot()
    def cancel(self):
        self.queue = []
        self.convert_queue = []
        self.convert_stopped = True
        self.message = '将在当前文档完成后停止'
        self.changed.emit()

    def next_file(self):
        if not self.queue:
            self.running = False
            self.progress_timer.stop()
            self.overall_value = 100
            done = sum(1 for row in self.rows if row.get('output'))
            failed = sum(1 for row in self.rows if row.get('error'))
            self.message = '任务结束 · 可点击已完成的文档打开结果'
            if self._did_work or failed:
                self.batchFinished.emit('处理完成。成功 %d 份，失败 %d 份。' % (done, failed))
            self.changed.emit(); return
        self.current = self.queue.pop(0)
        row = self.rows[self.current]
        row['output']='';row['report']='';row.pop('error',None)
        row['percent'] = 0
        if str(row['path']).lower().endswith('.wenju'):
            row['state'] = '请使用合稿导出'
            self.changed.emit(); QTimer.singleShot(0, self.next_file); return
        row['state'] = '正在整理…'
        self._did_work = True
        self.message = '正在整理 ' + row['name']
        jobdir = DATA/'输出'/uuid.uuid4().hex[:10]
        jobdir.mkdir(parents=True)
        source = jobdir/row['name']
        try:shutil.copy2(row['path'], source)
        except OSError as exc:
            row['state']='失败：无法读取源文件';row['error']=str(exc);self.changed.emit();QTimer.singleShot(0,self.next_file);return
        self.launch(jobdir,{'source':str(source), 'rules':self.batch_rules})
        self.changed.emit()

    def launch(self,jobdir,payload):
        payload=dict(payload)
        payload['progress']=str(jobdir/'progress.json')
        self.progress_file=jobdir/'progress.json'
        job=jobdir/'task.json'
        job.write_text(json.dumps(payload,ensure_ascii=False),'utf-8')
        self.result_file = jobdir/'result.json'
        self.progress_timer.start()
        self.proc = QProcess(self)
        self.proc.setProgram(sys.executable)
        self.proc.setArguments([str(ROOT/'worker.py'),str(job)])
        self.proc.finished.connect(self.finished)
        self.proc.errorOccurred.connect(self.process_error)
        self._progress_path=Path(payload['progress']) if payload.get('progress') else None
        if self._progress_path is not None:
            if self._poll is None:
                self._poll=QTimer(self)
                self._poll.timeout.connect(self.poll_progress)
            self._poll.start(80)
        elif self._poll:
            self._poll.stop()
        self.proc.start()
        self.changed.emit()

    def process_error(self, error):
        if error != failed_to_start(QProcess):
            return
        self.progress_timer.stop()
        if self._poll: self._poll.stop()
        if self.task_kind in ('convert','export') and not getattr(self, '_convert_closed', False):
            if 0<=self.convert_pos<len(self.convert_rows):
                row=self.convert_rows[self.convert_pos]
                row['state']='失败'; row['percent']=100; row['message']='后台进程启动失败，请检查运行库'
                self._convert_failed.append({'name':row['name'],'message':row['message']})
                self.convert_pos += 1
            self.convert_stopped=True
            self._convert_finish()
            return
        self.running=False;self.error('后台进程启动失败，请检查运行库')

    def _finish_merge(self):
        self.progress_timer.stop(); self.running=False
        if self._poll: self._poll.stop()
        try:
            result=json.loads(self.result_file.read_text('utf-8'))
            if not result['ok']: raise RuntimeError(result['error'])
            for index in self.merge_indexes:
                row=self.rows[index]
                row['output']=result['output']; row['percent']=100; row['state']='已完成 · 点击打开'
            self.overall_value=100
            self.message='合稿完成'
            self.batchFinished.emit('合稿完成，已导出一份 Word。\n'+result['output'])
        except Exception as exc:
            self.error(exc)
        self.proc.deleteLater(); self.changed.emit()

    def finished(self, code, _status):
        if self.task_kind=='merge':
            self._finish_merge(); return
        if self.task_kind in ('convert','export'):
            self._apply_convert_result(); return
        if self.task_kind!='process':
            self.progress_timer.stop()
            try:
                result=json.loads(self.result_file.read_text('utf-8'))
                if not result['ok']:raise ValueError(result['error'])
                if self.task_kind=='infer':
                    self.store.rules=normalize(result['rules']);self.store.dirty=True;self.rule_update()
                    self.reportReady.emit('识别结果已载入当前工作方案，请复核后另存为模板。\n\n'+'\n'.join(result['notes']))
                else:self.reportReady.emit(result['reportText'])
                self.message='识别完成，请复核并另存为模板' if self.task_kind=='infer' else '环境检测完成'
            except Exception as exc:self.error(exc)
            self.running=False;self.proc.deleteLater();self.changed.emit();return
        row = self.rows[self.current]
        try:
            result = json.loads(self.result_file.read_text('utf-8'))
            if not result['ok']: raise RuntimeError(result['error'])
            row['output'] = result['output']; row['report'] = result.get('report',''); row['percent'] = 100; row['state'] = '已完成 · 点击打开'
        except Exception as exc:
            row['state'] = '失败：' + str(exc)[:100];row['error']=str(exc)
        self.proc.deleteLater()
        self.next_file()

    @Slot(int)
    def openFile(self, index):
        if 0 <= index < len(self.rows) and self.rows[index]['output']:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.rows[index]['output']))

    @Slot()
    def openOutput(self):
        p=DATA/'输出'; p.mkdir(exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    @Slot(int)
    def showReport(self,index):
        if 0 <= index < len(self.rows):
            path=self.rows[index].get('report')
            if path and Path(path).exists():self.reportReady.emit(Path(path).read_text('utf-8'))
            elif self.rows[index].get('error'):self.reportReady.emit(self.rows[index]['error'])
    @Slot()
    def help(self):self.reportReady.emit((ROOT/'使用说明.txt').read_text('utf-8-sig'))

def brand_icon():
    icon = QIcon()
    hicolor = ROOT / 'launcher' / 'icons' / 'hicolor'
    for path in sorted(hicolor.glob('*/apps/wenju.png')):
        icon.addFile(str(path))
    if icon.isNull():
        icon = QIcon(str(ROOT / 'core' / '素材' / '文矩_图标_512.png'))
    return icon

QQuickStyle.setStyle(quick_style())
# Desktop file name is read when the platform plugin starts. Setting it later
# leaves WM_CLASS as "app.py" and the taskbar icon does not match StartupWMClass.
if hasattr(QGuiApplication, 'setDesktopFileName'):
    QGuiApplication.setDesktopFileName('wenju')
# argv[0] becomes the X11 WM_CLASS instance. Keep it the same as StartupWMClass.
if sys.platform != 'win32':
    sys.argv[0] = 'wenju'
app = QApplication(sys.argv)
set_color_scheme(app, False)
palette=QPalette()
for role,color in [(QPalette.Window,'#f4f6f9'),(QPalette.WindowText,'#22344a'),(QPalette.Base,'#f9fafc'),(QPalette.Text,'#22344a'),(QPalette.Button,'#ffffff'),(QPalette.ButtonText,'#22344a'),(QPalette.Highlight,'#245a83'),(QPalette.HighlightedText,'#ffffff')]:
    palette.setColor(role,QColor(color))
app.setPalette(palette)
for font_file in fontfallback.application_font_files(ROOT):
    QFontDatabase.addApplicationFont(str(font_file))
fontfallback.reset_index()
app.setApplicationName('wenju')
if sys.platform == 'win32':
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('WenJu.Desktop.3.3')
app.setOrganizationName('WenJu')
app.setWindowIcon(brand_icon())
app.setFont(QFont('Microsoft YaHei UI',10))
appearance=Appearance(DATA,app)
bridge = Bridge()
engine = QQmlApplicationEngine()
engine.rootContext().setContextProperty('bridge',bridge)
engine.rootContext().setContextProperty('appearance',appearance)
engine.rootContext().setContextProperty('startupAnimation',appearance.showIntro and os.environ.get('WENJU_LOW_POWER')!='1' and not any(a in sys.argv for a in ('--smoke','--capture','--capture-themes','--test-convert-ui','--test-clipboard')))
engine.load(QUrl.fromLocalFile(str(ROOT/'Main.qml')))
if not engine.rootObjects(): sys.exit(1)
window = engine.rootObjects()[0]
if hasattr(window, 'setIcon'):
    window.setIcon(app.windowIcon())
incoming=[arg for arg in sys.argv[1:] if not arg.startswith('--') and Path(arg).is_file()]
if incoming:bridge.add(incoming)
if '--test-opening' in sys.argv:
    before=copy.deepcopy(bridge.store.rules)
    def opening_capture():
        assert window.property('page')==2
        o=window.findChild(QObject,'openingAnimation')
        assert o.property('playing')
        window.grabWindow().save(str(ROOT/'开场动画预览.png'))
    def opening_finished():
        o=window.findChild(QObject,'openingAnimation')
        if o.property('playing'):
            QTimer.singleShot(100,opening_finished)
            return
        o.setProperty('playing',True)
        QTimer.singleShot(200,opening_skip)
    def opening_skip():
        QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,QPoint(window.width()-65,45))
        assert not window.findChild(QObject,'openingAnimation').property('playing')
        assert bridge.store.rules==before
        print('PASS: opening animation completes, skip works, template homepage first, document rules unchanged')
        app.quit()
    QTimer.singleShot(1350,opening_capture)
    QTimer.singleShot(2100,opening_finished)
    QTimer.singleShot(8000,lambda:app.exit(2))
if '--test-library-ui' in sys.argv:
    import traceback
    def library_ui_test():
        try:
            home=window.findChild(QObject,'templateHome')
            home.setProperty('pageIndex',1);app.processEvents()
            assert home.property('pageIndex')==1
            home.setProperty('category','红头文件');app.processEvents()
            assert home.property('pageIndex')==0
            home.setProperty('pageIndex',1);app.processEvents()
            home.setProperty('query','工作通知');app.processEvents()
            assert home.property('pageIndex')==0
            bridge.selectTemplate('scene-01-01');bridge.setSection('红头');window.setProperty('page',3)
            bridge.editRule('红头.机关名称','示例科技中心文件')
            bridge.editRule('红头.发文字号','示例〔2026〕1号')
            assert bridge.store.rules['红头']['发文字号']=='示例〔2026〕1号'
            print('PASS: template pagination, category/search reset, redhead settings text editing')
            app.quit()
        except Exception:traceback.print_exc();app.exit(1)
    QTimer.singleShot(2600,library_ui_test)
    QTimer.singleShot(10000,lambda:app.exit(2))
if '--capture-themes' in sys.argv:
    theme_queue=list(appearance.themes)
    original_rules=copy.deepcopy(bridge.store.rules)
    def next_theme():
        if not theme_queue:
            appearance.setPreferences('night',appearance.fontFamily,18)
            window.setProperty('page',3)
            QTimer.singleShot(500,capture_large)
            return
        theme=theme_queue.pop(0)
        appearance.setPreferences(theme['id'],appearance.fontFamily,14)
        window.setProperty('page',4)
        QTimer.singleShot(500,lambda:capture_theme(theme['id']))
    def capture_theme(id):
        window.grabWindow().save(str(ROOT/('皮肤_'+id+'.png')))
        assert bridge.store.rules==original_rules
        next_theme()
    def capture_large():
        window.grabWindow().save(str(ROOT/'大字深色预览.png'))
        assert bridge.store.rules==original_rules
        print('PASS: five themes and large UI text; document rules unchanged')
        app.quit()
    QTimer.singleShot(700,next_theme)
if '--capture' in sys.argv:
    def capture():
        window.grabWindow().save(str(ROOT/'界面预览.png'))
        window.setProperty('page',1)
        QTimer.singleShot(700, capture_page)
    def capture_page():
        window.grabWindow().save(str(ROOT/'页码设计预览.png'))
        window.setProperty('page',2)
        QTimer.singleShot(700,capture_library)
    def capture_library():
        window.grabWindow().save(str(ROOT/'模板书架预览.png'))
        window.setProperty('page',3)
        QTimer.singleShot(700,capture_advanced)
    def capture_advanced():
        window.grabWindow().save(str(ROOT/'高级设置预览.png'))
        app.quit()
    QTimer.singleShot(1500,capture)
if '--test-convert-ui' in sys.argv:
    import traceback
    sample = DATA/'convert-sample.txt'
    def convert_ui():
        try:
            window.setProperty('page', 5)
            app.processEvents()
            panel = window.findChild(QObject, 'progressPanel')
            assert panel is not None, 'progress panel missing'
            assert panel.property('overall') == 0
            sample.write_text('界面转换\n', encoding='utf-8')
            rejected = sample.with_suffix('.xls')
            rejected.write_bytes(b'not-xlsx')
            bridge.addConvert([str(sample), str(rejected)])
            bridge.setConvertPaste('粘贴一行')
            bridge.setConvertMode('template')
            assert bridge.convertMode == 'template'
            bridge.setConvertMode('preserve')
            assert bridge.convertMode == 'preserve'
            bridge.startConvert()
            assert bridge.busy
            assert any(row['percent'] > 0 for row in bridge.convertFiles)
            app.processEvents()
            QTimer.singleShot(100, wait_convert)
        except Exception:
            traceback.print_exc(); app.exit(1)
    def wait_convert():
        try:
            if bridge.busy:
                QTimer.singleShot(100, wait_convert); return
            files = {row['name']: row for row in bridge.convertFiles}
            assert files['convert-sample.txt']['state'] == '成功', files
            assert files['convert-sample.txt']['percent'] == 100
            assert files['粘贴的内容']['state'] == '成功'
            assert files['convert-sample.xls']['state'] == '失败'
            assert '.xlsx' in files['convert-sample.xls']['message']
            assert bridge.convertOverall == 100
            panel = window.findChild(QObject, 'progressPanel')
            assert panel.property('overall') == 100
            assert bridge.status == '转换完成', bridge.status
            report = window.findChild(QObject, 'convertResult')
            text = report.property('text') or ''
            assert '成功 2 个' in text and '失败 1 个' in text, text
            assert 'convert-sample.txt' in text and 'convert-sample.xls' in text
            bridge.exportConvert()
            assert bridge.busy
            QTimer.singleShot(100, wait_export)
        except Exception:
            traceback.print_exc(); app.exit(1)
    def wait_export():
        try:
            if bridge.busy:
                QTimer.singleShot(100, wait_export); return
            assert bridge.status == '导出完成', bridge.status
            docx_rows = [row for row in bridge.convertFiles if row.get('docx')]
            assert len(docx_rows) == 2, bridge.convertFiles
            assert all(row['percent'] == 100 and row['state'] == '成功' for row in docx_rows)
            report = window.findChild(QObject, 'convertResult')
            text = report.property('text') or ''
            assert '导出完成' in text and '成功 2 个' in text, text
            print('PASS: convert page shows per-file progress, lists successes and failures, and exports docx')
            app.quit()
        except Exception:
            traceback.print_exc(); app.exit(1)
    QTimer.singleShot(800, convert_ui)
    QTimer.singleShot(20000, lambda: app.exit(2))
app.aboutToQuit.connect(lambda: bridge.proc.waitForFinished(30000) if bridge.running and bridge.proc else None)
if '--smoke' in sys.argv:
    # Integration test runs with an isolated WENJU_DATA_DIR, never user presets.
    import traceback
    def guarded(fn):
        def run():
            try:fn()
            except Exception:
                traceback.print_exc();app.exit(1)
        return run
    def later(fn,ms=300):QTimer.singleShot(ms,guarded(fn))
    def find_item(name):
        todo=[window.contentItem()]
        while todo:
            item=todo.pop()
            if item.objectName()==name:return item
            todo+=item.childItems()
        return window.findChild(QObject,name)
    def click_item(name):
        item=find_item(name)
        assert item is not None,name
        pt=item.mapToScene(QPointF(item.width()/2,item.height()/2)).toPoint()
        QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,pt)
        return item
    def begin_test():
        bridge.selectTemplate('unit')
        assert window.property('page')==2
        click_item('useTemplate_research')
        assert bridge.selectedId=='research' and window.property('page')==0
        click_item('nav_3')
        assert window.property('page')==3
        later(edit_field)
    def edit_field():
        item=click_item('field_页面.上边距')
        QTest.keyClick(window,Qt.Key_A,Qt.ControlModifier)
        for c in '3.25':QTest.keyClick(window,Qt.Key(ord(c)))
        QTest.keyClick(window,Qt.Key_Tab)
        assert bridge.store.rules['页面']['上边距']==3.25
        assert bridge.store.dirty
        bridge.editRule('正文.字号',19)
        bridge.editRule('页码.左侧字符','第 <& ')
        bridge.editRule('页码.右侧字符',' 页')
        bridge.editRule('页码.字间距',1.25)
        assert window.property('prefix')=='第 <& '
        # The top-right save-as button opens the in-window name dialog.
        QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,QPoint(window.width()-215,55))
        later(save_dialog)
    def save_dialog():
        window.grabWindow().save(str(DATA/'save-debug.png'))
        item=find_item('saveName');assert item is not None
        item.setProperty('text','Integration template')
        click_item('saveAsButton')
        assert bridge.personal and not bridge.dirty
        bridge.editRule('正文.行距值',30)
        bridge.saveTemplate()
        assert not bridge.dirty
        # Exercise the same dialog-backed slots as the toolbar with isolated paths.
        out=DATA/'roundtrip.json'
        QFileDialog.getSaveFileName=lambda *a,**k:(str(out),'JSON')
        bridge.exportTemplates(False)
        assert out.exists()
        count=len(bridge.templates)
        QFileDialog.getOpenFileNames=lambda *a,**k:([str(out)],'JSON')
        bridge.importTemplates()
        assert len(bridge.templates)==count+1
        bridge.setSection('正文')
        for section in bridge.ruleSections:
            bridge.setSection(section['key']);app.processEvents()
        bridge.setSection('正文')
        window.grabWindow().save(str(ROOT/'高级设置预览.png'))
        window.setProperty('page',0)
        bridge.sample()
        bridge.start(bridge.pageSettings)
        assert bridge.busy
        later(wait_processing)
    def wait_processing():
        if bridge.busy:return later(wait_processing)
        assert bridge.files[0]['output'],bridge.files
        assert bridge.batch_rules['正文']['字号']==19
        assert bridge.batch_rules['页面']['上边距']==3.25
        bridge.showReport(0)
        window.grabWindow().save(str(ROOT/'整理报告预览.png'))
        # Infer through its actual QProcess worker, then verify new page decorations.
        bridge.start_tool('infer',bridge.files[0]['output'])
        later(wait_inference)
    def wait_inference():
        if bridge.busy:return later(wait_inference)
        assert bridge.store.rules['正文']['字号']==19
        assert bridge.store.rules['页码']['左侧字符']=='第 <& '
        bridge.environment()
        later(wait_environment)
    def wait_environment():
        if bridge.busy:return later(wait_environment)
        assert bridge.status=='环境检测完成',bridge.status
        print('PASS: QML numeric editing, page sync, save-as dialog, personal save, import/export slots, all form sections, worker snapshot, DOCX output, inference, environment')
        app.quit()
    later(begin_test,700)
    QTimer.singleShot(60000,lambda:app.exit(2))
if '--test-clipboard' in sys.argv:
    import traceback
    def guarded_clip(fn):
        def run():
            try: fn()
            except Exception:
                traceback.print_exc(); app.exit(1)
        return run
    def find_item(name):
        todo=[window.contentItem()]
        while todo:
            item=todo.pop()
            if item.objectName()==name: return item
            todo += item.childItems()
        return window.findChild(QObject, name)
    def click_item(name):
        item=find_item(name)
        assert item is not None, name
        point=item.mapToScene(QPointF(item.width()/2, item.height()/2)).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
        return item
    def begin_clipboard():
        window.setProperty('page', 0)
        app.processEvents()
        ok=None
        todo=[window.contentItem()]
        while todo:
            item=todo.pop()
            if str(item.metaObject().className()).startswith('Button') and item.property('text') in ('OK', '确定') and item.property('visible'):
                ok=item
            todo += item.childItems()
        if ok is not None:
            point=ok.mapToScene(QPointF(ok.width()/2, ok.height()/2)).toPoint()
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
            app.processEvents()
        assert find_item('importClipboard').property('text')=='从剪贴板导入'
        assert find_item('clipboardBrush').property('checked') is False
        mime=QMimeData()
        mime.setData('text/html', (ROOT/'core/样例/clipboard/wps.html').read_bytes())
        mime.setText('plain should lose')
        QGuiApplication.clipboard().setMimeData(mime)
        click_item('importClipboard')
        app.processEvents()
        assert bridge.importProgress==100, bridge.importProgress
        assert bridge.files and bridge.files[-1]['state']=='已从剪贴板导入', bridge.files
        row=bridge.files[-1]
        wenju_path, docx_path=Path(row['wenju']), Path(row['output'])
        assert wenju_path.is_file() and docx_path.is_file() and Path(row['report']).is_file()
        _clip, wenju=wenju_modules()
        kept=wenju.load(wenju_path)
        heading=next(block for block in kept.blocks if block['type']=='heading')
        assert heading['runs'][0]['text']=='通知标题' and heading['runs'][0]['size_pt']==22
        original=wenju.from_docx(docx_path)
        assert next(block for block in original.blocks if block['type']=='heading')['runs'][0]['size_pt']==22
        done=find_item('clipDone')
        assert done is not None and done.property('visible')
        QMetaObject.invokeMethod(done, 'close')
        app.processEvents()
        click_item('clipboardBrush')
        app.processEvents()
        assert bridge.clipboard_brush is True
        brushed=wenju.from_docx(docx_path)
        assert next(block for block in brushed.blocks if block['type']=='heading')['runs'][0]['size_pt']==16
        assert wenju.load(wenju_path).blocks[0]['runs'][0]['size_pt']==22
        shot=Path('/tmp/clipboard-import.png')
        assert window.grabWindow().save(str(shot)), shot
        first=Path(bridge.files[-1]['wenju'])
        mime2=QMimeData()
        mime2.setHtml('<html><body><p>第二份完全不同</p></body></html>')
        QGuiApplication.clipboard().setMimeData(mime2)
        bridge.importClipboard(False)
        second=Path(bridge.files[-1]['wenju'])
        assert str(first)!=str(second) and first.is_file() and second.is_file()
        assert '通知标题' in ''.join(run.get('text','') for block in wenju.load(first).blocks if block.get('type')=='heading' for run in block.get('runs') or [])
        assert '第二份完全不同' in ''.join(run.get('text','') for block in wenju.load(second).blocks for run in block.get('runs') or [])
        QGuiApplication.clipboard().clear()
        app.processEvents()
        before=len(bridge.files)
        bridge.importClipboard(False)
        assert len(bridge.files)==before
        assert '没有可导入' in bridge.status, bridge.status
        print('PASS: clipboard button imports HTML, saves wenju and docx, brushes on toggle, rejects an empty clipboard')
        app.quit()
    QTimer.singleShot(800, guarded_clip(begin_clipboard))
    QTimer.singleShot(20000, lambda: app.exit(2))
exit_code=exec_app(app)
delete_qobject(engine)
sys.exit(exit_code)
