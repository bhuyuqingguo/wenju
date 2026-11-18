"""Build the Windows 7 SP1 x64 portable zip. Does not touch the Win10/11 or Kylin layouts.

Set WENJU_WIN7_CACHE to a directory with py38/ (extracted Python 3.8.10
embeddable x64) and wheels/ (PySide2 and shiboken2 5.15.2.1, win_amd64).
Build on Windows with Visual Studio C++ Build Tools and Windows SDK.
The SDK's application-local x64 UCRT is bundled beside pythonw.exe.
"""
from pathlib import Path
import hashlib, os, shutil, struct, subprocess, sys, tempfile, textwrap, zipfile, zlib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'launcher'))
import pe_imports
import app_files

CACHE = Path(os.environ.get('WENJU_WIN7_CACHE', Path.home() / 'AppData/Local/WenjuBuild/win7')).resolve()
WHEEL_DIR = CACHE / 'wheels'
OUT = ROOT / 'dist'
STAGE = OUT / 'win7-stage' / '文矩'
VERSION = '3.4.2'
ARCHIVE = OUT / f'文矩_{VERSION}_Windows7_x64_免安装_测试版.zip'

KEEP_PYD = {
    'QtCore.pyd', 'QtGui.pyd', 'QtWidgets.pyd', 'QtQml.pyd', 'QtQuick.pyd',
    'QtQuickControls2.pyd', 'QtNetwork.pyd', 'QtOpenGL.pyd', 'QtSvg.pyd', 'QtTest.pyd',
}
FORCE_DLL = {
    'libegl.dll', 'libglesv2.dll', 'opengl32sw.dll', 'd3dcompiler_47.dll', 'ucrtbase.dll',
}
KEEP_QML = {'QtQml', 'QtQuick', 'QtQuick.2'}
PLUGIN_PREFIXES = (
    'plugins/platforms/qwindows.dll',
    'plugins/platforms/qminimal.dll',
    'plugins/imageformats/qgif.dll',
    'plugins/imageformats/qico.dll',
    'plugins/imageformats/qjpeg.dll',
    'plugins/imageformats/qsvg.dll',
    'plugins/imageformats/qtiff.dll',
    'plugins/imageformats/qwebp.dll',
    'plugins/iconengines/qsvgicon.dll',
)
APP_FILES = app_files.names(ROOT)
def rewrite_qml(name, text):
    text = text.replace('import QtQuick.Controls\n', 'import QtQuick.Controls 2.15\n')
    text = text.replace('import QtQuick.Layouts\n', 'import QtQuick.Layouts 1.15\n')
    text = text.replace('import QtQuick\n', 'import QtQuick 2.15\n')
    text = text.replace('contentWidth:availableWidth', 'contentWidth:width')
    text = text.replace('.toLowerCase().includes(query)', '.toLowerCase().indexOf(query)>=0')
    text = text.replace('let ', 'var ')
    old = 'property var categories: ["全部"].concat([...new Set(bridge.templates.map(t=>t.category))])'
    new = (
        'function uniqueCategories(){var seen={};var out=["全部"];var items=bridge.templates;'
        'for(var i=0;i<items.length;++i){var c=items[i].category;if(c&&!seen[c]){seen[c]=true;out.push(c);}}'
        'return out;}\n    property var categories: uniqueCategories()'
    )
    if old not in text and name == 'TemplateHome.qml':
        raise SystemExit('TemplateHome.qml category line changed; update the Win7 rewrite')
    return text.replace(old, new)


def find_wheel(prefix):
    matches = sorted(WHEEL_DIR.glob(prefix + '*.whl'))
    if not matches:
        raise SystemExit('missing wheel ' + prefix + ' in ' + str(WHEEL_DIR))
    return matches[-1]


def extract_wheel(wheel, dest):
    with zipfile.ZipFile(wheel) as z:
        z.extractall(dest)


def install_downlevel_ucrt(runtime):
    default = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)'))
    default /= 'Windows Kits/10/Redist/ucrt/DLLs/x64'
    src = Path(os.environ.get('WENJU_WIN7_UCRT', default))
    if not (src / 'ucrtbase.dll').is_file():
        raise SystemExit(f'Windows SDK application-local x64 UCRT not found: {src}')
    for path in src.glob('*.dll'):
        if path.name == 'ucrtbase.dll' or path.name.startswith('api-ms-win-'):
            shutil.copy2(path, runtime / path.name)
    if not (runtime / 'api-ms-win-crt-runtime-l1-1-0.dll').is_file():
        raise SystemExit('Application-local Universal CRT copy is incomplete')


def closure(pyside):
    by_name = {}
    for path in pyside.rglob('*'):
        if path.suffix.lower() in ('.dll', '.pyd'):
            by_name.setdefault(path.name.lower(), path)
    keep = set()
    queue = []
    for name in KEEP_PYD:
        queue.append(by_name[name.lower()])
    for path in pyside.rglob('*'):
        rel = path.relative_to(pyside).as_posix().lower()
        parts = path.relative_to(pyside).parts
        qml_plugin = (
            len(parts) > 2 and parts[0] == 'qml' and parts[1] in KEEP_QML
            and path.suffix.lower() == '.dll'
        )
        if rel in PLUGIN_PREFIXES or path.name.lower() in FORCE_DLL or qml_plugin:
            queue.append(path)
    shib = pyside.parent / 'shiboken2'
    for path in shib.rglob('*'):
        if path.suffix.lower() in ('.dll', '.pyd'):
            by_name.setdefault(path.name.lower(), path)
            queue.append(path)
    while queue:
        path = queue.pop()
        if path in keep:
            continue
        keep.add(path)
        parsed = pe_imports.pe_imports(path)
        if not parsed:
            continue
        for block in parsed:
            for dll, funcs in block:
                dep = by_name.get(dll.lower())
                if dep is not None and dep not in keep:
                    queue.append(dep)
    return keep


def copy_runtime(stage):
    runtime = stage / 'runtime'
    if runtime.exists():
        shutil.rmtree(runtime)
    shutil.copytree(CACHE / 'py38', runtime)
    pth = runtime / 'python38._pth'
    pth.write_text('python38.zip\n.\n..\nLib\\site-packages\nimport site\n', encoding='ascii')
    (runtime / 'qt.conf').write_text(
        '[Paths]\nPrefix=Lib/site-packages/PySide2\nPlugins=plugins\nQml2Imports=qml\n',
        encoding='ascii',
    )
    site = runtime / 'Lib' / 'site-packages'
    site.mkdir(parents=True)
    extract_wheel(find_wheel('PySide2-'), site)
    extract_wheel(find_wheel('shiboken2-'), site)
    pyside = site / 'PySide2'
    keep = closure(pyside)
    for path in list(pyside.rglob('*')):
        if path.suffix.lower() in ('.dll', '.pyd') and path not in keep:
            path.unlink()
    qml = pyside / 'qml'
    if qml.exists():
        for child in qml.iterdir():
            if child.is_dir() and child.name not in KEEP_QML:
                shutil.rmtree(child)
    # Drop designer plugins, webengine leftovers, static libs and type stubs.
    for path in list(pyside.rglob('*')):
        if path.suffix.lower() in ('.lib', '.pyi', '.qmltypes') or path.name.endswith('.pdb'):
            path.unlink()
    plugins = pyside / 'plugins'
    if plugins.exists():
        for child in list(plugins.iterdir()):
            rel_keep = False
            for prefix in PLUGIN_PREFIXES:
                if prefix.startswith('plugins/' + child.name + '/'):
                    rel_keep = True
            if child.is_dir() and not rel_keep:
                shutil.rmtree(child)
            elif child.is_dir():
                allowed = {Path(p).name.lower() for p in PLUGIN_PREFIXES if p.split('/')[1] == child.name}
                for item in child.iterdir():
                    if item.name.lower() not in allowed:
                        if item.is_dir():
                            shutil.rmtree(item)
                        else:
                            item.unlink()
    init = (pyside / '__init__.py').read_text(encoding='utf-8')
    old = (
        "    if sys.platform == 'win32' and sys.version_info[0] == 3 and sys.version_info[1] >= 8:\n"
        "        for dir in _additional_dll_directories(pyside_package_dir):\n"
        "            os.add_dll_directory(dir)\n"
    )
    new = (
        "    if sys.platform == 'win32' and sys.version_info[0] == 3 and sys.version_info[1] >= 8 and hasattr(os, 'add_dll_directory'):\n"
        "        for dir in _additional_dll_directories(pyside_package_dir):\n"
        "            try:\n"
        "                os.add_dll_directory(dir)\n"
        "            except (OSError, AttributeError, NotImplementedError):\n"
        "                pass\n"
    )
    if old not in init:
        raise SystemExit('PySide2 __init__.py DLL search block changed')
    (pyside / '__init__.py').write_text(init.replace(old, new, 1), encoding='utf-8')
    shib = pyside.parent / 'shiboken2'
    for dll in shib.glob('*.dll'):
        shutil.copy2(dll, pyside / dll.name)
    for name in ('vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll', 'concrt140.dll', 'vcomp140.dll'):
        src = pyside / name
        if src.exists() and not (runtime / name).exists():
            shutil.copy2(src, runtime / name)
    # The copy of ucrtbase.dll shipped inside the wheel targets Windows 10.
    # Use the SDK's app-local copy and forwarders beside pythonw.exe instead.
    for path in (runtime / 'Lib').rglob('*'):
        if path.name.lower() in ('ucrtbase.dll', 'vccorlib140.dll'):
            path.unlink()
    install_downlevel_ucrt(runtime)
    (runtime / 'qt5.txt').write_text('PySide2 5.15.2.1 / Python 3.8.10\n', encoding='ascii')
    return runtime


def prepare_icons():
    subprocess.check_call([sys.executable, str(ROOT / 'launcher' / 'check_icons.py'), 'ico', str(ROOT / 'launcher' / 'WenJu.ico')])


def build_launcher(stage):
    exe = stage / '文矩.exe'
    subprocess.check_call([
        'pwsh', '-NoProfile', '-File', str(ROOT / 'launcher' / 'build.ps1'),
        '-Win7', '-OutputPath', str(exe),
    ])
    pe_imports.require_native_launcher(exe)
    subprocess.check_call([sys.executable, str(ROOT / 'launcher' / 'check_icons.py'), 'exe', str(exe)])


def write_note(stage):
    (stage / 'Windows7说明.txt').write_text(textwrap.dedent(f"""\
        文矩 {VERSION} Windows 7 x64 免安装测试版

        适用系统：Windows 7 SP1 64 位，且已通过 KB2533623 或后续系统更新提供安全 DLL 加载接口。
        如果启动报缺少系统组件，请记下完整提示或截图；应用不会安装系统补丁。
        已附带 Python 3.8.10、Qt 5.15 和 VC++／通用 C 运行库。无需安装 .NET，也无需管理员权限运行。
        请完整解压到固定、可写的目录，双击「文矩.exe」，保留旁边的 runtime、core 和 ui 等文件。
        默认启用软件渲染和低动效模式，兼顾老显卡与驱动。不要与 Win10/11 版混用 runtime。
        首次启动后可右键文矩任务栏图标固定。如曾固定旧入口，请手动取消旧项后重新固定。
        移动便携目录后，旧固定项仍指向原位置，请从新目录打开并重新固定。
        """), encoding='utf-8-sig')


def assemble():
    prepare_icons()
    if STAGE.resolve() != ROOT / 'dist' / 'win7-stage' / '文矩':
        raise SystemExit('Unexpected Win7 staging path')
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    copy_runtime(STAGE)
    for name in APP_FILES:
        src = ROOT / name
        text = src.read_text(encoding='utf-8')
        if name.endswith('.qml'):
            text = rewrite_qml(name, text)
        dest = STAGE / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding='utf-8')
    core_src = ROOT / 'core'
    for path in core_src.rglob('*'):
        if not path.is_file():
            continue
        if '__pycache__' in path.parts or path.suffix == '.pyc':
            continue
        if path.name.endswith('_已整理.docx') or path.name.endswith('_整理报告.txt'):
            continue
        dest = STAGE / path.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    app_files.require_tree(ROOT, STAGE)
    docs = STAGE / 'docs'
    docs.mkdir(exist_ok=True)
    for path in (ROOT / 'docs').glob('*.png'):
        shutil.copy2(path, docs / path.name)
    write_note(STAGE)
    icon_src = ROOT / 'launcher' / 'icons'
    if icon_src.exists():
        shutil.copytree(icon_src, STAGE / 'launcher' / 'icons')
    build_launcher(STAGE)
    checked, problems = pe_imports.scan(STAGE)
    print(f'PE files: {checked}')
    if problems:
        for item in problems:
            print('\t'.join(item))
        raise SystemExit(f'Windows 7 import audit failed: {len(problems)}')
    print('Import audit: no Windows 7 violations.')
    with tempfile.TemporaryDirectory(prefix='WenJu-Win7-') as data:
        env = dict(os.environ, WENJU_QT='5', WENJU_DATA_DIR=data)
        subprocess.run([str(STAGE / 'runtime' / 'python.exe'), '-X', 'faulthandler', '-B',
                        str(STAGE / 'app.py'), '--safe-render', '--smoke-startup'],
                       cwd=STAGE, env=env, timeout=25, check=True)
    class ChineseZipInfo(zipfile.ZipInfo):
        def _encodeFilenameFlags(self):
            return self.filename.encode('gbk'), self.flag_bits & ~0x800
    if ARCHIVE.exists():
        ARCHIVE.unlink()
    files = [p for p in STAGE.rglob('*') if p.is_file()]
    with zipfile.ZipFile(ARCHIVE, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in files:
            name = '文矩/' + path.relative_to(STAGE).as_posix()
            info = ChineseZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            raw = name.encode('gbk')
            extra = struct.pack('<BI', 1, zlib.crc32(raw)) + name.encode('utf-8')
            info.extra = struct.pack('<HH', 0x7075, len(extra)) + extra
            z.writestr(info, path.read_bytes())
    with zipfile.ZipFile(ARCHIVE, metadata_encoding='gbk') as z:
        if '文矩/文矩.exe' not in z.namelist() or z.testzip() is not None:
            raise SystemExit('Windows 7 zip validation failed')
    digest = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    sums = OUT / 'SHA256SUMS-win7.txt'
    sums.write_text(f'{digest}  {ARCHIVE.name}\n', encoding='utf-8')
    print(ARCHIVE)
    print('SHA256:', digest)
    print('Bytes:', ARCHIVE.stat().st_size, 'Files:', len(files))


if __name__ == '__main__':
    assemble()
