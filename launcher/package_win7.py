"""Build the Windows 7 SP1 x64 portable zip. Does not touch the Win10/11 or Kylin layouts.

Downloads are cached under the directory given by WENJU_WIN7_CACHE (default: a
sibling of the repo is not used; pass the cache explicitly). Official pieces:

- Python 3.8.10 embeddable x64, the last CPython release that supports Windows 7
- PySide2 / shiboken2 5.15.2.1 (Qt 5.15.2), the last Qt LTS with Windows 7 support
- Universal CRT DLLs from KB2999226 are not full files (the MSU stores PA30
  deltas). This script instead builds api-ms-win-crt-* forwarders to the
  ucrtbase.dll shipped inside the PySide2 wheel, and copies that DLL next to
  pythonw.exe. vcruntime140 and msvcp140 come from the same wheel.
"""
from pathlib import Path
import hashlib, os, shutil, struct, subprocess, sys, textwrap, zipfile, zlib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'launcher'))
import pe_imports

CACHE = Path(os.environ.get('WENJU_WIN7_CACHE', '/tmp/win7build'))
PY_ZIP = CACHE / 'py.zip'
WHEEL_DIR = CACHE / 'wheels'
OUT = ROOT / 'dist'
STAGE = OUT / 'win7-stage' / '文矩'
ARCHIVE = OUT / 'WenJu_3.4.0_Windows7_x64_Portable.zip'

KEEP_PYD = {
    'QtCore.pyd', 'QtGui.pyd', 'QtWidgets.pyd', 'QtQml.pyd', 'QtQuick.pyd',
    'QtQuickControls2.pyd', 'QtNetwork.pyd', 'QtOpenGL.pyd', 'QtSvg.pyd',
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
APP_FILES = (
    'app.py', 'qt_compat.py', 'platform_support.py', 'template_library.py', 'appearance.py',
    'templates.py', 'preset_store.py', 'rule_schema.py', 'worker.py', 'Main.qml', 'Advanced.qml',
    'AppearancePage.qml', 'Opening.qml', 'TemplateHome.qml', '使用说明.txt', 'README.md',
    'requirements-windows.txt', '可选字体/README.txt',
    'ui/ProgressPanel.qml', 'ui/qmldir',
)
# Data exports of ucrtbase. Marking a code export DATA breaks the loader.
UCRT_DATA = {
    '_errno', '_doserrno', '__argc', '__argv', '__wargv', '_environ', '_wenviron', 'environ',
    '_pgmptr', '_wpgmptr', '_pctype', '_pwctype', '__p__commode', '__p__fmode', '_wctype',
    '_mbctype', '__initenv', '__winitenv',
}


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
    src = CACHE / 'ucrt-win7'
    if not (src / 'ucrtbase.dll').exists():
        raise SystemExit(
            'missing ' + str(src / 'ucrtbase.dll') +
            ' (extract api-ms-win-*.dll and ucrtbase.dll from the VS 2015 Update 3 vc_redist.x64.exe cabinet)'
        )
    for path in src.iterdir():
        if not path.is_file():
            continue
        name = path.name
        if name.startswith('api_ms_'):
            name = name.replace('_', '-')
        if name == 'ucrtbase.dll' or name.startswith('api-ms-win-'):
            shutil.copy2(path, runtime / name)
    if not (runtime / 'ucrtbase.dll').exists() or not (runtime / 'api-ms-win-crt-runtime-l1-1-0.dll').exists():
        raise SystemExit('downlevel Universal CRT copy is incomplete')


def build_forwarders(stage_runtime, symbols_by_dll):
    """Create api-ms-win-crt forwarders next to pythonw.exe and return their paths."""
    work = stage_runtime / '_forwarders'
    work.mkdir(exist_ok=True)
    built = []
    gcc = 'x86_64-w64-mingw32-gcc'
    for dll, names in sorted(symbols_by_dll.items()):
        lines = ['LIBRARY ' + dll, 'EXPORTS']
        for name in sorted(names):
            data = ' DATA' if name in UCRT_DATA else ''
            lines.append(f'  {name}=ucrtbase.{name}{data}')
        def_path = work / (dll + '.def')
        def_path.write_text('\n'.join(lines) + '\n', encoding='ascii')
        out = stage_runtime / dll
        c_path = work / 'empty.c'
        c_path.write_text('void wenju_crt_forwarder(void) {}\n', encoding='ascii')
        subprocess.check_call(
            [gcc, '-shared', '-o', str(out), str(c_path), str(def_path), '-Wl,--enable-stdcall-fixup'],
            stdout=subprocess.DEVNULL,
        )
        built.append(out)
    shutil.rmtree(work)
    return built


def needed_crt(root):
    wanted = {}
    for path in root.rglob('*'):
        if path.suffix.lower() not in ('.exe', '.dll', '.pyd'):
            continue
        parsed = pe_imports.pe_imports(path)
        if not parsed:
            continue
        for block in parsed:
            for dll, funcs in block:
                if dll.lower().startswith('api-ms-win-crt-'):
                    wanted.setdefault(dll.lower(), set()).update(n for n in funcs if not n.startswith('#'))
    return wanted


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
        if rel in PLUGIN_PREFIXES or path.name.lower() in FORCE_DLL:
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
    pth.write_text('python38.zip\n.\nLib\\site-packages\nimport site\n', encoding='ascii')
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
    ucrt = pyside / 'ucrtbase.dll'
    if not ucrt.exists():
        raise SystemExit('PySide2 wheel did not contain ucrtbase.dll')
    shutil.copy2(ucrt, runtime / 'ucrtbase.dll')
    for name in ('vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll', 'concrt140.dll', 'vcomp140.dll'):
        src = pyside / name
        if src.exists() and not (runtime / name).exists():
            shutil.copy2(src, runtime / name)
    # The ucrtbase.dll inside the PySide2 wheel is a Windows 10 build. It imports
    # API sets that do not exist on Windows 7. Replace it with the downlevel
    # Universal CRT from the VS 2015 Update 3 redistributable, and put every
    # api-ms-win-* forwarder in the pythonw.exe directory. On Windows 7 those
    # forwarders only resolve ucrtbase when they sit next to the process exe.
    for path in (runtime / 'Lib').rglob('*'):
        if path.name.lower() in ('ucrtbase.dll', 'vccorlib140.dll'):
            path.unlink()
    install_downlevel_ucrt(runtime)
    (runtime / 'qt5.txt').write_text('PySide2 5.15.2.1 / Python 3.8.10\n', encoding='ascii')
    return runtime


def prepare_icons():
    subprocess.check_call([sys.executable, str(ROOT / 'launcher' / 'make_icon.py')])
    subprocess.check_call([sys.executable, str(ROOT / 'launcher' / 'check_icons.py'), 'ico', str(ROOT / 'launcher' / 'WenJu.ico')])


def build_launcher(stage):
    gcc = 'x86_64-w64-mingw32-gcc'
    windres = 'x86_64-w64-mingw32-windres'
    rc = ROOT / 'launcher' / '_win7_launcher.rc'
    rc.write_text('1 ICON "WenJu.ico"\n1 24 "app.manifest"\n', encoding='ascii')
    res = ROOT / 'launcher' / '_win7_launcher.o'
    subprocess.check_call([windres, '-O', 'coff', '-i', str(rc), '-o', str(res)], cwd=ROOT / 'launcher')
    subprocess.check_call([
        gcc, '-municode', '-mwindows', '-O2', '-s', '-o', str(stage / '文矩.exe'),
        str(ROOT / 'launcher' / 'win7_launcher.c'), str(res),
    ])
    rc.unlink()
    res.unlink()
    subprocess.check_call([sys.executable, str(ROOT / 'launcher' / 'check_icons.py'), 'exe', str(stage / '文矩.exe')])


def write_note(stage):
    (stage / 'Windows7说明.txt').write_text(textwrap.dedent("""\
        文矩 3.4.0 Windows 7 便携包（64 位）

        适用系统：Windows 7 SP1 x64，并安装平台更新 KB2670838（提供 d3d11.dll；Qt 5.15 会直接加载它）。
        本包自带 Python 3.8.10、PySide2 5.15.2.1（Qt 5.15.2）、vcruntime140、msvcp140、
        以及 Windows 7 可用的 ucrtbase 和 api-ms-win-* 转发库。不需要单独安装 Python 或 VC++ 运行库。
        不需要 .NET。解压后双击外层的「打开文矩.exe」。它会建立桌面和开始菜单快捷方式。文件夹里的「文矩.exe」是同一个程序。也可以双击「启动文矩.bat」。

        这是 Win7 专用变体。Win10/11 便携包和麒麟包仍使用 PySide6，不能把两边的 runtime 混用。
        界面用 Qt Quick Controls 2 / Fusion。显卡驱动过旧时，用「文矩.exe --safe-render」改软件渲染。

        解压到当前用户可写的目录，保留 runtime、core 和程序文件。工作数据写在本目录。
        """), encoding='utf-8')
    bat = stage / '启动文矩.bat'
    bat.write_text('@echo off\r\ncd /d "%~dp0"\r\nset WENJU_QT=5\r\nstart "" "runtime\\pythonw.exe" "app.py" %*\r\n', encoding='ascii')


def assemble():
    prepare_icons()
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
    docs = STAGE / 'docs'
    docs.mkdir(exist_ok=True)
    for path in (ROOT / 'docs').glob('*.png'):
        shutil.copy2(path, docs / path.name)
    write_note(STAGE)
    icon_src = ROOT / 'launcher' / 'icons'
    if icon_src.exists():
        shutil.copytree(icon_src, STAGE / 'launcher' / 'icons')
    build_launcher(STAGE)
    shutil.copy2(STAGE / '文矩.exe', STAGE.parent / '打开文矩.exe')
    checked, problems = pe_imports.scan(STAGE)
    print(f'PE files: {checked}')
    if problems:
        for item in problems:
            print('\t'.join(item))
        raise SystemExit(f'Windows 7 import audit failed: {len(problems)}')
    print('Import audit: no Windows 7 violations.')
    class ChineseZipInfo(zipfile.ZipInfo):
        def _encodeFilenameFlags(self):
            return self.filename.encode('gbk'), self.flag_bits & ~0x800
    if ARCHIVE.exists():
        ARCHIVE.unlink()
    files = [p for p in STAGE.rglob('*') if p.is_file()]
    entry = STAGE.parent / '打开文矩.exe'
    with zipfile.ZipFile(ARCHIVE, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        info = ChineseZipInfo('打开文矩.exe')
        info.compress_type = zipfile.ZIP_DEFLATED
        raw = '打开文矩.exe'.encode('gbk')
        extra = struct.pack('<BI', 1, zlib.crc32(raw)) + '打开文矩.exe'.encode('utf-8')
        info.extra = struct.pack('<HH', 0x7075, len(extra)) + extra
        z.writestr(info, entry.read_bytes())
        for path in files:
            name = '文矩/' + path.relative_to(STAGE).as_posix()
            info = ChineseZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            raw = name.encode('gbk')
            extra = struct.pack('<BI', 1, zlib.crc32(raw)) + name.encode('utf-8')
            info.extra = struct.pack('<HH', 0x7075, len(extra)) + extra
            z.writestr(info, path.read_bytes())
    digest = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    sums = OUT / 'SHA256SUMS-win7.txt'
    sums.write_text(f'{digest}  {ARCHIVE.name}\n', encoding='ascii')
    print(ARCHIVE)
    print('SHA256:', digest)
    print('Bytes:', ARCHIVE.stat().st_size, 'Files:', len(files))


if __name__ == '__main__':
    assemble()
