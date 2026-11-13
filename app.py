import sys, json, shutil, uuid, os, copy, re
from pathlib import Path
from platform_support import data_directory, configure_rendering
configure_rendering()
from PySide6.QtCore import QObject, Signal, Slot, Property, QUrl, QProcess, QTimer, qInstallMessageHandler, Qt
from PySide6.QtGui import QGuiApplication, QDesktopServices, QIcon, QPalette, QColor, QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication, QFileDialog
from templates import CATALOG
from preset_store import PresetStore, normalize, checked, sections, fields, SIZES, BASE
from appearance import Appearance

ROOT = Path(__file__).resolve().parent
DATA = data_directory(ROOT)

def wenju_api():
    core = str(ROOT/'core')
    if core not in sys.path: sys.path.insert(0, core)
    import wenju_format
    return wenju_format

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
    rulesChanged = Signal()
    libraryChanged = Signal()
    errorRaised = Signal(str)
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
        self.section='页面'
        self.task_kind='process'
        if not (DATA/'current.json').exists() and self.settings:
            if self.store.find(self.settings.get('template','unit')):self.store.select(self.settings.get('template','unit'))
            self.updatePage(self.settings)

    @Property('QVariantList', notify=changed)
    def files(self): return self.rows
    @Property(str, notify=changed)
    def status(self): return self.message
    @Property(bool, notify=changed)
    def busy(self): return self.running
    @Property('QVariantMap', constant=True)
    def saved(self): return self.settings
    @Property('QVariantList', notify=libraryChanged)
    def templates(self):
        rows=[]
        for t in self.store.items():
            r=t['rules'];p=r['页码'];body=r['正文'];size=body['字号']
            heading={'汉字顿号':'一、（一）','多级数字':'1 / 1.1','第X章':'第一章','数字点':'1.'}.get(r['标题']['一级']['格式'],r['标题']['一级']['格式'])
            page=p['左侧字符']+'1'+p['右侧字符'] if p['启用'] else '无页码'
            rows.append({**{k:v for k,v in t.items() if k!='rules'},'font':r['字体']['正文'],'size':size,'line':body['行距值'],
                'bodySummary':r['字体']['正文']+' · '+(str(size)+' 磅' if isinstance(size,(float,int)) else size),
                'lineSummary':body['行距类型']+' '+str(body['行距值'])+(' 倍' if body['行距类型']=='多倍' else ' 磅' if body['行距类型'] in ('固定值','最小值') else ''),
                'headingSummary':heading+' · '+str(r['标题']['级数'])+' 级',
                'pageSummary':page+' · '+p['位置'].replace('底部','') if p['启用'] else page,
                'marginSummary':'上 '+str(r['页面']['上边距'])+' / 下 '+str(r['页面']['下边距'])+' / 左 '+str(r['页面']['左边距'])+' / 右 '+str(r['页面']['右边距'])+' cm'})
        return rows
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
                self.rows.append(dict(path=p, name=Path(p).name, state='等待整理', output='',report=''))
                known.add(p)
        self.changed.emit()

    @Slot()
    def choose(self):
        paths, _ = QFileDialog.getOpenFileNames(None, '选择文档', '', '文档 (*.docx *.doc *.wps *.rtf *.wenju)')
        self.add(paths)

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
        if not self.running: self.rows = []; self.changed.emit()

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
        self.queue = list(range(len(self.rows)))
        self.running = True
        self.next_file()

    @Slot()
    def cancel(self):
        self.queue = []
        self.message = '将在当前文档完成后停止'
        self.changed.emit()

    def next_file(self):
        if not self.queue:
            self.running = False
            self.message = '任务结束 · 可点击已完成的文档打开结果'
            self.changed.emit(); return
        self.current = self.queue.pop(0)
        row = self.rows[self.current]
        row['output']='';row['report']='';row.pop('error',None)
        row['state'] = '正在整理…'
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
        job=jobdir/'task.json'
        job.write_text(json.dumps(payload,ensure_ascii=False),'utf-8')
        self.result_file = jobdir/'result.json'
        self.proc = QProcess(self)
        self.proc.setProgram(sys.executable)
        self.proc.setArguments([str(ROOT/'worker.py'),str(job)])
        self.proc.finished.connect(self.finished)
        self.proc.errorOccurred.connect(self.process_error)
        self.proc.start()
        self.changed.emit()

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.running=False;self.error('后台进程启动失败，请检查运行库')

    def finished(self, code, _status):
        if self.task_kind!='process':
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
            row['output'] = result['output']; row['report'] = result.get('report',''); row['state'] = '已完成 · 点击打开'
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

QQuickStyle.setStyle('Basic')
app = QApplication(sys.argv)
app.styleHints().setColorScheme(Qt.ColorScheme.Light)
palette=QPalette()
for role,color in [(QPalette.Window,'#f4f6f9'),(QPalette.WindowText,'#22344a'),(QPalette.Base,'#f9fafc'),(QPalette.Text,'#22344a'),(QPalette.Button,'#ffffff'),(QPalette.ButtonText,'#22344a'),(QPalette.Highlight,'#245a83'),(QPalette.HighlightedText,'#ffffff')]:
    palette.setColor(role,QColor(color))
app.setPalette(palette)
app.setApplicationName('文矩')
app.setOrganizationName('WenJu')
app.setWindowIcon(QIcon(str(ROOT/'core/素材/文矩_图标_512.png')))
app.setFont(__import__('PySide6.QtGui',fromlist=['QFont']).QFont('Microsoft YaHei UI',10))
appearance=Appearance(DATA,app)
bridge = Bridge()
engine = QQmlApplicationEngine()
engine.rootContext().setContextProperty('bridge',bridge)
engine.rootContext().setContextProperty('appearance',appearance)
engine.rootContext().setContextProperty('startupAnimation',appearance.showIntro and os.environ.get('WENJU_LOW_POWER')!='1' and not any(a in sys.argv for a in ('--smoke','--capture','--capture-themes')))
engine.load(QUrl.fromLocalFile(str(ROOT/'Main.qml')))
if not engine.rootObjects(): sys.exit(1)
window = engine.rootObjects()[0]
incoming=[arg for arg in sys.argv[1:] if not arg.startswith('--') and Path(arg).is_file()]
if incoming:bridge.add(incoming)
if '--test-opening' in sys.argv:
    from PySide6.QtTest import QTest
    from PySide6.QtCore import QPoint
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
    from PySide6.QtTest import QTest
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
app.aboutToQuit.connect(lambda: bridge.proc.waitForFinished(30000) if bridge.running and bridge.proc else None)
if '--smoke' in sys.argv:
    # Integration test runs with an isolated WENJU_DATA_DIR, never user presets.
    from PySide6.QtTest import QTest
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtWidgets import QFileDialog
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
exit_code=app.exec()
import shiboken6
shiboken6.delete(engine)
sys.exit(exit_code)
