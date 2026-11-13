"""Pick a font the machine actually has, and say so when it does not.

Templates name the preferred family (仿宋_GB2312, 方正小标宋简体, …).
The docx writer must store the family that was really selected, not a name
this computer will only substitute later. Chinese system fonts and Founder
faces are not redistributable; this module never ships those files.
"""
import os, sys, shutil, subprocess
from pathlib import Path

# Each list is the order to try. The first entry is the preferred family.
CHAINS = {
    '仿宋_GB2312': ['仿宋_GB2312', 'FangSong_GB2312', '仿宋', 'FangSong', 'STFangsong', '华文仿宋'],
    '仿宋': ['仿宋', 'FangSong', 'STFangsong', '华文仿宋', '仿宋_GB2312', 'FangSong_GB2312'],
    '楷体_GB2312': ['楷体_GB2312', 'KaiTi_GB2312', '楷体', 'KaiTi', 'STKaiti', '华文楷体'],
    '楷体': ['楷体', 'KaiTi', 'STKaiti', '华文楷体', '楷体_GB2312', 'KaiTi_GB2312'],
    '黑体': ['黑体', 'SimHei', 'STHeiti', '华文黑体', 'Noto Sans CJK SC', 'Noto Sans SC', 'Source Han Sans SC'],
    '宋体': ['宋体', 'SimSun', 'NSimSun', 'STSong', '华文宋体', 'Noto Serif CJK SC', 'Noto Serif SC', 'Source Han Serif SC'],
    '方正小标宋简体': ['方正小标宋简体', 'FZXiaoBiaoSong-B05S', '方正小标宋', '华文中宋', 'STZhongsong', '宋体', 'SimSun'],
    '方正仿宋_GBK': ['方正仿宋_GBK', 'FZFangSong-Z02', '仿宋_GB2312', '仿宋', 'FangSong'],
    '方正楷体_GBK': ['方正楷体_GBK', 'FZKai-Z03', '楷体_GB2312', '楷体', 'KaiTi'],
    '方正黑体_GBK': ['方正黑体_GBK', 'FZHei-B01', '黑体', 'SimHei'],
    '微软雅黑': ['微软雅黑', 'Microsoft YaHei', 'Microsoft YaHei UI', 'Noto Sans CJK SC', 'Noto Sans SC'],
    '华文中宋': ['华文中宋', 'STZhongsong', '宋体', 'SimSun'],
}

# What to tell the user. These families are not included in the program package.
LICENSE = {
    '仿宋_GB2312': '中易/微软随 Windows 或 Office 提供，不能单独分发。文件名常见为 simfang.ttf，英文家族名 FangSong_GB2312。',
    '仿宋': 'Windows 10 以后的补充字体，英文家族名 FangSong。授权随系统，不能抽出分发。麒麟上常见家族名也是「仿宋」或 FangSong。',
    '楷体_GB2312': '随中文 Windows/Office 提供，英文名 KaiTi_GB2312，不能单独分发。',
    '黑体': 'SimHei，随中文 Windows 提供，不能单独分发。',
    '宋体': 'SimSun，随中文 Windows 提供，不能单独分发。',
    '方正小标宋简体': '方正商用字体，英文名常见 FZXiaoBiaoSong-B05S。未获授权不能放进安装包。',
    '方正仿宋_GBK': '方正商用字体。未获授权不能放进安装包。',
    '方正楷体_GBK': '方正商用字体。未获授权不能放进安装包。',
    '方正黑体_GBK': '方正商用字体。未获授权不能放进安装包。',
}

_INDEX = None


def chain_for(name):
    if name in CHAINS:
        return CHAINS[name]
    for chain in CHAINS.values():
        if name in chain:
            return chain
    return [name]


def per_user_os_fonts():
    """Windows 10 and later can register a font for the current user. Windows 7 cannot."""
    if not sys.platform.startswith('win'):
        return True
    return sys.getwindowsversion().major >= 10


def optional_font_dirs(root):
    root = Path(root)
    return [root / '可选字体', root / '字体']


def _index():
    global _INDEX
    if _INDEX is None:
        import fontembed
        extra = []
        here = Path(__file__).resolve().parent.parent
        extra += [str(p) for p in optional_font_dirs(here)]
        _INDEX = {}
        for folder in fontembed.font_dirs(extra):
            for dirpath, _, files in os.walk(folder):
                for fn in files:
                    if not fn.lower().endswith(('.ttf', '.ttc', '.otf')):
                        continue
                    path = os.path.join(dirpath, fn)
                    try:
                        faces = fontembed.font_faces(path)
                    except Exception:
                        continue
                    for _fi, fams, _sub, _b, _i in faces:
                        display = next((n for n in fams if any('\u4e00' <= c <= '\u9fff' for c in n)), None)
                        if not display and fams:
                            display = sorted(fams)[0]
                        for fam in fams:
                            _INDEX.setdefault(fam.casefold(), display or fam)
    return _INDEX


def reset_index():
    global _INDEX
    _INDEX = None


def choose(name):
    """Return (written_name, found). written_name is what goes into the docx."""
    if not name or not str(name).strip():
        return name, False
    index = _index()
    for candidate in chain_for(str(name).strip()):
        hit = index.get(candidate.casefold())
        if hit:
            return hit, True
    return str(name).strip(), False


def collect(names):
    rows = []
    for name in names:
        if not name or not str(name).strip():
            continue
        chosen, found = choose(name)
        rows.append({'requested': str(name).strip(), 'chosen': chosen, 'found': found,
                     'note': '' if found else LICENSE.get(str(name).strip(), '请向字体权利人取得文件，或放到程序旁的「可选字体」文件夹。')})
    return rows


def rules_font_names(rules):
    found = set()
    fonts = rules.get('字体', {})
    for key, value in fonts.items():
        if key.startswith('_') or key == '模式' or not isinstance(value, str):
            continue
        found.add(value)
    page = rules.get('页码', {})
    for key in ('字体', '中文字体'):
        if isinstance(page.get(key), str):
            found.add(page[key])
    for group in ('公文', '红头', '封面'):
        block = rules.get(group, {})
        if isinstance(block, dict):
            for key, value in block.items():
                if key.endswith('字体') and isinstance(value, str):
                    found.add(value)
    return found


def guidance(rules):
    missing = [row for row in collect(rules_font_names(rules))
               if not row['found'] and (row['requested'] in CHAINS or any('\u4e00' <= c <= '\u9fff' for c in row['requested']))]
    if not missing:
        return ''
    lines = ['有模板字体在这台电脑上没有找到。文档会写上首选字体名，对方电脑若也没有，仍会被替换。']
    for row in missing:
        lines.append(row['requested'] + '：' + row['note'])
    lines.append('可以把自有的 .ttf/.otf/.ttc 放进程序旁边的「可选字体」文件夹，然后重新打开文矩。')
    if sys.platform.startswith('win') and not per_user_os_fonts():
        lines.append('Windows 7 不能给当前用户注册字体。文矩会在打开时用这些文件画界面，并在嵌入字体时使用它们。')
    elif sys.platform.startswith('win'):
        lines.append('Windows 10 及以上可以把字体装到当前用户（不需要管理员）。')
    else:
        lines.append('Linux 会把字体复制到 ~/.local/share/fonts 并刷新字体缓存，不需要 root。')
    return '\n'.join(lines)


def install_user_font(src):
    """Copy a font the user already has. Returns a short status string."""
    src = Path(src)
    if src.suffix.lower() not in ('.ttf', '.otf', '.ttc'):
        raise ValueError('只接受 ttf、otf、ttc')
    if sys.platform.startswith('win') and per_user_os_fonts():
        dest_dir = Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft' / 'Windows' / 'Fonts'
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        shutil.copy2(src, dest)
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows NT\CurrentVersion\Fonts') as key:
            winreg.SetValueEx(key, src.stem + ' (TrueType)', 0, winreg.REG_SZ, str(dest))
        reset_index()
        return '已安装到当前用户字体目录'
    if sys.platform.startswith('win'):
        dest_dir = Path(__file__).resolve().parent.parent / '可选字体'
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest_dir / src.name)
        reset_index()
        return 'Windows 7 已复制到「可选字体」。界面会加载该文件；系统字体列表不会出现它。'
    dest_dir = Path.home() / '.local' / 'share' / 'fonts' / 'wenju'
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest_dir / src.name)
    if shutil.which('fc-cache'):
        subprocess.run(['fc-cache', '-f', str(dest_dir)], check=False)
    reset_index()
    return '已安装到 ~/.local/share/fonts/wenju'


def resolve(name):
    """Name stored in the docx. A missing face is substituted only when drawing."""
    if not name:
        return name
    return str(name)


def application_font_files(root):
    files = []
    for folder in optional_font_dirs(root):
        if not folder.is_dir():
            continue
        for path in folder.rglob('*'):
            if path.suffix.lower() in ('.ttf', '.otf', '.ttc') and path.is_file():
                files.append(path)
    return files
