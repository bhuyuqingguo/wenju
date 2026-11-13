"""Preferred font names stay in the document. choose() is only for painting.

Templates ask for 仿宋_GB2312 first. eastAsia and the exported docx keep that
name. A screen or preview substitutes the next installed face, and only then.
"""
import os

import fontembed

CHAINS = {
    "仿宋_GB2312": ["仿宋_GB2312", "FangSong_GB2312", "仿宋", "FangSong", "STFangsong", "华文仿宋"],
    "仿宋": ["仿宋", "FangSong", "STFangsong", "华文仿宋", "仿宋_GB2312", "FangSong_GB2312"],
    "楷体_GB2312": ["楷体_GB2312", "KaiTi_GB2312", "楷体", "KaiTi", "STKaiti", "华文楷体"],
    "楷体": ["楷体", "KaiTi", "STKaiti", "华文楷体", "楷体_GB2312", "KaiTi_GB2312"],
    "黑体": ["黑体", "SimHei", "STHeiti", "华文黑体", "Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC"],
    "宋体": ["宋体", "SimSun", "NSimSun", "STSong", "华文宋体", "Noto Serif CJK SC", "Noto Serif SC", "Source Han Serif SC"],
    "方正小标宋简体": ["方正小标宋简体", "FZXiaoBiaoSong-B05S", "方正小标宋", "华文中宋", "STZhongsong", "宋体", "SimSun"],
    "方正仿宋_GBK": ["方正仿宋_GBK", "FZFangSong-Z02", "仿宋_GB2312", "仿宋", "FangSong"],
    "方正楷体_GBK": ["方正楷体_GBK", "FZKai-Z03", "楷体_GB2312", "楷体", "KaiTi"],
    "方正黑体_GBK": ["方正黑体_GBK", "FZHei-B01", "黑体", "SimHei"],
    "微软雅黑": ["微软雅黑", "Microsoft YaHei", "Microsoft YaHei UI", "Noto Sans CJK SC", "Noto Sans SC"],
    "华文中宋": ["华文中宋", "STZhongsong", "宋体", "SimSun"],
}

_INDEX = None


def chain_for(name):
    if name in CHAINS:
        return CHAINS[name]
    for chain in CHAINS.values():
        if name in chain:
            return chain
    return [name]


def _index():
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    found = {}
    for folder in fontembed.font_dirs([]):
        for dirpath, _dirs, files in os.walk(folder):
            for filename in files:
                if not filename.lower().endswith((".ttf", ".ttc", ".otf")):
                    continue
                path = os.path.join(dirpath, filename)
                try:
                    faces = fontembed.font_faces(path)
                except Exception:
                    continue
                for _face, families, _sub, _bold, _italic in faces:
                    display = next((item for item in families if any("\u4e00" <= char <= "\u9fff" for char in item)), None)
                    if not display and families:
                        display = sorted(families)[0]
                    for family in families:
                        found.setdefault(family.casefold(), display or family)
    _INDEX = found
    return _INDEX


def reset_index():
    global _INDEX
    _INDEX = None


def choose(name):
    """Return (face, found) for display and preview. Does not rename stored runs."""
    if not name or not str(name).strip():
        return name, False
    requested = str(name).strip()
    index = _index()
    for candidate in chain_for(requested):
        hit = index.get(candidate.casefold())
        if hit:
            return hit, True
    return requested, False


def resolve(name):
    """Keep the requested family. Painting uses choose()."""
    return name
