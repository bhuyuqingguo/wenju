# -*- coding: utf-8 -*-
"""
docx_fmt.py —— 文矩·文档格式整理系统 核心引擎（纯标准库，无第三方依赖）
用法：python docx_fmt.py 文件1.docx [文件2.docx ...]
      规则读取同目录 rules.json；输出「原名_已整理.docx」与「原名_整理报告.txt」，原件不动。
"""
import sys, os, re, json, zipfile, shutil, copy, io
import xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fontembed

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
def q(tag): return "{%s}%s" % (W, tag)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paths

CN_NUM = "一二三四五六七八九十"
def cn(n):
    if n <= 10: return CN_NUM[n-1]
    if n < 20: return "十" + CN_NUM[n-11]
    t, o = divmod(n, 10)
    return CN_NUM[t-1] + "十" + (CN_NUM[o-1] if o else "")

def cm2twip(cm): return int(round(cm / 2.54 * 1440))
def pt2half(pt): return int(round(pt * 2))
def pt2twip(pt): return int(round(pt * 20))

# ---------------------------------------------------------------- XML 工具
def parse_keep_ns(xml_bytes):
    """解析 XML，并记录根标签原文（含全部 xmlns 声明），序列化后原样放回，避免 Word 报「不可读内容」。"""
    text = xml_bytes.decode("utf-8")
    for pre, uri in re.findall(r'xmlns:([\w\-]+)="([^"]+)"', text):
        ET.register_namespace(pre, uri)
    root = ET.fromstring(xml_bytes)
    m = re.search(r"<[\w:]+\s[^>]*>", text)  # 第一个带属性的元素即根开始标签
    return root, m.group(0)

def serialize(root, root_tag):
    body = ET.tostring(root, encoding="unicode")
    m = re.match(r"<[^>]+>", body)
    # 原根标签的 xmlns 声明为准，再补上 ET 汇集到根上的、原根标签没有的声明（文内局部声明的命名空间）
    have = set(re.findall(r'xmlns:([\w\-]+)=', root_tag))
    extra = [d for d in re.findall(r'\sxmlns:[\w\-]+="[^"]+"', m.group(0)) if re.search(r'xmlns:([\w\-]+)', d).group(1) not in have]
    tag = root_tag[:-1] + "".join(extra) + ">"
    body = tag + body[m.end():]
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n' + body).encode("utf-8")

def child(el, tag, create=False, before=None):
    c = el.find("w:" + tag, NS)
    if c is None and create:
        c = ET.Element(q(tag))
        idx = len(el)
        if before:
            for i, e in enumerate(el):
                if e.tag in [q(b) for b in before]:
                    idx = i; break
        el.insert(idx, c)
    return c

def set_attr(el, name, val):
    el.set(q(name), str(val))

def remove(el, tag):
    for c in el.findall("w:" + tag, NS): el.remove(c)

# pPr 子元素规范顺序（Word 校验严格）
PPR_ORDER = ["pStyle","keepNext","keepLines","pageBreakBefore","framePr","widowControl","numPr",
             "suppressLineNumbers","pBdr","shd","tabs","suppressAutoHyphens","kinsoku","wordWrap",
             "overflowPunct","topLinePunct","autoSpaceDE","autoSpaceDN","bidi","adjustRightInd",
             "snapToGrid","spacing","ind","contextualSpacing","mirrorIndents","suppressOverlap",
             "jc","textDirection","textAlignment","textboxTightWrap","outlineLvl","divId","cnfStyle",
             "rPr","sectPr","pPrChange"]
SECT_ORDER = ["headerReference","footerReference","footnotePr","endnotePr","type","pgSz","pgMar","paperSrc","pgBorders",
              "lnNumType","pgNumType","cols","formProt","vAlign","noEndnote","titlePg","textDirection","bidi","rtlGutter","docGrid",
              "printerSettings","sectPrChange"]
RPR_ORDER = ["rStyle","rFonts","b","bCs","i","iCs","caps","smallCaps","strike","dstrike","outline",
             "shadow","emboss","imprint","noProof","snapToGrid","vanish","webHidden","color","spacing",
             "w","kern","position","sz","szCs","highlight","u","effect","bdr","shd","fitText","vertAlign",
             "rtl","cs","em","lang","eastAsianLayout","specVanish","oMath"]
def reorder(el, order):
    rank = {q(t): i for i, t in enumerate(order)}
    kids = list(el)
    kids.sort(key=lambda e: rank.get(e.tag, 999))
    for k in list(el): el.remove(k)
    for k in kids: el.append(k)

def ppr(p): return child(p, "pPr", create=True, before=["r","hyperlink","fldSimple","bookmarkStart","proofErr"])
def rpr(r): return child(r, "rPr", create=True, before=["t","tab","br","drawing","pict","fldChar","instrText","sym","cr"])

KEEP_ORIGINAL_FONTS = False  # 字体模式=原文档 时为 True：不改任何字体名
def set_fonts(rp, east, west, hint=True):
    if KEEP_ORIGINAL_FONTS: return
    f = child(rp, "rFonts", create=True)
    for a in list(f.attrib): del f.attrib[a]
    set_attr(f, "ascii", west); set_attr(f, "hAnsi", west); set_attr(f, "cs", west)
    set_attr(f, "eastAsia", east)
    if hint: set_attr(f, "hint", "eastAsia")

SIZE_NAMES = {"初号": 42, "小初": 36, "一号": 26, "小一": 24, "二号": 22, "小二": 18, "三号": 16, "小三": 15,
              "四号": 14, "小四": 12, "五号": 10.5, "小五": 9, "六号": 7.5, "小六": 6.5, "七号": 5.5, "八号": 5}
def size_pt(v, default=12):
    """字号：接受中文字号名（三号、小四…）或磅数（16、"16"、"16磅"）。"""
    if v is None or v == "": return default
    if isinstance(v, (int, float)): return float(v)
    t = str(v).strip().replace("磅", "").replace("pt", "").replace("號", "号")
    if t in SIZE_NAMES: return float(SIZE_NAMES[t])
    try: return float(t)
    except ValueError: return default

def set_size(rp, pt):
    pt = size_pt(pt)
    for t in ("sz", "szCs"):
        e = child(rp, t, create=True); set_attr(e, "val", pt2half(pt))

def set_bold(rp, on):
    remove(rp, "b"); remove(rp, "bCs")
    if on:
        child(rp, "b", create=True); child(rp, "bCs", create=True)

def set_spacing(pp, line_pt=None, before_pt=0, after_pt=0):
    s = child(pp, "spacing", create=True)
    for a in list(s.attrib): del s.attrib[a]
    set_attr(s, "before", pt2twip(before_pt)); set_attr(s, "after", pt2twip(after_pt))
    if line_pt:
        set_attr(s, "line", pt2twip(line_pt)); set_attr(s, "lineRule", "exact")
    else:
        set_attr(s, "line", 240); set_attr(s, "lineRule", "auto")  # 单倍行距，图片段不被裁切

def set_indent(pp, first_chars=0):
    i = child(pp, "ind", create=True)
    for a in list(i.attrib): del i.attrib[a]
    if first_chars:
        set_attr(i, "firstLineChars", first_chars * 100)
        set_attr(i, "firstLine", first_chars * 320)  # 按三号字估算的兜底值
    else:
        set_attr(i, "firstLine", 0); set_attr(i, "firstLineChars", 0)

def set_jc(pp, val):
    j = child(pp, "jc", create=True); set_attr(j, "val", val)

def para_text(p):
    return "".join(t.text or "" for t in p.iter(q("t")))

def runs(p):
    return [r for r in p.iter(q("r"))]

def has_image(p):
    WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
    return next(p.iter(WP + "inline"), None) is not None or next(p.iter(WP + "anchor"), None) is not None or \
           p.find(".//w:pict", NS) is not None or p.find(".//w:object", NS) is not None

def style_id(p):
    ps = p.find("w:pPr/w:pStyle", NS)
    return ps.get(q("val")) if ps is not None else ""

def set_style(p, sid):
    pp = ppr(p)
    ps = child(pp, "pStyle", create=True); set_attr(ps, "val", sid)

def set_para_text(p, text, keep_rpr=True):
    """把段落文本替换为单一 run（保留首个 run 的 rPr）。"""
    first = None
    for r in list(p):
        if r.tag == q("r"):
            if first is None: first = r
            else: p.remove(r)
        elif r.tag in (q("hyperlink"), q("fldSimple"), q("smartTag")):
            p.remove(r)
    if first is None:
        first = ET.SubElement(p, q("r"))
    rp = first.find("w:rPr", NS)
    for c in list(first): first.remove(c)
    if rp is not None and keep_rpr: first.append(rp)
    t = ET.SubElement(first, q("t")); t.text = text
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return first


# ---------------------------------------------------------------- 统一段落格式
PARA_DEFAULTS = {"字号": 16, "加粗": False, "对齐": "both", "行距类型": "固定值", "行距值": 25,
                 "段前": 0, "段后": 0, "首行缩进字符": 0, "左缩进字符": 0, "右缩进字符": 0}
def apply_para_fmt(pp, cfg):
    """按配置写段落属性：段前/段后（磅）、行距（固定值/多倍/最小值/单倍）、缩进（字符）、对齐。"""
    c = dict(PARA_DEFAULTS); c.update({k: v for k, v in cfg.items() if not k.startswith("_")})
    sp = child(pp, "spacing", create=True)
    for a in list(sp.attrib): del sp.attrib[a]
    set_attr(sp, "before", pt2twip(float(c["段前"]))); set_attr(sp, "after", pt2twip(float(c["段后"])))
    t, v = c["行距类型"], float(c["行距值"] or 0)
    if t == "固定值": set_attr(sp, "line", pt2twip(v)); set_attr(sp, "lineRule", "exact")
    elif t == "最小值": set_attr(sp, "line", pt2twip(v)); set_attr(sp, "lineRule", "atLeast")
    elif t == "多倍": set_attr(sp, "line", int(round(240 * (v or 1)))); set_attr(sp, "lineRule", "auto")
    else: set_attr(sp, "line", 240); set_attr(sp, "lineRule", "auto")  # 单倍
    ind = child(pp, "ind", create=True)
    for a in list(ind.attrib): del ind.attrib[a]
    size = size_pt(c.get("字号"), 12)
    fc, lc, rc = float(c["首行缩进字符"]), float(c["左缩进字符"]), float(c["右缩进字符"])
    set_attr(ind, "leftChars", int(round(lc * 100))); set_attr(ind, "left", int(round(lc * size * 20)))
    set_attr(ind, "rightChars", int(round(rc * 100))); set_attr(ind, "right", int(round(rc * size * 20)))
    if fc < 0:
        set_attr(ind, "hangingChars", int(round(-fc * 100))); set_attr(ind, "hanging", int(round(-fc * size * 20)))
    else:
        set_attr(ind, "firstLineChars", int(round(fc * 100))); set_attr(ind, "firstLine", int(round(fc * size * 20)))
    set_jc(pp, c["对齐"] or "both")

def apply_run_fmt(rp, cfg, font, west):
    c = dict(PARA_DEFAULTS); c.update({k: v for k, v in cfg.items() if not k.startswith("_")})
    set_fonts(rp, font, west); set_size(rp, c["字号"]); set_bold(rp, bool(c.get("加粗")))

def normalize_rules(R):
    """旧版规则（行距固定值/标题缩进字符/封面标题字号等）自动升级为统一段落格式结构。"""
    def up(d, defaults):
        d = dict(d)
        if "行距固定值" in d and "行距类型" not in d:
            d["行距类型"] = "固定值"; d["行距值"] = d.pop("行距固定值")
        for k, v in defaults.items(): d.setdefault(k, v)
        return d
    B = R["正文"] = up(R["正文"], PARA_DEFAULTS)
    H = R["标题"]; hind = H.pop("标题缩进字符", 0)
    H.setdefault("级数", 4)
    default_fmt = {"一级": "汉字顿号", "二级": "括号汉字", "三级": "数字点"}
    for i, k in enumerate(LEVEL_KEYS, start=1):
        base = H.get(k) or dict(H.get("四级", {}), 格式="多级数字")
        d = up(base, dict(PARA_DEFAULTS, 对齐="both", 首行缩进字符=hind, 行距值=29 if i <= 2 else 25))
        d.setdefault("格式", default_fmt.get(k, "多级数字"))
        H[k] = d
    F = R["字体"]
    for k in LEVEL_KEYS:
        F.setdefault(k + "标题", F.get("四级标题", F.get("正文", "仿宋_GB2312")))
    C = R["题注"] = up(R["题注"], dict(PARA_DEFAULTS, 字号=10.5, 对齐="center", 行距值=20, 段前=6, 段后=6))
    T = R["表格"] = up(R["表格"], dict(PARA_DEFAULTS, 字号=12, 对齐="center", 行距值=20))
    G = R["图片"] = up(R["图片"], dict(PARA_DEFAULTS, 对齐="center", 行距类型="单倍", 行距值=1, 段前=6))
    G.pop("居中", None); G.pop("取消首行缩进", None)
    cv = R["封面"]
    if "标题" not in cv or not isinstance(cv.get("标题"), dict):
        cv["标题"] = dict(PARA_DEFAULTS, 字号=cv.pop("标题字号", 24), 对齐="center" if cv.pop("标题居中", True) else "both", 行距类型="单倍", 行距值=1)
    if "落款" not in cv or not isinstance(cv.get("落款"), dict):
        cv["落款"] = dict(PARA_DEFAULTS, 字号=cv.pop("落款字号", 16), 对齐="center", 行距类型="固定值", 行距值=B.get("行距值", 25))
    return R

LEVEL_KEYS = ["一级", "二级", "三级", "四级", "五级", "六级", "七级", "八级", "九级"]
CN_DIGITS = "一二三四五六七八九十"
FMT_KINDS = ["汉字顿号", "括号汉字", "数字点", "多级数字", "括号数字", "圈数字", "字母点", "第X章"]

def level_count(H):
    try: return max(1, min(9, int(H.get("级数", 4))))
    except Exception: return 4

# ---------------------------------------------------------------- 标题多级自动编号
def heading_numbering_xml(H, abstract_id, num_id):
    """生成与标题样式关联的多级列表定义（abstractNum + num）。"""
    n_lv = level_count(H)
    fmts = [H[LEVEL_KEYS[i]].get("格式", "多级数字") for i in range(n_lv)]
    def chain_base(k):
        """多级数字：向上找连续的 数字点/多级数字 链的起点级别。"""
        b = k
        while b > 1 and fmts[b - 2] in ("数字点", "多级数字"): b -= 1
        return b
    def lvl_text(k, fmt):
        n = "%%%d" % k
        if fmt == "汉字顿号": return "chineseCounting", n + "、"
        if fmt == "第X章": return "chineseCounting", "第" + n + "章"
        if fmt == "括号汉字": return "chineseCounting", "（" + n + "）"
        if fmt == "数字点": return "decimal", n + "."
        if fmt == "括号数字": return "decimal", "（" + n + "）"
        if fmt == "圈数字": return "decimalEnclosedCircleChinese", n
        if fmt == "字母点": return "lowerLetter", n + "."
        if fmt == "多级数字":
            b = chain_base(k)
            return "decimal", ".".join("%%%d" % j for j in range(b, k + 1)) if k > b else n + "."
        return "decimal", n + "."
    lvls = []
    for k in range(1, n_lv + 1):
        key = LEVEL_KEYS[k - 1]
        numfmt, text = lvl_text(k, fmts[k - 1])
        lvls.append('<w:lvl w:ilvl="%d"><w:start w:val="1"/><w:numFmt w:val="%s"/><w:pStyle w:val="__HSTYLE%d__"/>'
                    '<w:suff w:val="nothing"/><w:lvlText w:val="%s"/><w:lvlJc w:val="left"/>'
                    '<w:pPr><w:ind w:left="0" w:firstLine="0"/></w:pPr></w:lvl>' % (k - 1, numfmt, k, text))
    abstract = '<w:abstractNum w:abstractNumId="%d"><w:multiLevelType w:val="multilevel"/>%s</w:abstractNum>' % (abstract_id, "".join(lvls))
    num = '<w:num w:numId="%d"><w:abstractNumId w:val="%d"/></w:num>' % (num_id, abstract_id)
    return abstract, num

def ensure_heading_numbering(items, H, sid_map):
    """在 numbering.xml 中写入标题编号定义，返回 numId。"""
    W_ = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    path = "word/numbering.xml"
    if path in items:
        xml = items[path].decode("utf-8")
    else:
        xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:numbering xmlns:w="%s"></w:numbering>' % W_)
        rels = items["word/_rels/document.xml.rels"].decode("utf-8")
        if "numbering.xml" not in rels:
            rels = rels.replace("</Relationships>", '<Relationship Id="rIdNumberingH" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/></Relationships>')
            items["word/_rels/document.xml.rels"] = rels.encode("utf-8")
        ct = items["[Content_Types].xml"].decode("utf-8")
        if "/word/numbering.xml" not in ct:
            ct = ct.replace("</Types>", '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/></Types>')
            items["[Content_Types].xml"] = ct.encode("utf-8")
    # 清除旧的标题关联（其他列表若挂了 Heading 样式，会与新定义冲突）
    for k in range(1, 10):
        xml = re.sub(r'<w:pStyle w:val="%s"\s*/>' % re.escape(sid_map.get("Heading%d" % k, "Heading%d" % k)), "", xml)
    ids = [int(x) for x in re.findall(r'w:abstractNumId="(\d+)"', xml)] or [-1]
    nums = [int(x) for x in re.findall(r'<w:num w:numId="(\d+)"', xml)] or [0]
    abstract_id, num_id = max(ids) + 1, max(nums) + 1
    abstract, num = heading_numbering_xml(H, abstract_id, num_id)
    for k in range(1, 10):
        abstract = abstract.replace("__HSTYLE%d__" % k, sid_map.get("Heading%d" % k, "Heading%d" % k))
    # abstractNum 须位于所有 num 之前
    m = re.search(r"<w:num\b", xml)
    if m: xml = xml[:m.start()] + abstract + xml[m.start():]
    else: xml = xml.replace("</w:numbering>", abstract + "</w:numbering>")
    m = re.search(r"<w:numIdMacAtCleanup", xml)
    if m: xml = xml[:m.start()] + num + xml[m.start():]
    else: xml = xml.replace("</w:numbering>", num + "</w:numbering>")
    items[path] = xml.encode("utf-8")
    return num_id

# ---------------------------------------------------------------- 主处理类
class Formatter:
    def __init__(self, rules):
        self.R = rules
        self.log = []
        self.stats = {}
        self.punct_log = []
        self.auto_caps = []
        self.toc_range = None
        self.toc_ids = set()
        self.sid = {}  # 逻辑样式名 → 文档实际 styleId（中文 Word 的标题样式 id 为 "1""2"、正文为 "a"）

    def note(self, k, n=1):
        self.stats[k] = self.stats.get(k, 0) + n

    # ---------- 页面
    def do_sections(self, body):
        """页面设置。分节符、纸张大小与方向一律保留；只按节的方向套用页边距。"""
        P = self.R["页面"]
        keep = P.get("纸张方向与分节", "保留") == "保留"
        mode = P.get("横向页边距", "互换")
        for sp in body.iter(q("sectPr")):
            sz = child(sp, "pgSz", create=True)
            w = int(sz.get(q("w"), 11906)); h = int(sz.get(q("h"), 16838))
            landscape = sz.get(q("orient")) == "landscape" or w > h
            if not keep:
                set_attr(sz, "w", 11906); set_attr(sz, "h", 16838)
                if q("orient") in sz.attrib: del sz.attrib[q("orient")]
                landscape = False
            if landscape and mode == "不改":
                self.note("横向节数（页边距未改）"); continue
            mar = child(sp, "pgMar", create=True)
            t, b, l, r = P["上边距"], P["下边距"], P["左边距"], P["右边距"]
            if landscape and mode == "互换":
                t, b, l, r = l, r, t, b
            set_attr(mar, "top", cm2twip(t)); set_attr(mar, "bottom", cm2twip(b))
            set_attr(mar, "left", cm2twip(l)); set_attr(mar, "right", cm2twip(r))
            set_attr(mar, "header", cm2twip(P["页眉距"])); set_attr(mar, "footer", cm2twip(P["页脚距"]))
            if q("gutter") not in mar.attrib: set_attr(mar, "gutter", 0)
            self.note("横向节数" if landscape else "纵向节数")

    # ---------- 样式表
    def do_styles(self, styles):
        F, B, H, C, T = self.R["字体"], self.R["正文"], self.R["标题"], self.R["题注"], self.R["表格"]
        west = F["西文"]
        # docDefaults
        dd = child(styles, "docDefaults", create=True)
        rpd = child(dd, "rPrDefault", create=True); rp = child(rpd, "rPr", create=True)
        set_fonts(rp, F["正文"], west); set_size(rp, B["字号"])
        lang = child(rp, "lang", create=True); set_attr(lang, "val", "en-US"); set_attr(lang, "eastAsia", "zh-CN")
        reorder(rp, RPR_ORDER)

        def ensure(sid, name, based="Normal", next_="Normal", outline=None):
            st = None
            for s in styles.findall("w:style", NS):
                n = s.find("w:name", NS)
                if s.get(q("type"), "paragraph") == "paragraph" and n is not None and (n.get(q("val")) or "").lower() == name.lower():
                    st = s; break
            if st is None:
                for s in styles.findall("w:style", NS):
                    if s.get(q("styleId")) == sid: st = s; break
            if st is None and sid == "Normal":  # 默认段落样式即正文
                for s in styles.findall("w:style", NS):
                    if s.get(q("type"), "paragraph") == "paragraph" and s.get(q("default")) in ("1", "true"): st = s; break
            if st is not None:
                self.sid[sid] = st.get(q("styleId"))
            else:
                self.sid[sid] = sid
            based = self.sid.get(based, based) if based else based
            next_ = self.sid.get(next_, next_)
            if st is None:
                st = ET.SubElement(styles, q("style"))
                set_attr(st, "type", "paragraph"); set_attr(st, "styleId", sid)
                n = ET.SubElement(st, q("name")); set_attr(n, "val", name)
                if based:
                    b = ET.SubElement(st, q("basedOn")); set_attr(b, "val", based)
                nx = ET.SubElement(st, q("next")); set_attr(nx, "val", next_)
                ET.SubElement(st, q("qFormat"))
            old_fonts = st.find("w:rPr/w:rFonts", NS)
            remove(st, "pPr"); remove(st, "rPr")
            pp = ET.SubElement(st, q("pPr")); rp = ET.SubElement(st, q("rPr"))
            if KEEP_ORIGINAL_FONTS and old_fonts is not None: rp.append(copy.deepcopy(old_fonts))
            if outline is not None:
                ET.SubElement(pp, q("keepNext")); ET.SubElement(pp, q("keepLines"))
                o = ET.SubElement(pp, q("outlineLvl")); set_attr(o, "val", outline)
            return st, pp, rp

        G, cv = self.R["图片"], self.R["封面"]
        # Normal / 正文
        st, pp, rp = ensure("Normal", "Normal", based=None, next_="Normal")
        wc = child(pp, "widowControl", create=True); set_attr(wc, "val", "0")
        apply_para_fmt(pp, B); apply_run_fmt(rp, B, F["正文"], west)
        k = child(rp, "kern", create=True); set_attr(k, "val", 2)
        reorder(pp, PPR_ORDER); reorder(rp, RPR_ORDER)
        # 标题 1–4
        auto_num = H.get("编号方式", "自动编号") == "自动编号" and H.get("重新编号", True)
        for lvl in range(1, level_count(H) + 1):
            key = LEVEL_KEYS[lvl - 1]; font_key = key + "标题"
            st, pp, rp = ensure("Heading%d" % lvl, "heading %d" % lvl, outline=lvl - 1)
            apply_para_fmt(pp, H[key]); apply_run_fmt(rp, H[key], F[font_key], west)
            if auto_num:
                np_ = ET.SubElement(pp, q("numPr"))
                il = ET.SubElement(np_, q("ilvl")); set_attr(il, "val", lvl - 1)
                ni = ET.SubElement(np_, q("numId")); set_attr(ni, "val", "__HEADNUM__")  # 稍后替换为实际 numId
            reorder(pp, PPR_ORDER); reorder(rp, RPR_ORDER)
        # 题注
        st, pp, rp = ensure("Caption", "caption")
        ET.SubElement(pp, q("keepNext"))
        apply_para_fmt(pp, C); apply_run_fmt(rp, C, F["题注"], west)
        reorder(pp, PPR_ORDER); reorder(rp, RPR_ORDER)
        # 表格文字
        st, pp, rp = ensure("TableText", "表格文字")
        apply_para_fmt(pp, T); apply_run_fmt(rp, T, F["表格"], west)
        reorder(pp, PPR_ORDER); reorder(rp, RPR_ORDER)
        # 图片段
        st, pp, rp = ensure("Figure", "图片")
        ET.SubElement(pp, q("keepNext"))
        apply_para_fmt(pp, G)
        reorder(pp, PPR_ORDER)
        # 封面
        st, pp, rp = ensure("CoverTitle", "封面标题")
        apply_para_fmt(pp, cv["标题"]); apply_run_fmt(rp, cv["标题"], F["封面标题"], west)
        reorder(pp, PPR_ORDER); reorder(rp, RPR_ORDER)
        st, pp, rp = ensure("CoverInfo", "封面落款")
        apply_para_fmt(pp, cv["落款"]); apply_run_fmt(rp, cv["落款"], F["封面落款"], west)
        reorder(pp, PPR_ORDER); reorder(rp, RPR_ORDER)
        self.note("样式重建数", 9)

    # ---------- 段落分类
    RE_H1 = re.compile(r"^\s*(?:第[一二三四五六七八九十]{1,3}[章节部分篇]|[一二三四五六七八九十]{1,3}[、．.：:，,])\s*")
    RE_H2 = re.compile(r"^\s*[（(][一二三四五六七八九十]{1,3}[）)]\s*")
    RE_H3 = re.compile(r"^\s*(?:(\d{1,2})[．.、：:]|[（(]?\d{1,2}[）)])\s*(?!\d)")
    RE_H4 = re.compile(r"^\s*\d{1,2}(?:[.．]\d{1,2})+[．.、]?\s*")
    RE_HCIRCLE = re.compile(r"^\s*[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]\s*")
    RE_HALPHA = re.compile(r"^\s*[a-zA-Z][.．、)）]\s*")
    RE_HPARENNUM = re.compile(r"^\s*[（(]\d{1,2}[）)]\s*")

    def label_level(self, txt):
        """由标题文字的编号写法推断级别：先按各级配置的「格式」匹配，找不到时用常规顺序。"""
        H = self.R["标题"]; n = level_count(H)
        fmts = [H[LEVEL_KEYS[i]].get("格式", "多级数字") for i in range(n)]
        def first(kind):
            for i, f in enumerate(fmts):
                if f == kind: return i + 1
            return None
        m = self.RE_H4.match(txt)
        if m:
            dots = m.group(0).strip().rstrip("．.、").count(".") + m.group(0).strip().rstrip("．.、").count("．")
            base = first("数字点") or first("多级数字") or 3
            # 数字点级别 +点数 → 多级数字级别
            lvl = base + dots
            return min(lvl, n)
        if txt.strip().startswith("第") and self.RE_H1.match(txt): return first("第X章") or first("汉字顿号") or 1
        if self.RE_H1.match(txt): return first("汉字顿号") or first("第X章") or 1
        if self.RE_H2.match(txt): return first("括号汉字") or 2
        if self.RE_HPARENNUM.match(txt): return first("括号数字") or first("数字点") or 3
        if self.RE_HCIRCLE.match(txt): return first("圈数字") or min(n, 5)
        if self.RE_HALPHA.match(txt): return first("字母点") or min(n, 5)
        if self.RE_H3.match(txt): return first("数字点") or first("多级数字") or 3
        return None
    RE_FIG = re.compile(r"^\s*图\s*[\d０-９]+(?:[\-－—–.．][\d０-９]+)?\s*[:：]?\s*")
    RE_TAB = re.compile(r"^\s*表\s*[\d０-９]+(?:[\-－—–.．][\d０-９]+)?\s*[:：]?\s*")

    RE_TOC_TITLE = re.compile(r"^\s*目\s*录\s*$")
    def is_toc_para(self, p):
        sid = style_id(p)
        if re.match(r"^(TOC|toc)", sid) or re.match(r"^\d\d$", sid) and False: return True
        for it in p.iter(q("instrText")):
            if it.text and re.search(r"\b(TOC|PAGEREF)\b", it.text): return True
        if p.find(".//w:fldSimple", NS) is not None:
            for f in p.iter(q("fldSimple")):
                if re.search(r"\b(TOC|PAGEREF)\b", f.get(q("instr"), "")): return True
        return False

    def classify(self, p, prev_p, next_is_table, prev_has_img):
        sid = style_id(p); txt = para_text(p).strip()
        if id(p) in self.toc_ids or self.RE_TOC_TITLE.match(txt) or self.is_toc_para(p): return "keep"
        if not txt and not has_image(p): return "empty"
        if has_image(p): return "figure"
        if next_is_table and self.RE_TAB.match(txt): return "tabcap"
        if prev_has_img and self.RE_FIG.match(txt): return "figcap"
        if self.RE_TAB.match(txt) and len(txt) < 60 and next_is_table: return "tabcap"
        n_lv = level_count(self.R["标题"])
        for lvl in range(1, 10):
            if sid and sid == self.sid.get("Heading%d" % lvl): return "h%d" % min(lvl, n_lv)
        m = re.match(r"^(?:[Hh]eading)?([1-9])$", sid)
        if m: return "h%d" % min(int(m.group(1)), n_lv)
        if self.R["标题"]["识别"] and len(txt) < 60 and not txt.endswith(("。", "；", "，", "：")):
            lv = self.label_level(txt)
            if lv: return "h%d" % lv
        if self.RE_FIG.match(txt) and len(txt) < 60: return "figcap"
        if self.R["题注"].get("缺失时自动补编号", True) and self.is_title_candidate(p, txt):
            if next_is_table: return "tabcap_auto"
            if prev_has_img: return "figcap_auto"
        return "body"

    def is_title_candidate(self, p, txt):
        """无编号的题名行：短、不以句读结尾、不是列表/标题；居中段更可信。"""
        if not txt or len(txt) > 40: return False
        if txt.endswith(("。", "；", "，", "：", ":", ";", ",", ".", "！", "？")): return False
        if re.match(r"^\s*(?:[（(]?\d+[）).、]|[一二三四五六七八九十]+[、.]|[•·\-—])", txt): return False
        jc = p.find("w:pPr/w:jc", NS)
        centered = jc is not None and jc.get(q("val")) == "center"
        return centered or len(txt) <= 25

    # ---------- run 清理
    def clean_runs(self, p, size_pt=None, font=None, keep_bi=True, west=None):
        F = self.R["字体"]; west = west or F["西文"]
        for r in runs(p):
            rp = r.find("w:rPr", NS)
            if rp is None:
                continue
            keep = {}
            if KEEP_ORIGINAL_FONTS:
                e = rp.find("w:rFonts", NS)
                if e is not None: keep["rFonts"] = e
            if keep_bi:
                for t in ("b", "bCs", "i", "iCs", "u", "vertAlign", "color", "strike"):
                    e = rp.find("w:" + t, NS)
                    if e is not None: keep[t] = e
            for c in list(rp): rp.remove(c)
            for e in keep.values(): rp.append(e)
            # 字体与字号不写直接格式，由段落样式承载——这样在 Word 中修改样式即可全文联动
            if self.R.get("输出", {}).get("字体字号写入直接格式", False):
                if font: set_fonts(rp, font, west)
                if size_pt: set_size(rp, size_pt)
            reorder(rp, RPR_ORDER)
            if len(rp) == 0: r.remove(rp)

    def para_reset(self, p, style, first_chars=None, jc=None, keep_next=False):
        pp = ppr(p)
        for tag in ("pStyle", "numPr", "spacing", "ind", "jc", "keepNext", "rPr", "outlineLvl", "snapToGrid", "widowControl", "adjustRightInd"):
            remove(pp, tag)
        ps = ET.SubElement(pp, q("pStyle")); set_attr(ps, "val", self.sid.get(style, style))
        if keep_next: ET.SubElement(pp, q("keepNext"))
        reorder(pp, PPR_ORDER)

    # ---------- 括号内改楷体
    def bracket_font(self, p):
        F = self.R["字体"]; west = F["西文"]
        for r in runs(p):
            ts = [t for t in r.findall("w:t", NS)]
            if len(ts) != 1: continue
            t = ts[0]; s = t.text or ""
            if not re.search(r"[（(][^（）()]{1,80}[）)]", s): continue
            parts = re.split(r"([（(][^（）()]{1,80}[）)])", s)
            base_rp = r.find("w:rPr", NS)
            idx = list(p).index(r); p.remove(r)
            for i, seg in enumerate(parts):
                if not seg: continue
                nr = ET.Element(q("r"))
                nrp = copy.deepcopy(base_rp) if base_rp is not None else ET.Element(q("rPr"))
                nr.append(nrp)
                if i % 2 == 1:
                    set_fonts(nrp, F["括号内"], west); reorder(nrp, RPR_ORDER)
                nt = ET.SubElement(nr, q("t")); nt.text = seg
                nt.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                p.insert(idx, nr); idx += 1
            self.note("括号内改楷体段数")

    # ---------- 标点修订（可开关，逐条记录）
    CJK = "一-鿿"
    CJK_PUNCT = "。，、；：？！（）“”‘’《》〈〉【】—…～·"
    HALF2FULL = {",": "，", ";": "；", ":": "：", "?": "？", "!": "！", "(": "（", ")": "）"}
    def punct(self, p, where="正文"):
        S = self.R["标点"]
        if not S.get("启用", True): return
        full_ctx = self.CJK + self.CJK_PUNCT
        changed = 0
        for t in p.iter(q("t")):
            s0 = t.text or ""
            s = s0
            # 1 全角字母数字 → 半角（型号、数字须半角）
            if S.get("全角字母数字转半角", True):
                s = s.translate({c: c - 0xFEE0 for c in range(0xFF10, 0xFF5B) if c not in (0xFF08, 0xFF09, 0xFF0C, 0xFF1A, 0xFF1B, 0xFF1F, 0xFF01)})
            # 2 中文语境半角标点 → 全角
            if S.get("中文语境半角转全角", True):
                s = re.sub(r"(?<=[%s])[ \u3000]*([,;:?!])[ \u3000]*(?=[%s]|$)" % (full_ctx, self.CJK), lambda m: self.HALF2FULL[m.group(1)], s)
                s = re.sub(r"(?<=[%s])[,;:?!()]|[,;:?!()](?=[%s])" % (full_ctx, self.CJK), lambda m: self.HALF2FULL[m.group(0)], s)
                s = re.sub(r"（([^()（）]*)\)", "（\\1）", s)   # 半全角括号配对
                s = re.sub(r"\(([^()（）]*)）", "（\\1）", s)
                s = re.sub(r"(?<=[%s）”])\.(?=[%s]|\s*$)" % (self.CJK, self.CJK), "。", s)
                s = re.sub(r"(?<=[%s])\((?=[A-Za-z0-9])" % self.CJK, "（", s)   # 中文后接 (abc → （abc
                s = re.sub(r"(?<=[A-Za-z0-9])\)(?=[%s])" % self.CJK, "）", s)   # abc) 后接中文 → abc）
            # 3 百分号
            if S.get("百分号全角", True):
                s = re.sub(r"(?<=[0-9])%%(?=[%s]|\s*$|[，。；：、）]|\s*[~～])" % self.CJK, "％", s)
            # 4 省略号与破折号
            if S.get("省略号破折号规范", True):
                s = re.sub(r"\.{3,}|。{3,}|…(?!…)", "……", s)
                s = re.sub(r"(?<=[%s])-{2,}(?=[%s])|(?<=[%s])—(?!—)(?=[%s])" % (self.CJK, self.CJK, self.CJK, self.CJK), "——", s)
                s = re.sub(r"(?<=[%s％])\s*~\s*(?=[0-9%s])" % (self.CJK + "0-9", self.CJK), "～", s)
            # 5 引号配对：中文语境下的 " " → “ ”，' ' → ‘ ’
            if S.get("引号中文化", True):
                def pair(txt, half, l, r):
                    out=[]; open_=False
                    for i,ch in enumerate(txt):
                        if ch == half:
                            prev = txt[i-1] if i else ""; nxt = txt[i+1] if i+1 < len(txt) else ""
                            if re.match("[%s%s]" % (self.CJK, self.CJK_PUNCT), prev) or re.match("[%s]" % self.CJK, nxt) or (open_ and re.match("[%s%s]" % (self.CJK, self.CJK_PUNCT), prev+nxt or " ")):
                                out.append(r if open_ else l); open_ = not open_; continue
                        out.append(ch)
                    return "".join(out)
                s = pair(s, '"', "“", "”")
                s = pair(s, "'", "‘", "’")
            # 6 重复标点与多余空格
            if S.get("去重复标点", True):
                s = re.sub(r"([，。、；：？！])\1+", r"\1", s)
                s = re.sub(r"，。", "。", s)
            if S.get("去中文间多余空格", True):
                s = re.sub(r"(?<=[%s])[ \u3000]+(?=[%s])" % (full_ctx, full_ctx), "", s)
                s = re.sub(r"[ \u3000]+(?=[，。、；：？！）”])", "", s)
                s = re.sub(r"(?<=[（“])[ \u3000]+", "", s)
            if s != s0:
                t.text = s; changed += 1
                if len(self.punct_log) < 300:
                    self.punct_log.append("[%s] %s\n      → %s" % (where, s0.strip()[:60], s.strip()[:60]))
        if changed: self.note("标点修订处数", changed)

    def find_toc(self, kids):
        """返回 (目录起始下标, 目录结束下标) 或 None。识别：目录标题段、TOC 域、TOC 样式段、目录内容控件(sdt)。"""
        start = end = None
        self.toc_ids = set()
        open_fld = 0  # 跨段落的 TOC 域：begin 后直到 end 之间的段落都属于目录
        for i, k in enumerate(kids):
            if k.tag == q("p") and start is not None and open_fld > 0:
                self.toc_ids.add(id(k)); end = i
                for fc in k.iter(q("fldChar")):
                    t = fc.get(q("fldCharType"))
                    if t == "begin": open_fld += 1
                    elif t == "end": open_fld -= 1
                continue
            if k.tag == q("sdt"):
                gal = k.find(".//w:docPartGallery", NS)
                if gal is not None and "Table of Contents" in (gal.get(q("val")) or ""):
                    start = i if start is None else start; end = i; continue
                if any(re.search(r"\bTOC\b", it.text or "") for it in k.iter(q("instrText"))):
                    start = i if start is None else start; end = i; continue
            if k.tag != q("p"):
                if start is not None and end is not None and i > end + 3: break
                continue
            txt = para_text(k).strip()
            if start is None and self.RE_TOC_TITLE.match(txt) and i < len(kids) // 2:
                start = i; end = i; self.toc_ids.add(id(k)); continue
            if start is not None:
                if self.is_toc_para(k):
                    end = i; self.toc_ids.add(id(k))
                    for fc in k.iter(q("fldChar")):
                        t = fc.get(q("fldCharType"))
                        if t == "begin": open_fld += 1
                        elif t == "end": open_fld -= 1
                    continue
                if not txt: continue
                if i > end + 2: break  # 连续两段以上非目录内容即结束
        if start is None: return None
        return (start, end)

    def do_page_numbers(self, body, items):
        N = self.R.get("页码", {})
        if not N.get("启用", True): return
        kids = list(body)
        mode = N.get("起始位置", "目录后")
        body_start = 0
        if mode == "目录后" and self.toc_range:
            body_start = self.toc_range[1] + 1
        elif mode in ("目录后", "封面后"):
            for i, k in enumerate(kids):
                if k.tag == q("p") and k.find("w:pPr/w:sectPr", NS) is not None:
                    body_start = i + 1; break
            if mode == "目录后" and body_start == 0: self.note("页码：未找到目录，从首节起编号")
        # 跳过目录后的空段/分页段；遇到带分节符的空段则越过它（它是前置节的结尾）
        has_break = False
        while body_start < len(kids) and kids[body_start].tag == q("p") and not para_text(kids[body_start]).strip():
            if kids[body_start].find("w:pPr/w:sectPr", NS) is not None: has_break = True
            body_start += 1
        if body_start >= len(kids): return
        bs_el = kids[body_start]
        # 正文起始处若无分节：在其前插入带 sectPr 的空段（复制正文末节设置，nextPage）
        if body_start > 0:
            prev = kids[body_start - 1]
            has_break = has_break or (prev.tag == q("p") and prev.find("w:pPr/w:sectPr", NS) is not None)
            if not has_break:
                final = body.find("w:sectPr", NS)
                newp = ET.Element(q("p")); pp = ET.SubElement(newp, q("pPr"))
                sp = copy.deepcopy(final) if final is not None else ET.Element(q("sectPr"))
                for t in ("headerReference", "footerReference", "pgNumType", "titlePg"): remove(sp, t)
                ty = child(sp, "type", create=True, before=["pgSz"]); set_attr(ty, "val", "nextPage")
                pp.append(sp)
                body.insert(list(body).index(kids[body_start]), newp)
                self.note("页码：正文前插入分节符")
        # 建立页脚部件
        fid = self._add_footer_part(items, N)
        # 遍历各节：正文起始之前的节清除页脚引用；正文各节挂页脚，首节从 1 起
        kids = list(body)
        first_body_sect = True
        sect_elems = []
        for i, k in enumerate(kids):
            if k.tag == q("p"):
                sp = k.find("w:pPr/w:sectPr", NS)
                if sp is not None: sect_elems.append((i, sp))
        final = body.find("w:sectPr", NS)
        if final is not None: sect_elems.append((len(kids), final))
        bs_idx = list(body).index(bs_el)
        for i, sp in sect_elems:
            in_front = i < bs_idx
            remove(sp, "footerReference")
            pn = sp.find("w:pgNumType", NS)
            if in_front:
                continue
            for typ in ("default", "first", "even"):
                fr = ET.Element(q("footerReference")); set_attr(fr, "type", typ)
                fr.set("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id", fid)
                sp.insert(0, fr)
            if pn is None:
                pn = child(sp, "pgNumType", create=True, before=["formProt", "vAlign", "noEndnote", "titlePg", "textDirection", "bidi", "rtlGutter", "docGrid", "printerSettings"])
            if first_body_sect:
                set_attr(pn, "start", 1); first_body_sect = False
            elif q("start") in pn.attrib:
                del pn.attrib[q("start")]
            set_attr(pn, "fmt", "decimal")
            reorder(sp, SECT_ORDER)
            self.note("页码：挂接页脚的节数")

    def _add_footer_part(self, items, N):
        font = N.get("字体", "宋体")
        size = size_pt(N.get("字号", 10.5), 10.5)
        jc = {"底部居中": "center", "底部右侧": "right", "底部左侧": "left"}.get(N.get("位置", "底部居中"), "center")
        legacy = {"1": ("", ""), "- 1 -": ("- ", " -"), "第 1 页": ("第 ", " 页")}
        pre, post = legacy.get(N.get("格式", "1"), ("", ""))
        pre, post = N.get("左侧字符", pre), N.get("右侧字符", post)
        footer = ET.Element(q("ftr"))
        p = ET.SubElement(footer, q("p")); pp = ET.SubElement(p, q("pPr"))
        ET.SubElement(pp, q("pStyle"), {q("val"): "Footer"})
        ET.SubElement(pp, q("jc"), {q("val"): jc})
        def run(tag, text=None, attrs=None):
            r = ET.SubElement(p, q("r")); rp = ET.SubElement(r, q("rPr"))
            fonts = {q(k): font for k in ("ascii", "hAnsi", "cs", "eastAsia")}
            if not N.get("统一字体", True): fonts[q("eastAsia")] = N.get("中文字体", "宋体")
            ET.SubElement(rp, q("rFonts"), fonts)
            ET.SubElement(rp, q("spacing"), {q("val"): str(round(float(N.get("字间距", 0)) * 20))})
            for k in ("sz", "szCs"):
                ET.SubElement(rp, q(k), {q("val"): str(round(size * 2))})
            el = ET.SubElement(r, q(tag), attrs or {})
            if text is not None:
                el.text = text
                el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        if pre: run("t", pre)
        run("fldChar", attrs={q("fldCharType"): "begin"})
        run("instrText", " PAGE ")
        run("fldChar", attrs={q("fldCharType"): "separate"})
        run("t", "1")
        run("fldChar", attrs={q("fldCharType"): "end"})
        if post: run("t", post)
        xml = ET.tostring(footer, encoding="unicode")
        n = 1
        while "word/footer%d.xml" % n in items: n += 1
        part = "word/footer%d.xml" % n
        items[part] = xml.encode("utf-8")
        rels = items["word/_rels/document.xml.rels"].decode("utf-8")
        rid = "rIdFooterPN%d" % n
        rels = rels.replace("</Relationships>", '<Relationship Id="%s" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer%d.xml"/></Relationships>' % (rid, n))
        items["word/_rels/document.xml.rels"] = rels.encode("utf-8")
        ct = items["[Content_Types].xml"].decode("utf-8")
        if ("/word/footer%d.xml" % n) not in ct:
            ct = ct.replace("</Types>", '<Override PartName="/word/footer%d.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/></Types>' % n)
            items["[Content_Types].xml"] = ct.encode("utf-8")
        return rid

    def make_caption_para(self, body, ref, before=True, keep_next=None):
        C, F = self.R["题注"], self.R["字体"]
        if keep_next is None: keep_next = before
        newp = ET.Element(q("p"))
        idx = list(body).index(ref)
        body.insert(idx if before else idx + 1, newp)
        r = ET.SubElement(newp, q("r")); ET.SubElement(r, q("t")).text = ""
        self.para_reset(newp, "Caption", keep_next=keep_next)
        self.clean_runs(newp, C["字号"], F["题注"], keep_bi=False)
        return newp

    # ---------- 题注写 SEQ 域
    def write_caption(self, p, prefix, num, title, use_seq):
        sep = self.R["题注"]["编号与题名分隔"]
        r0 = set_para_text(p, "")
        rp0 = r0.find("w:rPr", NS)
        p.remove(r0)
        def mk_run(text=None, fld=None, instr=None):
            r = ET.Element(q("r"))
            if rp0 is not None: r.append(copy.deepcopy(rp0))
            if fld:
                f = ET.SubElement(r, q("fldChar")); set_attr(f, "fldCharType", fld)
            elif instr is not None:
                it = ET.SubElement(r, q("instrText")); it.text = instr
                it.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            else:
                t = ET.SubElement(r, q("t")); t.text = text
                t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            return r
        seq = []
        seq.append(mk_run(prefix))
        if use_seq:
            seq += [mk_run(fld="begin"), mk_run(instr=" SEQ %s \\* ARABIC " % prefix), mk_run(fld="separate"),
                    mk_run(str(num)), mk_run(fld="end")]
        else:
            seq.append(mk_run(str(num)))
        seq.append(mk_run(sep + title if title else ""))
        for r in seq: p.append(r)

    # ---------- 主流程
    def process_body(self, body):
        F, B, C, T = self.R["字体"], self.R["正文"], self.R["题注"], self.R["表格"]
        kids = list(body)
        self.toc_range = self.find_toc(kids)
        # 封面判定：首个 sectPr 段落之前、且其中无标题 → 视为封面
        cover_end = -1
        if self.R["封面"]["启用"]:
            for i, k in enumerate(kids):
                if k.tag == q("p") and k.find("w:pPr/w:sectPr", NS) is not None:
                    cover_end = i; break
                if k.tag == q("tbl"): break
            if cover_end >= 0 and self.toc_range and self.toc_range[0] <= cover_end:
                cover_end = self.toc_range[0] - 1  # 封面与目录同节：封面到目录标题之前为止
            if cover_end >= 0:
                cover = [k for k in kids[:cover_end + 1] if k.tag == q("p")]
                nonempty = [p for p in cover if para_text(p).strip()]
                if len(nonempty) == 0 or len(nonempty) > 8 or any(self.classify(p, None, False, False).startswith("h") for p in nonempty):
                    cover_end = -1
                else:
                    cv = self.R["封面"]
                    title = nonempty[0]
                    self.para_reset(title, "CoverTitle")
                    self.clean_runs(title, cv["标题"]["字号"], F["封面标题"])
                    for p in nonempty[1:]:
                        self.para_reset(p, "CoverInfo")
                        self.clean_runs(p, cv["落款"]["字号"], F["封面落款"])
                    for p in cover:
                        if not para_text(p).strip():
                            self.para_reset(p, "CoverInfo"); self.clean_runs(p, cv["落款"]["字号"], F["封面落款"])
                    self.note("封面段数", len(cover))

        counters = [0] * 9
        fig_n = tab_n = 0
        fig_map = {}; tab_map = {}
        H = self.R["标题"]
        fmt = {k: H[k]["格式"] for k in LEVEL_KEYS}
        body_paras = []
        prev_img = False
        last_cls = ""
        for i, k in enumerate(kids):
            if i <= cover_end: continue
            if k.tag == q("tbl"):
                if C["启用"] and C.get("缺失时自动补编号", True) and last_cls not in ("tabcap", "tabcap_auto"):
                    tab_n += 1
                    newp = self.make_caption_para(body, k, before=True)
                    self.write_caption(newp, C["表前缀"], tab_n, C.get("补充题名占位", ""), C["使用SEQ域"])
                    self.note("自动插入表题注数"); self.auto_caps.append("表 %d：无题注行，已插入编号（题名待补）" % tab_n)
                self.do_table(k); prev_img = False; last_cls = "tbl"; continue
            if k.tag != q("p"): continue
            p = k
            next_tbl = (i + 1 < len(kids) and kids[i + 1].tag == q("tbl"))
            cls = self.classify(p, None, next_tbl, prev_img)
            txt = para_text(p).strip()
            # 图后紧跟的不是题注 → 插入题注
            if prev_img and cls not in ("figcap", "figcap_auto", "empty") and C["启用"] and C.get("缺失时自动补编号", True):
                fig_n += 1
                newp = self.make_caption_para(body, p, before=True, keep_next=False)
                self.write_caption(newp, C["图前缀"], fig_n, C.get("补充题名占位", ""), C["使用SEQ域"])
                self.note("自动插入图题注数"); self.auto_caps.append("图 %d：无题注行，已插入编号（题名待补）" % fig_n)
                prev_img = False
            last_cls = cls
            if cls == "keep":
                last_cls = cls; prev_img = False; continue  # 目录标题与目录条目原样保留
            if cls == "empty":
                self.para_reset(p, "Normal"); self.clean_runs(p, B["字号"], F["正文"])
                continue  # 空段不改变 prev_img，允许图与题注之间有空行
            if cls == "figure":
                self.para_reset(p, "Figure", keep_next=True)
                prev_img = True; self.note("图片段数"); continue
            if cls in ("figcap", "tabcap", "figcap_auto", "tabcap_auto"):
                is_fig = cls.startswith("figcap")
                if cls.endswith("_auto"):
                    old = ""; title = txt
                    self.note("自动补图题注数" if is_fig else "自动补表题注数")
                    self.auto_caps.append("%s题注补编号：「%s」" % ("图" if is_fig else "表", txt[:40]))
                else:
                    m = (self.RE_FIG if is_fig else self.RE_TAB).match(txt)
                    old = re.sub(r"[^\d０-９\-－—.]", "", m.group(0)).translate(str.maketrans("０１２３４５６７８９－—", "0123456789--"))
                    title = txt[m.end():].strip()
                if is_fig: fig_n += 1; n = fig_n
                else: tab_n += 1; n = tab_n
                if old:
                    (fig_map if is_fig else tab_map)[old] = n
                if C["启用"]:
                    self.para_reset(p, "Caption", keep_next=not is_fig)
                    self.clean_runs(p, C["字号"], F["题注"], keep_bi=False)
                    self.write_caption(p, C["图前缀"] if is_fig else C["表前缀"], n, title, C["使用SEQ域"])
                    self.punct(p, "题注")
                    self.note("图题注数" if is_fig else "表题注数")
                prev_img = False; continue
            if cls.startswith("h"):
                lvl = int(cls[1])
                counters[lvl - 1] += 1
                for j in range(lvl, 9): counters[j] = 0
                # 去掉旧编号，重排
                if H["重新编号"]:
                    stripped = re.sub(r"^\s*(?:第?[一二三四五六七八九十]{1,3}[、．.，,：:章节部分篇]|[（(][一二三四五六七八九十]{1,3}[）)]|\d{1,2}(?:[.．]\d{1,2}){1,8}[．.、,，：:]?|\d{1,2}[．.、,，：:)）]|[（(]\d{1,2}[）)]|[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]|[a-zA-Z][.．、)）])\s*", "", txt)
                    key = LEVEL_KEYS[lvl - 1]
                    f = fmt[key]
                    if H.get("编号方式", "自动编号") == "自动编号":
                        label = ""  # 由样式关联的多级自动编号出号
                        if stripped != txt: self.note("标题清除手打编号数")
                    else:
                        c = counters[lvl - 1]
                        if f == "汉字顿号": label = cn(c) + "、"
                        elif f == "第X章": label = "第%s章" % cn(c)
                        elif f == "括号汉字": label = "（%s）" % cn(c)
                        elif f == "数字点": label = "%d." % c
                        elif f == "括号数字": label = "（%d）" % c
                        elif f == "圈数字": label = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"[min(c, 20) - 1]
                        elif f == "字母点": label = "%s." % chr(96 + min(c, 26))
                        elif f == "多级数字":
                            b = lvl
                            while b > 1 and fmt[LEVEL_KEYS[b - 2]] in ("数字点", "多级数字"): b -= 1
                            label = ".".join(str(max(1, counters[j - 1])) for j in range(b, lvl + 1))
                        else: label = ""
                    new = label + stripped
                    if new != txt:
                        set_para_text(p, new)
                self.para_reset(p, "Heading%d" % lvl)
                self.clean_runs(p, H[LEVEL_KEYS[lvl - 1]]["字号"], F[LEVEL_KEYS[lvl - 1] + "标题"], keep_bi=False)
                self.punct(p, "标题")
                self.note("标题段数")
                prev_img = False; continue
            # 正文
            self.para_reset(p, "Normal")
            if B["清除直接字体格式"]:
                self.clean_runs(p, B["字号"], F["正文"], keep_bi=B["保留加粗斜体下划线"])
            self.punct(p, "正文")
            self.bracket_font(p)
            body_paras.append(p)
            self.note("正文段数")
            prev_img = False
        # 正文引用同步
        if C["同步正文引用"] and (fig_map or tab_map):
            self.sync_refs(body_paras, fig_map, tab_map, C)

    def sync_refs(self, paras, fig_map, tab_map, C):
        def build(prefix, mp):
            mp = {k: v for k, v in mp.items() if k and k != str(v)}
            if not mp: return None
            pat = re.compile(r"%s\s*(%s)(?![\d\-.])" % (prefix, "|".join(sorted(map(re.escape, mp), key=len, reverse=True))))
            return pat, mp
        jobs = [j for j in (build(C["图前缀"], fig_map), build(C["表前缀"], tab_map)) if j]
        if not jobs: return
        n = 0
        for p in paras:
            for t in p.iter(q("t")):
                s = t.text or ""
                for pat, mp in jobs:
                    s2 = pat.sub(lambda m: m.group(0)[:m.start(1) - m.start(0)] + str(mp[m.group(1)]), s)
                    if s2 != s: n += 1; s = s2
                t.text = s
        if n: self.note("正文引用同步处数", n)

    def do_table(self, tbl):
        T, F = self.R["表格"], self.R["字体"]
        tp = child(tbl, "tblPr", create=True)
        if T["表格居中"]:
            j = child(tp, "jc", create=True, before=["tblCellSpacing","tblInd","tblBorders","shd","tblLayout","tblCellMar","tblLook","tblCaption","tblDescription"])
            set_attr(j, "val", "center")
        rows = tbl.findall("w:tr", NS)
        for ri, tr in enumerate(rows):
            for tc in tr.findall("w:tc", NS):
                for p in tc.findall("w:p", NS):
                    self.para_reset(p, "TableText")
                    self.clean_runs(p, T["字号"], F["表格"])
                    self.punct(p, "表格")
                    if ri == 0 and T["首行加粗"]:
                        for r in runs(p): set_bold(rpr(r), True); reorder(rpr(r), RPR_ORDER)
        if T.get("序号列自动编号", True): self.number_serial_column(tbl, rows, T)
        self.note("表格数")

    def number_serial_column(self, tbl, rows, T):
        """表头含「序号」类列名时，把该列数据行从 1 起连续编号（空单元格补齐，纯数字单元格重排，含其他文字的不动）。"""
        if len(rows) < 2: return
        heads = [h.strip() for h in T.get("序号列标题", ["序号", "编号", "序", "No.", "NO", "No"])]
        def cells_with_col(tr):
            """返回 [(tc, 起始列号)]，按 gridSpan 计算列位置。"""
            out = []; col = 0
            for tc in tr.findall("w:tc", NS):
                span = tc.find("w:tcPr/w:gridSpan", NS)
                n = int(span.get(q("val"))) if span is not None else 1
                out.append((tc, col)); col += n
            return out
        target = None; head_rows = 0
        for hr in rows[:2]:  # 表头可能占两行
            for tc, col in cells_with_col(hr):
                txt = "".join(t.text or "" for t in tc.iter(q("t"))).strip()
                if txt.replace(" ", "") in heads:
                    target = col; break
            head_rows += 1
            if target is not None: break
        if target is None: return
        n = 0; changed = 0
        for tr in rows[head_rows:]:
            cell = None
            for tc, col in cells_with_col(tr):
                if col == target: cell = tc; break
            if cell is None: continue
            vm = cell.find("w:tcPr/w:vMerge", NS)
            if vm is not None and vm.get(q("val"), "continue") != "restart": continue  # 纵向合并的续行不编号
            txt = "".join(t.text or "" for t in cell.iter(q("t"))).strip()
            if txt and not re.fullmatch(r"[0-9０-９]+[.．、]?", txt): continue  # 含其他文字，跳过
            n += 1
            if txt != str(n):
                ps = cell.findall("w:p", NS)
                p = ps[0] if ps else ET.SubElement(cell, q("p"))
                for extra in ps[1:]: cell.remove(extra)
                set_para_text(p, str(n)); self.para_reset(p, "TableText"); self.clean_runs(p, T["字号"], self.R["字体"]["表格"])
                changed += 1
        if changed:
            self.note("表格序号补齐处数", changed)
            self.auto_caps.append("表格序号列：补齐/重排 %d 处（共 %d 行）" % (changed, n))

# ---------------------------------------------------------------- 入口
def convert_to_docx(src):
    """.doc → .docx：优先本机 Word，其次 WPS，最后 LibreOffice。返回新文件路径或 None。"""
    import subprocess, tempfile
    out = os.path.splitext(src)[0] + ".docx"
    if os.path.exists(out):
        return out
    if sys.platform.startswith("win"):
        vbs = paths.helper("doc转docx.vbs")
        if os.path.exists(vbs):
            try:
                r = subprocess.run(["cscript", "//nologo", vbs, "/q", src], capture_output=True, timeout=300)
                if os.path.exists(out): return out
                print((r.stdout or b"").decode(errors="replace").strip())
            except Exception as e:
                print("Word/WPS 转换失败：%s" % e)
    for exe in ("soffice", "libreoffice", "/opt/libreoffice/program/soffice", r"C:\\Program Files\\LibreOffice\\program\\soffice.exe"):
        try:
            subprocess.run([exe, "--headless", "--convert-to", "docx", "--outdir", os.path.dirname(src), src], capture_output=True, timeout=300)
            if os.path.exists(out): return out
        except Exception:
            continue
    return None

def fix_console():
    """Windows 控制台由 Python 以 Unicode 直接写入，不能改编码；仅在输出被重定向到文件/管道时按系统代码页转码。"""
    import locale
    for st in (sys.stdout, sys.stderr):
        try:
            if st is None: continue
            if st.isatty(): st.reconfigure(errors="replace")
            else: st.reconfigure(encoding=locale.getpreferredencoding(False) or "utf-8", errors="replace")
        except Exception:
            pass

def load_rules():
    path = paths.rules_path()
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def process_file(src, rules):
    src = os.path.abspath(src)
    base, ext = os.path.splitext(src)
    if ext.lower() in (".doc", ".wps", ".rtf"):
        conv = convert_to_docx(src)
        if conv is None:
            return None, "无法把 %s 转为 .docx：本机未检测到 Word／WPS，请先在 Word 中另存为 .docx" % os.path.basename(src)
        print("已转换：%s → %s" % (os.path.basename(src), os.path.basename(conv)))
        src = conv; base, ext = os.path.splitext(src)
    if ext.lower() != ".docx":
        return None, "仅支持 .doc／.docx"
    dst = base + rules["输出"]["后缀"] + ".docx"
    rules = normalize_rules(json.loads(json.dumps(rules)))
    fm = Formatter(rules)
    global KEEP_ORIGINAL_FONTS
    KEEP_ORIGINAL_FONTS = rules.get("字体", {}).get("模式", "模板") == "原文档"
    with zipfile.ZipFile(src) as zin:
        items = {i.filename: zin.read(i.filename) for i in zin.infolist()}
        infos = zin.infolist()
    doc_root, doc_tag = parse_keep_ns(items["word/document.xml"])
    sty_root, sty_tag = parse_keep_ns(items["word/styles.xml"])
    body = doc_root.find("w:body", NS)
    fm.do_styles(sty_root)
    fm.do_sections(body)
    fm.process_body(body)
    fm.do_page_numbers(body, items)
    items["word/document.xml"] = serialize(doc_root, doc_tag)
    sty_bytes = serialize(sty_root, sty_tag)
    if b"__HEADNUM__" in sty_bytes:
        num_id = ensure_heading_numbering(items, rules["标题"], fm.sid)
        sty_bytes = sty_bytes.replace(b"__HEADNUM__", str(num_id).encode())
        fm.stats["标题自动编号"] = "已关联样式（列表 %d）" % num_id
    items["word/styles.xml"] = sty_bytes
    # ---- 字体嵌入
    font_log = []; embedded = []; missing = []
    E = rules.get("字体嵌入", {"启用": False})
    if E.get("启用"):
        used = set()
        def fonts_in(xml):
            out = set()
            for m in re.finditer(r"<w:rFonts\b[^>]*>", xml):
                for a in re.findall(r'w:(?:eastAsia|ascii|hAnsi|cs)="([^"]+)"', m.group(0)): out.add(a)
            return out
        doc_xml = items["word/document.xml"].decode("utf-8")
        used |= fonts_in(doc_xml)
        for part in items:
            if re.match(r"word/(header|footer)\d*\.xml$", part): used |= fonts_in(items[part].decode("utf-8"))
        # 样式表：只算文档实际用到的样式及默认样式
        sty_xml = items["word/styles.xml"].decode("utf-8")
        used_sids = set(re.findall(r'<w:(?:pStyle|rStyle|tblStyle) w:val="([^"]+)"', doc_xml)) | set(fm.sid.values())
        m = re.search(r"<w:docDefaults>.*?</w:docDefaults>", sty_xml, re.S)
        if m: used |= fonts_in(m.group(0))
        for m in re.finditer(r'<w:style\b[^>]*w:styleId="([^"]+)"[^>]*>.*?</w:style>', sty_xml, re.S):
            if m.group(1) in used_sids or 'w:default="1"' in m.group(0)[:200]: used |= fonts_in(m.group(0))
        skip = {x.lower() for x in E.get("不嵌入", [])}
        used = {u for u in used if u.lower() not in skip and not u.startswith("major") and not u.startswith("minor")}
        dirs = paths.font_dirs(E.get("字体目录", ["字体"]))
        embedded, missing = fontembed.embed_fonts(items, used, dirs, font_log)
        fm.stats["嵌入字体数"] = len([e for e in embedded if "原已嵌入" not in e])
        if missing: fm.stats["未找到字体文件数"] = len(missing)
    names = [i.filename for i in infos] + [k for k in items if k not in {i.filename for i in infos}]
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in names:
            zout.writestr(name, items[name])
    rep = None
    if rules["输出"]["生成报告"]:
        rep = base + "_整理报告.txt"
        lines = ["文档格式整理报告", "源文件：" + os.path.basename(src), "输出：" + os.path.basename(dst), ""]
        for k, v in fm.stats.items(): lines.append("%s：%s" % (k, v))
        if E.get("启用"):
            lines += ["", "【字体嵌入】"] + (font_log or ["（无新增嵌入）"])
            if embedded: lines.append("已嵌入：" + "、".join(embedded))
            if missing:
                lines.append("未找到字体文件（未嵌入）：" + "、".join(missing))
                lines.append("  处理办法：从装有该字体的电脑复制 C:\\Windows\\Fonts 下对应的 .ttf/.ttc 文件到工具的 fonts 文件夹后重新运行。")
        if fm.auto_caps:
            lines += ["", "【自动补编号清单】（题注请补齐题名）"] + fm.auto_caps
        if fm.punct_log:
            lines += ["", "【标点修订清单】（共 %d 处%s）" % (fm.stats.get("标点修订处数", 0), "，仅列前 300 处" if len(fm.punct_log) >= 300 else "")] + fm.punct_log
        lines += ["", "说明：题注已写入 SEQ 域并缓存编号；如需刷新交叉引用，在 Word 中全选后按 F9。",
                  "封面/标题/题注的识别基于文本规律，请复核报告中的数量是否与预期一致。"]
        with open(rep, "w", encoding="utf-8") as f: f.write("\n".join(lines))
    return dst, rep

def main():
    fix_console()
    args = sys.argv[1:]
    if not args:
        print("用法：把 .docx 文件拖到「整理.bat」上，或运行 python docx_fmt.py 文件.docx"); return 1
    rules = load_rules()
    ok = 0
    for a in args:
        try:
            dst, rep = process_file(a, rules)
            if dst is None: print("跳过：%s —— %s" % (a, rep)); continue
            print("完成：%s\n  → %s" % (os.path.basename(a), dst)); ok += 1
        except Exception as e:
            import traceback, datetime
            tb = traceback.format_exc()
            print(tb); print("失败：%s —— %s" % (a, e))
            try:
                with open(paths.log_path("run_log.txt"), "a", encoding="utf-8") as lf:
                    lf.write("[%s] %s\n%s\n" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), a, tb))
            except Exception:
                pass
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
