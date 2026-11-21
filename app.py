import subprocess
import zipfile
import sys, json, shutil, uuid, os, copy, re, datetime, tempfile
from pathlib import Path
from platform_support import data_directory, configure_rendering
configure_rendering()
from qt_compat import (
    QObject, Signal, Slot, Property, constant_property, QUrl, QProcess, QThread, QTimer, qInstallMessageHandler, Qt, QMimeData, QMetaObject,
    QGuiApplication, QDesktopServices, QIcon, QPalette, QColor, QFontDatabase, QFont,
    QQmlApplicationEngine, QQuickWindow, QQuickStyle, QApplication, QFileDialog,
    QTest, QPoint, QPointF, exec_app, delete_qobject, set_color_scheme, quick_style,
    failed_to_start, font_families, QT,
)
from templates import CATALOG, DEFAULT_TEMPLATE
from preset_store import PresetStore, normalize, checked, sections, fields, SIZES, BASE
from appearance import Appearance
from tutorial import Tutorial
from inference_draft import InferenceDraft
import offline_update_ui
import font_library

ROOT = Path(__file__).resolve().parent
DATA = data_directory(ROOT)
sys.path.insert(0, str(ROOT / 'core'))
import fontfallback
import preview_model
import import_drop

CONVERT_TARGETS = {
    'keep': {
        'label': '保持原格式',
        'mode': 'preserve',
        'brush': False,
        'hint': '不套模板，写成 .wenju。字体和字号按来源保留。剪贴板会同时另存一份同样版式的 Word。',
    },
    'wenju': {
        'label': '转成文矩',
        'mode': 'template',
        'brush': True,
        'hint': '按当前模板改字体和字号，写成 .wenju。剪贴板的文矩包仍保留来源字体，配套 Word 按模板刷。',
    },
    'docx': {
        'label': '转成 Word',
        'mode': 'preserve',
        'brush': False,
        'hint': '不套模板，导出 Word。字体和字号按来源保留。',
    },
    'styled': {
        'label': '按模板出 Word',
        'mode': 'template',
        'brush': True,
        'hint': '按当前模板刷成 Word。',
    },
    'merge': {
        'label': '合并为 Word',
        'mode': 'template',
        'brush': False,
        'hint': '按列表顺序把 .wenju 合成一份文矩，并按当前模板导出一份 Word。',
    },
}

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

class _ClipboardParse(QThread):
    progressed = Signal(int)
    parsed = Signal(object)
    failed = Signal(str)

    def __init__(self, html, rtf, plain, images):
        super().__init__()
        self._html = html
        self._rtf = rtf
        self._plain = plain
        self._images = images

    def run(self):
        try:
            clip, _wenju = wenju_modules()
            doc = clip.document_from_parts(self._html, self._rtf, self._plain, self._images, self.progressed.emit)
            self.parsed.emit(doc)
        except Exception as exc:
            try:
                clip, _wenju = wenju_modules()
                message = clip.clip_failure_text(exc)
            except Exception:
                message = '无法读取剪贴板'
            self.failed.emit(message or '无法读取剪贴板')


class _FontJob(QThread):
    result = Signal(bool, str)

    def __init__(self, action, value):
        super().__init__()
        self.action, self.value = action, value

    def run(self):
        root = font_library.storage(DATA)
        try:
            cancel = self.isInterruptionRequested
            if self.action == 'download':
                font_library.download(root, self.value, cancel)
                message = '已下载。可选用开源替代，也可以导出字体包。'
            elif self.action == 'import':
                font_library.import_pack(root, self.value, cancel)
                message = '离线字体包已导入。'
            elif self.action == 'system':
                for group in font_library.FILES:
                    if font_library.files_on_disk(root, group):
                        for filename in font_library.FILES[group][1]:
                            if cancel():
                                raise InterruptedError('已取消安装。')
                            if filename.endswith('.otf'):
                                path = root / group / filename
                                font_library.verify_local(path, group)
                                fontfallback.install_user_font(path)
                message = '已安装到当前用户。请重开 Word 或 WPS。'
            else:
                font_library.export_pack(root, self.value, cancel)
                message = '字体包已导出：' + str(self.value)
            self.result.emit(True, message)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
            self.result.emit(False, '字体操作未完成：' + str(exc))


class Bridge(QObject):
    changed = Signal()
    reportReady = Signal(str)
    inferenceReady = Signal(str, 'QVariantList')
    auditReady = Signal(str)
    offlineUpgradeReady = Signal('QVariantMap')
    offlineUpgradeResult = Signal(bool, str)
    markdownPreviewReady = Signal('QVariantList', str, bool)
    tutorialOutputReady = Signal(str)
    batchFinished = Signal(str)
    rulesChanged = Signal()
    libraryChanged = Signal()
    errorRaised = Signal(str)
    convertFinished = Signal(str)
    importProgressChanged = Signal()
    clipboardStarted = Signal()
    clipboardFinished = Signal(str)
    fontsChanged = Signal()
    fontTaskFinished = Signal(str)
    def __init__(self):
        super().__init__()
        self.rows = []
        self._font_job = None
        self._loaded_font_paths = {str(p) for p in fontfallback.application_font_files(ROOT, DATA)}
        self.offline_upgrade_job = None
        self.message = '准备就绪 · 文件仅在本机处理'
        self.running = False
        self.proc = None
        self.queue = []
        self.settings = {}
        try: self.settings = json.loads((DATA/'page.json').read_text('utf-8'))
        except (OSError, ValueError): pass
        self.store=PresetStore(DATA)
        self.rulesChanged.connect(self.fontsChanged.emit)
        self.template_ready=(DATA/'current.json').exists()
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
        self.convert_target='keep'
        self.convert_paste=''
        self._chain_docx=False
        self._kept_failed=[]
        self._kept_skipped=[]
        self._merge_surface='files'
        self._merge_skipped=[]
        self._base_blocks=[]
        self._base_note='拖入文件或读取剪贴板后，这里显示标题、段落、表格和图片。'
        self.preview_blocks=[]
        self.preview_note=self._base_note
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
        self._clip_thread = None
        self._clip_read = None
        self._clip_token = None
        self._preview_doc = None
        self._preview_charts = 0
        self._preview_limit = 40
        self._preview_folder = None
        self._more_scheduled = False
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
    def convertTarget(self): return self.convert_target
    @Property(str, notify=changed)
    def convertHint(self): return CONVERT_TARGETS[self.convert_target]['hint']
    @constant_property('QVariantList')
    def convertTargets(self):
        return [{'id': key, 'label': CONVERT_TARGETS[key]['label']} for key in ('keep', 'wenju', 'docx', 'styled', 'merge')]
    @Property('QVariantList', notify=changed)
    def previewBlocks(self): return self.preview_blocks
    @Property(str, notify=changed)
    def previewNote(self): return self.preview_note
    @Property(str, notify=changed)
    def status(self): return self.message
    @Property(bool, notify=changed)
    def busy(self): return self.running
    @Property(int, notify=changed)
    def overall(self): return self.overall_value
    @Property(int, notify=importProgressChanged)
    def importProgress(self): return self.import_progress
    @constant_property('QVariantMap')
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
    @Property(bool, notify=fontsChanged)
    def fontBusy(self):
        return self._font_job is not None

    def _font_fields(self):
        for group in ('字体', '页码', '公文', '红头', '封面'):
            block = self.store.rules.get(group, {})
            if group != '字体' and not block.get('启用', True):
                continue
            for key, val in block.items():
                if (key != '模式' and not key.startswith('_') and isinstance(val, str) and val.strip()
                        and (group == '字体' or key.endswith('字体'))):
                    yield block, key, val

    @Property('QVariantList', notify=fontsChanged)
    def templateFonts(self):
        names = sorted({name for _, _, name in self._font_fields()})
        root = font_library.storage(DATA)
        out = []
        for name in names:
            exact = fontfallback.exact_font(name)
            group = font_library.font_group(name)
            ready = bool(group and font_library.files_on_disk(root, group))
            out.append(dict(name=name, present=exact, group=group, ready=ready,
                            alternative=font_library.FAMILIES.get(group, '')))
        return out

    @Property(bool, notify=fontsChanged)
    def managedFonts(self):
        return any(font_library.files_on_disk(font_library.storage(DATA), g) for g in font_library.FILES)

    @constant_property(bool)
    def canInstallFontForUser(self):
        return fontfallback.per_user_os_fonts()

    def _start_font_job(self, action, value):
        if self._font_job is not None or self.running:
            return
        job = self._font_job = _FontJob(action, value)
        job.result.connect(self._font_result)
        job.finished.connect(self._font_finished)
        self.fontsChanged.emit()
        job.start()

    @Slot(bool, str)
    def _font_result(self, ok, message):
        for path in fontfallback.application_font_files(ROOT, DATA):
            if str(path) not in self._loaded_font_paths and QFontDatabase.addApplicationFont(str(path)) != -1:
                self._loaded_font_paths.add(str(path))
        fontfallback.reset_index()
        self.fontsChanged.emit()
        self.rulesChanged.emit()
        self.libraryChanged.emit()
        self.fontTaskFinished.emit(message)

    @Slot()
    def _font_finished(self):
        job, self._font_job = self._font_job, None
        if job: job.deleteLater()
        self.fontsChanged.emit()

    @Slot(str)
    def downloadTemplateFonts(self, group):
        groups = ({group} if group in font_library.FILES else
                  {row['group'] for row in self.templateFonts
                   if not row['present'] and row['group'] and not row['ready']})
        if groups:
            self._start_font_job('download', sorted(groups))
        else:
            self.fontTaskFinished.emit('当前模板没有可自动下载的缺失字体。可手动选择思源风格的黑体或宋体。')

    @Slot()
    def cancelFontTask(self):
        if self._font_job:
            self._font_job.requestInterruption()

    @Slot()
    def installManagedFonts(self):
        if self.canInstallFontForUser and self.managedFonts:
            self._start_font_job('system', None)

    @Slot()
    def importFontPack(self):
        path, _ = QFileDialog.getOpenFileName(None, '选择文矩字体包', '', '文矩字体包 (*.zip)')
        if path:
            self._start_font_job('import', path)

    @Slot()
    def exportFontPack(self):
        path, _ = QFileDialog.getSaveFileName(None, '导出文矩字体包', '文矩_离线字体包.zip', '文矩字体包 (*.zip)')
        if path:
            self._start_font_job('export', path if path.lower().endswith('.zip') else path + '.zip')

    @Slot()
    def applyManagedFonts(self):
        if self.fontBusy or self.running:
            return
        root = font_library.storage(DATA)
        updated = 0
        for block, key, name in self._font_fields():
            group = font_library.font_group(name)
            if not fontfallback.exact_font(name) and group and font_library.files_on_disk(root, group):
                block[key] = font_library.FAMILIES[group]
                updated += 1
        if updated:
            self.store.dirty = True
            self.rule_update()
        self.fontTaskFinished.emit(f'已替换 {updated} 项缺失的字体规则。需要重复使用时，请另存为模板。' if updated else '没有可替换的缺失字体。')

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
    @constant_property('QVariantList')
    def ruleSections(self):return sections(self.store.rules)
    @Property('QVariantList',notify=rulesChanged)
    def ruleFields(self):
        rows=fields(self.store.rules,self.section)
        for row in rows:
            if row['kind']=='choice' and row['editable'] and not row['path'].endswith('.字号'):
                row['values']=list(dict.fromkeys(row['values']+font_families()));row['labels']=row['values']
        return rows
    @Property('QStringList', notify=fontsChanged)
    def fontNames(self):return list(dict.fromkeys(['宋体','仿宋','黑体','楷体','Times New Roman','Arial']+font_families()))
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
        try:
            self.store.select(id)
            self.template_ready=True
            self.rulesChanged.emit();self.changed.emit()
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
        path,_=QFileDialog.getOpenFileName(None,'选择已排好版的样本文档','','文档 (*.docx *.dotx *.doc *.wps *.rtf)')
        if path:self.start_tool('infer',path)

    @Slot(str, result=str)
    def saveInferredTemplate(self, name):
        try:
            self.store.save_inferred(name, self.inferenceDraft.rules)
            self.message = '已保存到我的模板：' + name.strip()
            self.libraryChanged.emit()
            self.changed.emit()
            return ''
        except (OSError, ValueError) as exc:
            return str(exc)
    @Slot()
    def environment(self):
        if not self.running:return self.start_tool('environment')

    @Slot()
    def chooseOfflineUpgrade(self):
        if self.busy:
            return
        package, _ = QFileDialog.getOpenFileName(None, '选择文矩离线升级包', '', '离线升级包 (*.zip)')
        if package:
            self.loadOfflineUpgrade(package)

    @Slot(str)
    def loadOfflineUpgrade(self, package):
        if self.busy:
            return
        self.discardOfflineUpgrade()
        try:
            if ROOT.name != '文矩':
                raise ValueError('请在已解压的文矩便携版中使用离线升级。')
            self.offline_upgrade_job, summary = offline_update_ui.prepare(ROOT.parent, DATA, package)
            self.offlineUpgradeReady.emit(summary)
        except KeyError:
            self.offlineUpgradeResult.emit(False, '无法识别此 ZIP。请选择与当前系统对应的文矩离线升级包。')
        except offline_update_ui.PACKAGE_ERRORS as exc:
            self.offlineUpgradeResult.emit(False, str(exc))

    @Slot()
    def discardOfflineUpgrade(self):
        if self.offline_upgrade_job is not None:
            shutil.rmtree(self.offline_upgrade_job, ignore_errors=True)
            self.offline_upgrade_job = None

    @Slot(result=bool)
    def confirmOfflineUpgrade(self):
        if self.busy or self.offline_upgrade_job is None:
            return False
        try:
            offline_update_ui.launch_worker(ROOT.parent, DATA, self.offline_upgrade_job)
            self.offline_upgrade_job = None
            QTimer.singleShot(0, app.quit)
            return True
        except (OSError, ValueError, StopIteration) as exc:
            self.discardOfflineUpgrade()
            self.offlineUpgradeResult.emit(False, '无法启动离线升级。' + str(exc))
            return False

    def reportOfflineUpgrade(self):
        receipt = offline_update_ui.result_file(ROOT.parent, DATA)
        if not receipt.is_file():
            return
        try:
            message = json.loads(receipt.read_text(encoding='utf-8'))
            receipt.unlink()
            self.offlineUpgradeResult.emit(message['ok'], message['message'])
            job = receipt.parent / message['job']
            if job.parent == receipt.parent and job.name.startswith('任务-') and not job.is_symlink():
                QTimer.singleShot(1800, lambda: shutil.rmtree(job, ignore_errors=True))
        except (OSError, ValueError, KeyError):
            return

    @Slot()
    def auditFormatting(self):
        if self.running:
            return
        candidates = [row['path'] for row in self.rows if Path(row['path']).suffix.lower() == '.docx']
        if len(candidates) == 1:
            path = candidates[0]
        else:
            path, _ = QFileDialog.getOpenFileName(None, '选择要校核的原始文档', '', 'Word 文档 (*.docx)')
        if path:
            self.start_tool('audit', path)

    @Slot(int, result=bool)
    def startTutorialCase(self, index):
        if self.running:
            return False
        try:
            action, source = tutorial.copy_case(index, DATA/'教学练习')
            if action == 'markdown':
                return self.show_markdown_preview(str(source), practice=True)
            if action == 'audit':
                self.start_tool('audit', source, self.store.builtins[DEFAULT_TEMPLATE])
            else:
                self.start_tool('infer', source)
            return self.running
        except (OSError, ValueError) as exc:
            self.error(exc)
            return False

    @Slot()
    def formatTutorialMarkdown(self):
        if not self.running and getattr(self, 'tutorial_markdown_source', None):
            self.start_tool('practice-markdown', self.tutorial_markdown_source, self.store.builtins[DEFAULT_TEMPLATE])

    def start_tool(self,kind,source=None,template=None):
        self.task_kind=kind;self.running=True;self.queue=[]
        jobdir=self._scratch_dir()
        job={'action':kind,'rules':copy.deepcopy(self.store.rules),'templateName':self.selectedName}
        if template:
            job.update(rules=copy.deepcopy(template['rules']), templateName=template['name'])
        if kind == 'practice-markdown':
            self.practice_output_directory = Path(source).parent
            job['referenceDir'] = str(self.practice_output_directory)
        if source:
            if kind == 'audit' or Path(source).suffix.lower() in ('.docx', '.dotx'):
                job['source'] = str(source)
            else:
                try:
                    dst=jobdir/Path(source).name;shutil.copy2(source,dst);job['source']=str(dst)
                except OSError as exc:
                    self.running = False
                    self._drop_scratch()
                    self.error(exc)
                    return
        self.message={'infer':'正在识别样本文档…','audit':'正在按指定规则校核文档…',
                      'practice-markdown':'正在排版 Markdown 练习…'}.get(kind,'正在检测运行环境和字体…')
        self.launch(jobdir,job);self.changed.emit()

    def add(self, paths):
        imports=[p for p in paths if Path(p).suffix.lower() in ('.json','.zip') and Path(p).is_file()]
        if imports:self.import_paths(imports)
        known = {r['path'] for r in self.rows}
        for p in paths:
            p = str(Path(p).resolve())
            if p not in known and Path(p).suffix.lower() in import_drop.ORGANIZE_SUFFIXES and Path(p).is_file():
                self.rows.append(dict(path=p, name=Path(p).name, state='等待整理', output='', report='', percent=0))
                known.add(p)
        self.changed.emit()

    @Slot()
    def choose(self):
        paths, _ = QFileDialog.getOpenFileNames(None, '选择文档', '', '文档 (*.docx *.doc *.wps *.rtf *.wenju *.md *.markdown)')
        self.add(paths)

    def _set_import_progress(self, value):
        value = int(value)
        if value == self.import_progress:
            return
        self.import_progress = value
        self.importProgressChanged.emit()

    @Slot(bool)
    def importClipboard(self, brush):
        if self.running or self._importing:
            return
        clip, _wenju = wenju_modules()
        self._importing = True
        self.running = True
        if self._clip_read is None:
            self._clip_read = clip.ClipRead()
        self._clip_read.start()
        self.clipboard_brush = bool(brush)
        self.import_progress = 0
        self.importProgressChanged.emit()
        self.message = '正在从剪贴板读入…'
        self.changed.emit()
        self.clipboardStarted.emit()
        try:
            html, rtf, plain, images = clip.parts_from_mime(QGuiApplication.clipboard().mimeData())
        except Exception as exc:
            self.running = False
            self._importing = False
            self.error(exc)
            return
        worker = _ClipboardParse(html, rtf, plain, images)
        self._clip_token = object()
        worker._clip_token = self._clip_token
        worker.progressed.connect(self._set_import_progress)
        worker.parsed.connect(self._clip_ready)
        worker.failed.connect(self._clip_failed)
        worker.finished.connect(self._clip_thread_done)
        self._clip_thread = worker
        worker.start()

    def _clip_ready(self, doc):
        if self._clip_read is None or not self._clip_read.accept():
            return
        self.clipboard_doc = doc
        self.clipboard_docx = ''
        self.clipboard_wenju = ''
        self._set_preview_doc(doc)
        self._set_import_progress(100)
        self.running = False
        self._importing = False
        self.message = '已读入剪贴板，确认预览后再转换'
        self.clipboardFinished.emit('已读入 %d 个块。还没有写文件。确认预览后，点「开始转换」。' % len(doc.blocks))
        self.changed.emit()

    def _clip_failed(self, message):
        if self._clip_read is None or not self._clip_read.accept():
            return
        self.running = False
        self._importing = False
        self._set_import_progress(0)
        self.error(message or '无法读取剪贴板')

    def _stop_background(self):
        if self._font_job and self._font_job.isRunning():
            self._font_job.requestInterruption()
            self._font_job.wait()
        thread = self._clip_thread
        if thread is not None and thread.isRunning():
            thread.wait()
        if self.running and self.proc:
            self.proc.waitForFinished(30000)

    def _clip_thread_done(self):
        worker = self.sender()
        if worker is not None and getattr(worker, '_clip_token', None) is not self._clip_token:
            return
        if self._clip_read is None or not self._clip_read.thread_finished():
            return
        self.running = False
        self._importing = False
        self._set_import_progress(0)
        self.message = '已取消读入'
        self.changed.emit()

    @Slot(bool)
    def setClipboardBrush(self, brush):
        self.clipboard_brush = bool(brush)
        self.message = '按模板刷格式' if self.clipboard_brush else '保留原格式'
        self.changed.emit()

    @Slot('QVariantList')
    def dropFiles(self, urls):
        before=len(self.rows)
        self.add([QUrl(u).toLocalFile() for u in urls])
        if len(self.rows)>before and not self.template_ready:
            self.message=import_drop.TEMPLATE_PROMPT
            self.changed.emit()

    @Slot()
    def sample(self): self.add([ROOT/'core/样例/样例_整理前.docx'])

    def _write_row(self, index, dest):
        if not 0 <= index < len(self.rows): raise IndexError('没有这份文档')
        source = self.rows[index]['path']
        if Path(source).suffix.lower() in import_drop.MARKDOWN_SUFFIXES:
            import convert
            api = wenju_api()
            doc = convert.convert_path(source)
            if Path(dest).suffix.lower() == '.wenju':
                api.save(doc, dest)
            else:
                api.to_docx(doc, dest)
        else:
            wenju_api().convert_file(source_document(source), dest)
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
        self._merge_surface = 'files'
        self.task_kind = 'merge'
        self.running = True
        self.overall_value = 0
        jobdir = self._scratch_dir()
        sources, indexes = [], []
        import convert
        wenju_path, docx_path = convert.merge_targets(picked[0][1]['path'])
        for i, row in picked:
            dest = jobdir/('%02d_%s' % (len(sources), Path(row['path']).name))
            try: shutil.copy2(row['path'], dest)
            except OSError as exc:
                row['state'] = '失败：无法读取源文件'; row['error'] = str(exc); continue
            sources.append(str(dest)); indexes.append(i)
            row['percent'] = 0; row['output'] = str(docx_path); row['state'] = '等待合稿'
        if not sources:
            self.running = False; self._drop_scratch(); self.error('没有可读的 .wenju 文档'); return
        font = self.store.rules.get('字体', {}).get('正文', '仿宋')
        self.merge_indexes = indexes
        self.message = '正在合稿 %d 份文档' % len(sources)
        self.launch(jobdir, {'action':'merge', 'sources':sources, 'indexes':indexes,
            'wenju':str(wenju_path), 'docx':str(docx_path),
            'template':{'font':font, 'number':'多级数字'}})

    def addConvert(self, paths):
        if self.running: return
        added=''
        known={r.get('path') for r in self.convert_rows}
        for raw in paths:
            if not raw: continue
            path=Path(raw)
            if not path.is_file(): continue
            resolved=str(path.resolve())
            if resolved in known: continue
            self.convert_rows.append({'name':path.name,'path':resolved,'source':resolved,'percent':0,'state':'等待','message':'','output':''})
            known.add(resolved)
            added=resolved
        if added:
            self.preview_file(added)
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
        self.clipboard_doc=None
        self._preview_doc=None
        self._base_blocks=[]
        self._base_note='拖入文件或读取剪贴板后，这里显示标题、段落、表格和图片。'
        self._publish_preview()

    @Slot(str)
    def setConvertMode(self, mode):
        if mode in ('preserve','template'):
            self.convert_mode=mode
            self.changed.emit()

    @Slot(str)
    def setConvertTarget(self, target):
        spec=CONVERT_TARGETS.get(target)
        if not spec: return
        self.convert_target=target
        self.convert_mode=spec['mode']
        self.clipboard_brush=spec['brush']
        self.message=spec['hint']
        self.changed.emit()

    @Slot(str)
    def setConvertPaste(self, text):
        self.convert_paste=text or ''
        self._publish_preview()

    @Slot()
    def startConvert(self):
        if self.convert_target=='merge':
            self._merge_from_convert()
            return
        self._chain_docx=self.convert_target in ('docx','styled')
        self._begin_batch('convert')

    @Slot()
    def exportConvert(self):
        self._begin_batch('export')

    def _begin_batch(self, action, title=None):
        if self.running: return
        items=[]
        if action=='convert':
            text=(self.convert_paste or '').strip()
            if text: items.append({'name':'粘贴的内容','text':text,'source':'剪贴板'})
            clip_item=self._clipboard_item()
            if clip_item: items.insert(0, clip_item)
            for row in list(self.convert_rows):
                if row.get('path'): items.append({'name':row['name'],'path':row['path'],'source':row.get('source') or row['path']})
            self._convert_title=title or '转换完成'
        else:
            for row in list(self.convert_rows):
                output=row.get('output') or ''
                if output.lower().endswith('.wenju') and Path(output).is_file():
                    item={'name':row['name'],'path':output,'source':row.get('source') or ''}
                    if str(row.get('target') or '').lower().endswith('.docx'):
                        item['docx']=row['target']
                    items.append(item)
            self._convert_title=title or '导出完成'
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
        self._convert_dir=self._scratch_dir()
        import convert
        taken=set()
        when=datetime.datetime.now()
        placed=[]
        for item in items:
            if action=='export':
                if item.get('docx'):
                    final=Path(item['docx'])
                else:
                    source=Path(item['path'])
                    final=convert.place_output(source.parent, convert._safe_stem(source.stem), '.docx', taken)
                    item=dict(item, docx=str(final))
                target=str(final)
            elif item.get('path'):
                final_suffix='.docx' if self._chain_docx else '.wenju'
                final=convert.place_output(Path(item['path']).parent, convert._safe_stem(Path(item['path']).stem), final_suffix, taken)
                if self._chain_docx:
                    interim=convert.place_output(self._convert_dir, final.stem, '.wenju')
                    item=dict(item, output=str(interim))
                else:
                    item=dict(item, output=str(final))
                target=str(final)
            else:
                final_suffix='.docx' if self._chain_docx else '.wenju'
                final=convert.place_output(convert.clipboard_dir(), convert.clipboard_stem(when), final_suffix, taken)
                if self._chain_docx:
                    interim=convert.place_output(self._convert_dir, final.stem, '.wenju')
                    item=dict(item, output=str(interim))
                else:
                    item=dict(item, output=str(final))
                target=str(final)
            placed.append(item)
            self.convert_rows.append({'name':item['name'],'source':item.get('source') or '','path':item.get('path') or '','percent':0,'state':'等待','message':'','output':'','target':target})
        self.convert_queue=placed
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
            rows=self.convert_rows if self._merge_surface=='convert' else self.rows
            for key, value in (data.get('rows') or {}).items():
                index=int(key)
                if 0<=index<len(rows):
                    rows[index]['percent']=int(value)
                    if int(value)<100: rows[index]['state']='正在处理 %d%%' % int(value)
            if self._merge_surface=='convert': self.convert_overall=int(data.get('overall') or 0)
            else: self.overall_value=int(data.get('overall') or 0)
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
                if file.get('state')=='成功':
                    if self.task_kind=='convert': row['output']=file.get('output') or ''
                    else:
                        row['docx']=file.get('docx') or ''
                        row['output']=row['docx']
                planned=str(row.get('target') or '')
                if file.get('target') and not (self._chain_docx and planned.lower().endswith('.docx')):
                    row['target']=file['target']
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
        self.progress_timer.stop()
        if self._poll: self._poll.stop()
        self.convert_queue=[]
        while self.convert_pos < len(self.convert_rows):
            row=self.convert_rows[self.convert_pos]
            if row.get('state') in ('等待','正在转换','正在导出'):
                row['state']='未开始'
                self._convert_skipped.append(row.get('name') or '未命名')
            self.convert_pos += 1
        ready=any(str(row.get('output') or '').lower().endswith('.wenju') and Path(row.get('output') or '').is_file() for row in self.convert_rows)
        if self._chain_docx and not self.convert_stopped and ready:
            self._kept_failed=list(self._convert_failed)
            self._kept_skipped=list(self._convert_skipped)
            self._chain_docx=False
            self.running=False
            self._begin_batch('export', title='转换完成')
            return
        self._chain_docx=False
        self._convert_closed=True
        self.running=False
        self._drop_scratch()
        self.convert_overall=100
        failed=list(self._kept_failed)+list(self._convert_failed)
        skipped=list(self._kept_skipped)+list(self._convert_skipped)
        self._kept_failed=[]
        self._kept_skipped=[]
        title='转换已停止' if self.convert_stopped and self.task_kind=='convert' else ('导出已停止' if self.convert_stopped else self._convert_title)
        self.message=title
        core=str(ROOT/'core')
        if core not in sys.path: sys.path.insert(0, core)
        import convert
        self.convertFinished.emit(convert.summary({'succeeded':self._convert_succeeded,'failed':failed,'skipped':skipped}, title))
        self.changed.emit()

    def _display_font(self, name):
        if not name: return ''
        chosen, found = fontfallback.choose(str(name))
        return chosen if found else str(name)

    def _publish_preview(self):
        extra=preview_model.paste_blocks(self.convert_paste, self._display_font)
        self.preview_blocks=list(self._base_blocks)+extra
        self.preview_note=self._base_note
        self.changed.emit()

    def _clipboard_item(self):
        if self.clipboard_doc is None:
            return None
        _clip, wenju = wenju_modules()
        folder = DATA/'输出'
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        path = folder / ('剪贴板-%s.wenju' % stamp)
        wenju.save(self.clipboard_doc, path)
        return {'name':'剪贴板','path':str(path),'source':'剪贴板'}

    def _set_preview_doc(self, doc, charts=0):
        self._preview_doc = doc
        self._preview_charts = int(charts or 0)
        self._preview_limit = 40
        self._preview_folder = DATA/'预览'/uuid.uuid4().hex[:8]
        self._render_preview()

    def _render_preview(self):
        doc = self._preview_doc
        if doc is None:
            return
        try:
            self._preview_folder.mkdir(parents=True, exist_ok=True)
            blocks, note = preview_model.present(doc, self._preview_folder, self._display_font, self._preview_charts, self._preview_limit)
            warnings = (doc.source or {}).get('warnings') or []
            if warnings:
                note += '\n' + '\n'.join(warnings[:3])
                if len(warnings) > 3:
                    note += '\n另有 %d 条提示，完整内容见整理报告。' % (len(warnings) - 3)
            total = len(getattr(doc, 'blocks', None) or [])
            if total > len(blocks):
                note += ' 已显示前 %d 块，共 %d 块。继续往下滚动可再加载。' % (self._preview_limit, total)
            self._base_blocks = blocks
            self._base_note = note
        except Exception as exc:
            message = str(exc).splitlines()[-1][:180] or '无法预览'
            self._base_blocks = [preview_model.hold('还不能预览', message)]
            self._base_note = message
        self._publish_preview()

    @Slot()
    def morePreview(self):
        if self._more_scheduled or self._preview_doc is None:
            return
        total = len(self._preview_doc.blocks)
        if self._preview_limit >= total:
            return
        self._more_scheduled = True
        QTimer.singleShot(0, self._more_preview_now)

    def _more_preview_now(self):
        self._more_scheduled = False
        doc = self._preview_doc
        if doc is None:
            return
        total = len(doc.blocks)
        if self._preview_limit >= total:
            return
        self._preview_limit = min(total, self._preview_limit + 40)
        self._render_preview()

    def preview_file(self, path):
        try:
            core=str(ROOT/'core')
            if core not in sys.path: sys.path.insert(0, core)
            import convert
            doc=convert.convert_path(path, 'preserve')
            self._set_preview_doc(doc, preview_model.chart_count(path))
        except Exception as exc:
            message=str(exc).splitlines()[-1][:180] or '无法预览'
            self._base_blocks=[preview_model.hold('还不能预览', message)]
            self._base_note=message
            self._publish_preview()

    @Slot(int, result=bool)
    def previewMarkdown(self, index):
        if self.running or not 0 <= index < len(self.rows):
            return False
        source = self.rows[index]['path']
        if Path(source).suffix.lower() not in import_drop.MARKDOWN_SUFFIXES:
            return False
        return self.show_markdown_preview(source)

    def show_markdown_preview(self, source, practice=False):
        try:
            import convert
            doc = convert.convert_path(source)
            folder = DATA/'预览'/uuid.uuid4().hex[:8]
            folder.mkdir(parents=True, exist_ok=True)
            limit = 80
            blocks, note = preview_model.present(doc, folder, self._display_font, limit=limit)
            if len(doc.blocks) > limit:
                note += ' 已显示前 %d 块，共 %d 块。' % (limit, len(doc.blocks))
            warnings = (doc.source or {}).get('warnings') or []
            if warnings:
                note += '\n' + '\n'.join(warnings[:3])
                if len(warnings) > 3:
                    note += '\n另有 %d 条提示，完整内容见整理报告。' % (len(warnings) - 3)
            if practice:
                self.tutorial_markdown_source = source
                note = '练习模板：无敌公文体。' + note
            self.markdownPreviewReady.emit(blocks, note, practice)
            return True
        except Exception as exc:
            self.error(exc)
            return False

    def _merge_from_convert(self):
        if self.running: return
        picked=[]
        skipped=[]
        for row in self.convert_rows:
            path=str(row.get('path') or '')
            if path.lower().endswith('.wenju') and Path(path).is_file(): picked.append(row)
            else: skipped.append(row.get('name') or '未命名')
        if not picked:
            self.error('请先拖入一份或多份 .wenju，再合并为 Word。')
            return
        self._merge_surface='convert'
        self.task_kind='merge'
        self.running=True
        self.convert_overall=0
        self.convert_stopped=False
        jobdir=self._scratch_dir()
        sources=[]
        rows=[]
        import convert
        wenju_path, docx_path = convert.merge_targets(picked[0]['path'])
        for row in picked:
            dest=jobdir/('%02d_%s' % (len(sources), Path(row['path']).name))
            try: shutil.copy2(row['path'], dest)
            except OSError as exc:
                skipped.append((row.get('name') or dest.name)+'：'+str(exc))
                continue
            sources.append(str(dest))
            rows.append({'name':row.get('name') or dest.name,'path':str(dest),'percent':0,'state':'等待合稿','message':'','output':'','target':str(docx_path)})
        self._merge_skipped=skipped
        if not sources:
            self.running=False
            self._drop_scratch()
            self.error('没有可读的 .wenju 文档')
            return
        self.convert_rows=rows
        self.merge_indexes=list(range(len(sources)))
        font=self.store.rules.get('字体', {}).get('正文', '仿宋')
        self.message='正在合稿 %d 份文档' % len(sources)
        self.changed.emit()
        self.launch(jobdir, {'action':'merge','sources':sources,'indexes':self.merge_indexes,
            'wenju':str(wenju_path),'docx':str(docx_path),
            'template':{'font':font,'number':'多级数字'}})

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
        if self._importing and self._clip_read is not None and self._clip_read.running:
            self._clip_read.cancel()
            self.message = '正在取消读入…'
            self.changed.emit()
            return
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
        jobdir = self._scratch_dir()
        source = jobdir/row['name']
        try:shutil.copy2(row['path'], source)
        except OSError as exc:
            row['state']='失败：无法读取源文件';row['error']=str(exc);self._drop_scratch();self.changed.emit();QTimer.singleShot(0,self.next_file);return
        self.launch(jobdir,{'source':str(source), 'rules':self.batch_rules,
                            'referenceDir':str(Path(row['path']).parent)})
        self.changed.emit()

    def _scratch_dir(self):
        path=getattr(self,'_scratch',None)
        if path is None or not Path(path).is_dir():
            self._scratch=Path(tempfile.mkdtemp(prefix='wenju-'))
        return self._scratch

    def _drop_scratch(self):
        path=getattr(self,'_scratch',None)
        self._scratch=None
        if path and Path(path).is_dir():
            shutil.rmtree(path, ignore_errors=True)

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
        if self.task_kind in ('infer', 'audit', 'environment'):
            self._drop_scratch()

    def _finish_merge(self):
        self.progress_timer.stop(); self.running=False
        if self._poll: self._poll.stop()
        surface=self._merge_surface
        try:
            result=json.loads(self.result_file.read_text('utf-8'))
            if not result['ok']: raise RuntimeError(result['error'])
            if surface=='convert':
                for row in self.convert_rows:
                    row['output']=result['output']; row['docx']=result['output']; row['percent']=100; row['state']='成功'; row['message']=Path(result['output']).name
                self.convert_overall=100
                self.message='合并完成'
                text='合并完成，已导出一份 Word。\n'+result['output']
                if self._merge_skipped:
                    text+='\n未纳入 %d 个（不是可读的 .wenju）\n%s' % (len(self._merge_skipped), '\n'.join(self._merge_skipped))
                self.convertFinished.emit(text)
            else:
                for index in self.merge_indexes:
                    row=self.rows[index]
                    row['output']=result['output']; row['percent']=100; row['state']='已完成 · 点击打开'
                self.overall_value=100
                self.message='合稿完成'
                self.batchFinished.emit('合稿完成，已导出一份 Word。\n'+result['output'])
        except Exception as exc:
            self.error(exc)
        self._drop_scratch()
        self.proc.deleteLater(); self.changed.emit()

    def finished(self, code, _status):
        if self.task_kind=='merge':
            self._finish_merge(); return
        if self.task_kind in ('convert','export'):
            self._apply_convert_result(); return
        if self.task_kind!='process':
            self.progress_timer.stop()
            if self._poll: self._poll.stop()
            try:
                result=json.loads(self.result_file.read_text('utf-8'))
                if not result['ok']:raise ValueError(result['error'])
                if self.task_kind=='infer':
                    self.inferenceDraft.load(normalize(result['rules']))
                    self.inferenceReady.emit(result['name'], result['review'])
                    self.message = '识别完成，请复核后保存'
                elif self.task_kind=='audit':
                    self.auditReady.emit(result['reportText'])
                    self.message = '排版校核完成'
                elif self.task_kind=='practice-markdown':
                    import convert
                    produced = Path(result['output'])
                    output = convert.place_output(self.practice_output_directory, produced.stem, produced.suffix)
                    shutil.move(str(produced), str(output))
                    if result.get('report'):
                        report = Path(result['report'])
                        target = convert.place_output(output.parent, report.stem, report.suffix)
                        shutil.move(str(report), str(target))
                    self.tutorialOutputReady.emit(str(output))
                    self.message = 'Markdown 练习已生成 Word'
                else:
                    self.reportReady.emit(result['reportText'])
                    self.message = '环境检测完成'
            except Exception as exc:self.error(exc)
            self._drop_scratch()
            self.running=False;self.proc.deleteLater();self.changed.emit();return
        row = self.rows[self.current]
        try:
            result = json.loads(self.result_file.read_text('utf-8'))
            if not result['ok']: raise RuntimeError(result['error'])
            produced=Path(result['output'])
            import convert
            final=convert.place_output(Path(row['path']).parent, produced.stem, produced.suffix)
            if produced.resolve()!=final.resolve():
                shutil.move(str(produced), str(final))
            report=result.get('report') or ''
            if report and Path(report).is_file():
                report_path=Path(report)
                report_final=convert.place_output(final.parent, report_path.stem, report_path.suffix)
                if report_path.resolve()!=report_final.resolve():
                    shutil.move(str(report_path), str(report_final))
                report=str(report_final)
            row['output'] = str(final); row['report'] = report; row['percent'] = 100; row['state'] = '已完成 · 点击打开'
        except Exception as exc:
            row['state'] = '失败：' + str(exc)[:100];row['error']=str(exc)
        self._drop_scratch()
        self.proc.deleteLater()
        self.next_file()

    @Slot(str)
    def openTutorialOutput(self, path):
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

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
if sys.platform == 'win32':
    import windows_identity
    windows_identity.initialize()
app = QApplication(sys.argv)
upgrade_transaction = ROOT.parent / '.wenju-update-transaction'
if upgrade_transaction.is_dir() and not (upgrade_transaction / 'done').is_file():
    from qt_compat import load
    load()[2].QMessageBox.warning(None, '文矩', '离线升级尚未完成。请关闭此窗口，重新运行离线升级包。')
    sys.exit(1)
incoming = [str(Path(arg).resolve()) for arg in sys.argv[1:] if not arg.startswith('--') and Path(arg).is_file()]
session = None
if sys.platform == 'win32' and not any(arg.startswith(('--test-', '--capture', '--smoke')) for arg in sys.argv[1:]):
    from single_instance import LaunchSession
    from qt_compat import load
    QMessageBox = load()[2].QMessageBox
    session = LaunchSession(DATA)
    try:
        if not session.acquire(incoming):
            sys.exit(0)
    except RuntimeError as exc:
        QMessageBox.warning(None, '文矩', '无法连接已运行的文矩窗口：' + str(exc))
        sys.exit(1)
set_color_scheme(app, False)
palette=QPalette()
for role,color in [(QPalette.Window,'#f4f6f9'),(QPalette.WindowText,'#22344a'),(QPalette.Base,'#f9fafc'),(QPalette.Text,'#22344a'),(QPalette.Button,'#ffffff'),(QPalette.ButtonText,'#22344a'),(QPalette.Highlight,'#245a83'),(QPalette.HighlightedText,'#ffffff')]:
    palette.setColor(role,QColor(color))
app.setPalette(palette)
for font_file in fontfallback.application_font_files(ROOT, DATA):
    QFontDatabase.addApplicationFont(str(font_file))
fontfallback.reset_index()
app.setApplicationName('wenju')
app.setOrganizationName('WenJu')
app.setWindowIcon(brand_icon())
app.setFont(QFont('Microsoft YaHei UI',10))
appearance=Appearance(DATA,app)
bridge = Bridge()
bridge.inferenceDraft = InferenceDraft(bridge)
engine = QQmlApplicationEngine()
engine.rootContext().setContextProperty('bridge',bridge)
engine.rootContext().setContextProperty('inferenceDraft', bridge.inferenceDraft)
engine.rootContext().setContextProperty('appearance',appearance)
tutorial = Tutorial(ROOT, app)
engine.rootContext().setContextProperty('tutorial', tutorial)
app.aboutToQuit.connect(tutorial.stop)
app.aboutToQuit.connect(bridge.discardOfflineUpgrade)
QTimer.singleShot(300, bridge.reportOfflineUpgrade)
engine.rootContext().setContextProperty('startupAnimation',appearance.showIntro and os.environ.get('WENJU_LOW_POWER')!='1' and not any(a in sys.argv for a in ('--smoke','--capture','--capture-themes','--test-convert-ui','--test-clipboard','--capture-layout')))
engine.load(QUrl.fromLocalFile(str(ROOT/'Main.qml')))
if not engine.rootObjects(): sys.exit(1)
window = engine.rootObjects()[0]
if hasattr(window, 'setIcon'):
    window.setIcon(app.windowIcon())

identity = windows_identity.WindowIdentity(window, ROOT) if sys.platform == 'win32' else None
if identity:
    app.aboutToQuit.connect(identity.close)

def _window_drop(paths):
    page = window.property('page')
    if page == 5:
        bridge.addConvert(paths)
        return
    before = len(bridge.rows)
    bridge.add(paths)
    if len(bridge.rows) > before and not bridge.template_ready:
        bridge.message = import_drop.TEMPLATE_PROMPT
        bridge.changed.emit()

def _window_hover(hot):
    window.setProperty('dropHot', bool(hot))

import_drop.install_window_drop(window, _window_drop, _window_hover, import_drop.CONVERT_SUFFIXES)
if incoming:bridge.add(incoming)
def reuse_window(paths):
    if paths:
        _window_drop(paths)
    if window.visibility() == QQuickWindow.Minimized:
        window.showNormal()
    window.raise_()
    window.requestActivate()

if session:
    session.set_handler(reuse_window)
window.show()
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
    os.environ['WENJU_DOCUMENTS']=str(DATA)
    import traceback
    sample = DATA/'convert-sample.txt'
    held = {}
    def convert_ui():
        try:
            window.setProperty('page', 5)
            app.processEvents()
            bridge.setConvertTarget('wenju')
            assert bridge.convertTarget == 'wenju' and bridge.convertMode == 'template'
            bridge.setConvertTarget('keep')
            assert bridge.convertTarget == 'keep' and bridge.convertMode == 'preserve'
            panel = window.findChild(QObject, 'progressPanel')
            assert panel is not None, 'progress panel missing'
            assert panel.property('overall') == 0
            sample.write_text('界面转换\n', encoding='utf-8')
            rejected = sample.with_suffix('.xls')
            rejected.write_bytes(b'not-xlsx')
            bridge.addConvert([str(sample), str(rejected)])
            added = {row['name']: row for row in bridge.convertFiles}
            assert added['convert-sample.txt']['source'] == str(sample.resolve()), added
            assert added['convert-sample.txt']['output'] == ''
            assert added['convert-sample.xls']['source'] == str(rejected.resolve())
            assert added['convert-sample.xls']['output'] == ''
            bridge.setConvertPaste('粘贴一行')
            bridge.setConvertMode('template')
            assert bridge.convertMode == 'template'
            bridge.setConvertMode('preserve')
            assert bridge.convertMode == 'preserve'
            bridge.startConvert()
            assert bridge.busy
            started = {row['name']: row for row in bridge.convertFiles}
            assert started['粘贴的内容']['source'] == '剪贴板', started
            assert started['粘贴的内容']['output'] == ''
            assert started['convert-sample.txt']['source'] == str(sample.resolve())
            assert started['convert-sample.txt']['output'] == ''
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
            txt = files['convert-sample.txt']
            paste = files['粘贴的内容']
            bad = files['convert-sample.xls']
            assert txt['state'] == '成功', files
            assert txt['percent'] == 100
            assert txt['source'] == str(sample.resolve()), txt
            assert txt['output'].endswith('.wenju') and Path(txt['output']).is_file(), txt
            assert txt['message'] == '已写入', txt
            assert Path(txt['output']).name not in txt['message']
            assert paste['state'] == '成功'
            assert paste['source'] == '剪贴板', paste
            assert paste['output'].endswith('.wenju') and Path(paste['output']).is_file(), paste
            assert bad['state'] == '失败'
            assert bad['source'] == str(sample.with_suffix('.xls').resolve()), bad
            assert bad['output'] == ''
            assert '.xlsx' in bad['message']
            held['txt'] = txt['source']
            held['paste'] = paste['source']
            held['wenju'] = txt['output']
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
            files = {row['name']: row for row in bridge.convertFiles}
            txt = files['convert-sample.txt']
            paste = files['粘贴的内容']
            assert txt['source'] == held['txt'] == str(sample.resolve()), txt
            assert paste['source'] == held['paste'] == '剪贴板', paste
            assert not txt['source'].endswith('.wenju') and not txt['source'].endswith('.docx')
            assert txt['output'].endswith('.docx') and Path(txt['output']).is_file(), txt
            assert txt['output'] != held['wenju']
            assert paste['output'].endswith('.docx') and Path(paste['output']).is_file(), paste
            assert txt['message'] == '已写入' and Path(txt['output']).name not in txt['message']
            assert paste['message'] == '已写入'
            report = window.findChild(QObject, 'convertResult')
            text = report.property('text') or ''
            assert '导出完成' in text and '成功 2 个' in text, text
            bridge.clearConvert()
            bridge.setConvertPaste('链成 Word')
            bridge.setConvertTarget('docx')
            assert bridge.convertTarget == 'docx' and bridge.convertMode == 'preserve'
            bridge.startConvert()
            assert bridge.busy
            QTimer.singleShot(100, wait_chain)
        except Exception:
            traceback.print_exc(); app.exit(1)
    def wait_chain():
        try:
            if bridge.busy:
                QTimer.singleShot(100, wait_chain); return
            assert bridge.status == '转换完成', bridge.status
            made = [row for row in bridge.convertFiles if str(row.get('docx') or '').lower().endswith('.docx')]
            assert len(made) == 1 and made[0]['state'] == '成功' and made[0]['percent'] == 100, bridge.convertFiles
            assert made[0]['source'] == '剪贴板', made
            assert made[0]['output'].endswith('.docx') and Path(made[0]['output']).is_file(), made
            assert made[0]['output'] == made[0]['docx']
            print('PASS: convert page keeps source, writes wenju then docx to output, exports docx, and chains 转成 Word')
            app.quit()
        except Exception:
            traceback.print_exc(); app.exit(1)
    QTimer.singleShot(800, convert_ui)
    QTimer.singleShot(20000, lambda: app.exit(2))
app.aboutToQuit.connect(bridge._stop_background)
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
        assert bridge.inferenceDraft.rules['正文']['字号']==19
        assert bridge.inferenceDraft.rules['页码']['左侧字符']=='第 <& '
        assert bridge.store.rules['正文']['字号']==19
        assert not bridge.saveInferredTemplate('识别结果测试模板')
        assert bridge.store.find(bridge.selectedId)['name'] != '识别结果测试模板'
        bridge.environment()
        later(wait_environment)
    def wait_environment():
        if bridge.busy:return later(wait_environment)
        assert bridge.status=='环境检测完成',bridge.status
        print('PASS: QML numeric editing, page sync, save-as dialog, personal save, import/export slots, all form sections, worker snapshot, DOCX output, inference, environment')
        app.quit()
    later(begin_test,700)
    QTimer.singleShot(60000,lambda:app.exit(2))
if '--smoke-font-library' in sys.argv:
    def verify_font_center():
        try:
            center = window.findChild(QObject, 'fontCenter')
            assert center is not None and bridge.templateFonts
            assert QMetaObject.invokeMethod(center, 'open')
            assert center.property('visible')
            chapter = next(i for i, row in enumerate(tutorial.chapters) if row['id'] == 'font-library')
            tutorial.play(chapter)
            assert not tutorial.status, tutorial.status
            QTimer.singleShot(350, stop_font_lesson)
        except Exception:
            import traceback
            traceback.print_exc()
            app.exit(1)
    def stop_font_lesson():
        tutorial.stop()
        print('PASS: font center opens and font lesson audio starts and stops', flush=True)
        app.quit()
    QTimer.singleShot(800, verify_font_center)
    QTimer.singleShot(15000, lambda: app.exit(2))
if '--smoke-startup' in sys.argv:
    def verify_startup():
        if not window.isVisible():
            app.exit(1)
            return
        bridge.selectTemplate('unit')
        if bridge.selectedId != 'unit' or window.property('page') != 2:
            app.exit(2)
            return
        print('PASS: window shown and template selected', flush=True)
        app.quit()
    QTimer.singleShot(800, verify_startup)
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
        window.setProperty('page', 5)
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
        assert bridge.convertTarget=='keep'
        assert find_item('target_keep').property('checked') is True
        mime=QMimeData()
        mime.setData('text/html', (ROOT/'core/样例/clipboard/wps.html').read_bytes())
        mime.setText('plain should lose')
        QGuiApplication.clipboard().setMimeData(mime)
        import time
        out_dir=DATA/'输出'
        def snapshot():
            if not out_dir.exists():
                return set()
            return {path.relative_to(out_dir).as_posix() for path in out_dir.rglob('*') if path.is_file()}
        def wait_idle(limit):
            deadline=time.time()+limit
            while time.time()<deadline:
                app.processEvents()
                if not bridge.busy and not bridge._importing:
                    return
                time.sleep(0.02)
            raise AssertionError('still busy: %s' % bridge.status)
        def visible_text():
            found=[]
            todo=[window.contentItem()]
            while todo:
                item=todo.pop()
                value=item.property('text')
                if value:
                    found.append(str(value))
                todo += item.childItems()
            return '\n'.join(found)
        before=snapshot()
        click_item('importClipboard')
        wait_idle(20)
        assert bridge.importProgress==100, bridge.importProgress
        assert snapshot()==before, snapshot()-before
        assert not bridge.files, bridge.files
        done=find_item('clipDone')
        assert done is not None and done.property('visible') and done.property('title')=='已读入剪贴板'
        body=visible_text()
        assert '还没有写文件' in body, body
        QMetaObject.invokeMethod(done, 'close')
        app.processEvents()
        shown='\n'.join(str(block.get('text') or '') for block in bridge.previewBlocks)
        assert '通知标题' in shown and '正文第一段' in shown, shown
        assert any(block.get('kind')=='table' and '表头' in str(block.get('text') or '') for block in bridge.previewBlocks)
        assert any(block.get('kind')=='image' for block in bridge.previewBlocks), bridge.previewBlocks
        click_item('target_wenju')
        app.processEvents()
        assert bridge.convertTarget=='wenju'
        assert bridge.clipboard_brush is True
        assert snapshot()==before
        assert bridge.clipboard_doc.blocks[0]['runs'][0]['size_pt']==22
        shot=Path('/tmp/clipboard-import.png')
        assert window.grabWindow().save(str(shot)), shot
        click_item('startConvert')
        wait_idle(40)
        written=snapshot()-before
        wenju_names=[name for name in written if name.startswith('剪贴板-') and name.endswith('.wenju')]
        assert len(wenju_names)==1, written
        _clip, wenju=wenju_modules()
        kept=wenju.load(out_dir/wenju_names[0])
        heading=next(block for block in kept.blocks if block['type']=='heading')
        assert heading['runs'][0]['text']=='通知标题' and heading['runs'][0]['size_pt']==22
        mime2=QMimeData()
        mime2.setHtml('<html><body><p>第二份完全不同</p></body></html>')
        QGuiApplication.clipboard().setMimeData(mime2)
        held=snapshot()
        bridge.importClipboard(False)
        wait_idle(20)
        assert snapshot()==held
        shown2='\n'.join(str(block.get('text') or '') for block in bridge.previewBlocks)
        assert '第二份完全不同' in shown2, shown2
        QGuiApplication.clipboard().clear()
        app.processEvents()
        bridge.importClipboard(False)
        wait_idle(20)
        assert '没有可导入' in bridge.status, bridge.status
        assert snapshot()==held
        print('PASS: clipboard read previews without writing; convert writes the wenju; empty clipboard adds nothing')
        app.quit()
    QTimer.singleShot(800, guarded_clip(begin_clipboard))
    QTimer.singleShot(60000, lambda: app.exit(2))
if '--capture-layout' in sys.argv:
    import traceback
    shot_dir=Path(os.environ.get('WENJU_SHOT_DIR','/tmp/wenju-shots'))
    shot_dir.mkdir(parents=True, exist_ok=True)
    def capture_layout():
        try:
            def dismiss_ok():
                points=[]
                todo=[window.contentItem()]
                while todo:
                    item=todo.pop()
                    try:
                        name=str(item.metaObject().className())
                        if name.startswith('Button') and item.property('text') in ('OK','确定') and item.property('visible'):
                            points.append(item.mapToScene(QPointF(item.width()/2, item.height()/2)).toPoint())
                        todo += list(item.childItems())
                    except RuntimeError:
                        continue
                for point in points:
                    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
                    app.processEvents()
            def close_named(names):
                for name in names:
                    item=window.findChild(QObject, name)
                    if item is not None and item.property('visible'):
                        QMetaObject.invokeMethod(item, 'close')
                app.processEvents()
            dismiss_ok()
            window.setProperty('page', 0)
            bridge.sample()
            app.processEvents()
            assert window.grabWindow().save(str(shot_dir/'organize.png'))
            window.setWidth(1060)
            window.setHeight(740)
            app.processEvents()
            assert window.grabWindow().save(str(shot_dir/'organize-min.png'))
            window.setWidth(1220)
            window.setHeight(820)
            window.setProperty('page', 5)
            app.processEvents()
            mime=QMimeData()
            mime.setData('text/html', (ROOT/'core/样例/clipboard/wps.html').read_bytes())
            QGuiApplication.clipboard().setMimeData(mime)
            bridge.importClipboard(False)
            app.processEvents()
            close_named(['clipProgress','clipDone'])
            dismiss_ok()
            shown='\n'.join(str(block.get('text') or '') for block in bridge.previewBlocks)
            assert '通知标题' in shown and '表头' in shown, shown
            assert any(block.get('kind')=='image' for block in bridge.previewBlocks), bridge.previewBlocks
            assert window.grabWindow().save(str(shot_dir/'convert.png'))
            preview=window.findChild(QObject, 'previewList')
            assert preview is not None
            height=float(preview.property('height') or 0)
            content=float(preview.property('contentHeight') or 0)
            print('PREVIEW', height, content)
            if content>height+8:
                preview.setProperty('contentY', content-height)
                app.processEvents()
                assert window.grabWindow().save(str(shot_dir/'convert-detail.png'))
                preview.setProperty('contentY', 0)
                app.processEvents()
            window.setWidth(1060)
            window.setHeight(740)
            app.processEvents()
            assert window.grabWindow().save(str(shot_dir/'convert-min.png'))
            window.setWidth(1220)
            window.setHeight(820)
            app.processEvents()
            bridge.setConvertTarget('docx')
            app.processEvents()
            dismiss_ok()
            assert find_target()
            assert window.grabWindow().save(str(shot_dir/'convert-word.png'))
            log=DATA/'界面日志.txt'
            text=log.read_text(encoding='utf-8') if log.exists() else ''
            if 'Unable to assign' in text:
                print(text)
                raise RuntimeError('qml assigned undefined color')
            print('PASS: layout capture', shot_dir)
            app.quit()
        except Exception:
            traceback.print_exc(); app.exit(1)
    def find_target():
        todo=[window.contentItem()]
        while todo:
            item=todo.pop()
            if item.objectName()=='target_docx' and item.property('checked') is True:
                return True
            todo += item.childItems()
        raise AssertionError('转成 Word 没有处于选中')
    QTimer.singleShot(700, capture_layout)
    QTimer.singleShot(20000, lambda: app.exit(2))
try:
    exit_code=exec_app(app)
finally:
    if identity:
        identity.close()
    if session:
        session.close()
    if QT == '5':
        del engine
    else:
        delete_qobject(engine)
sys.exit(exit_code)
