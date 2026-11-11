# -*- coding: utf-8 -*-
"""
paths.py —— 路径解析（普通用户权限即可运行）
・工具目录可写：一切数据（rules.json、预设、输出、日志）就放在工具目录（便携模式）。
・工具目录只读（装在 Program Files、只读网络共享、受策略保护的目录）：数据自动放到用户目录
  Windows：%LOCALAPPDATA%\\WenJu　　Linux：~/.local/share/WenJu
  首次使用时把 rules.json 与内置预设复制过去；之后一律读写用户目录，不再触碰工具目录，因此不需要管理员权限。
・目录与文件同时接受中文名与英文名（首次改名失败时也能正常工作）。
"""
import os, sys, shutil

HERE = os.path.dirname(os.path.abspath(__file__))

NAMES = {  # 中文名: 英文名
    "预设": "presets", "字体": "fonts", "样例": "samples", "辅助脚本": "helpers", "输出": "output", "素材": "assets",
    "文矩_图标.svg": "logo.svg", "文矩_图标_512.png": "logo_512.png", "文矩_标志.png": "logo_full.png",
    "doc转docx.vbs": "doc2docx.vbs", "刷新域.vbs": "update_fields.vbs",
    "样例_整理前.docx": "sample_before.docx", "模板_经工具处理.docx": "template_processed.docx",
    "单位模板（默认）.json": "preset_default.json", "轻整理（保留原字体，仅题注与版式）.json": "preset_light.json",
}

def _writable(d):
    try:
        os.makedirs(d, exist_ok=True)
        t = os.path.join(d, ".hl_write_test_%d" % os.getpid())
        with open(t, "w") as f: f.write("1")
        os.remove(t)
        return True
    except Exception:
        return False

def res(*parts):
    """在工具目录下按中文名/英文名解析路径，返回第一个存在的；都不存在则返回中文名路径。"""
    cands = [[]]
    for p in parts:
        alt = NAMES.get(p)
        cands = [c + [p] for c in cands] + ([c + [alt] for c in cands] if alt else [])
    for c in cands:
        fp = os.path.join(HERE, *c)
        if os.path.exists(fp): return fp
    return os.path.join(HERE, *parts)

PORTABLE = _writable(HERE)
if PORTABLE:
    DATA = HERE
else:
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    DATA = os.path.join(base, "WenJu")
    if not _writable(DATA):
        import tempfile
        DATA = os.path.join(tempfile.gettempdir(), "WenJu"); os.makedirs(DATA, exist_ok=True)

def data(*parts):
    return os.path.join(DATA, *parts)

def _seed():
    """只读安装时，把规则与内置预设复制到用户数据目录（只在缺失时复制）。"""
    if PORTABLE: return
    for d in ("预设", "输出", "字体"):
        os.makedirs(data(d), exist_ok=True)
    r = data("rules.json")
    if not os.path.exists(r) and os.path.exists(os.path.join(HERE, "rules.json")):
        shutil.copy(os.path.join(HERE, "rules.json"), r)
    src = res("预设")
    if os.path.isdir(src):
        for f in os.listdir(src):
            if f.lower().endswith(".json") and not os.path.exists(data("预设", f)):
                try: shutil.copy(os.path.join(src, f), data("预设", f))
                except Exception: pass
_seed()

def rules_path():
    return data("rules.json") if not PORTABLE else os.path.join(HERE, "rules.json")

def preset_dir():
    if PORTABLE:
        p = res("预设"); os.makedirs(p, exist_ok=True); return p
    return data("预设")

def out_dir():
    if PORTABLE:
        p = res("输出"); os.makedirs(p, exist_ok=True); return p
    return data("输出")

def font_dirs(extra=None):
    """规则里写的相对字体目录：工具目录下的中/英文名 + 用户数据目录下的「字体」。"""
    out = []
    for d in (extra or ["字体"]):
        out.append(d if os.path.isabs(d) else res(d))
    if not PORTABLE: out.append(data("字体"))
    return out

def log_path(name):
    return data(name)

def helper(name):
    return res("辅助脚本", name)

def asset(name):
    return res("素材", name)

def sample(name):
    return res("样例", name)

def describe():
    return "工具目录：%s%s" % (HERE, "" if PORTABLE else "（只读）\n数据目录：%s" % DATA)
