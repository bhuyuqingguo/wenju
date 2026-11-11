# -*- coding: utf-8 -*-
"""
infer.py —— 反向识别：读取一份已排版的 docx，推断其版式参数，生成规则（预设）。
识别项：页面、正文、各级标题（格式/字体/字号/行距/段前后/缩进）、题注、表格文字、封面、页码位置。
纯标准库。用法：python infer.py 文件.docx  → 输出 JSON 到 stdout；或由 ui.py 调用。
"""
import sys, os, re, json, zipfile, copy
from collections import Counter
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import docx_fmt as D
W = D.W; NS = D.NS; q = D.q

SIZE_BY_PT = {v: k for k, v in D.SIZE_NAMES.items()}
def pt_name(pt):
    if pt is None: return None
    pt = round(float(pt) * 2) / 2
    return SIZE_BY_PT.get(pt, pt)

# ---------------------------------------------------------------- 样式链与有效属性
class Styles:
    def __init__(self, root):
        self.by_id = {}
        self.default_p = None
        for st in root.findall("w:style", NS):
            sid = st.get(q("styleId")); typ = st.get(q("type"), "paragraph")
            based = st.find("w:basedOn", NS)
            self.by_id[sid] = {"type": typ, "based": based.get(q("val")) if based is not None else None,
                               "pPr": st.find("w:pPr", NS), "rPr": st.find("w:rPr", NS),
                               "name": (st.find("w:name", NS).get(q("val")) if st.find("w:name", NS) is not None else sid)}
            if typ == "paragraph" and st.get(q("default")) in ("1", "true"): self.default_p = sid
        dd = root.find("w:docDefaults", NS)
        self.def_rpr = dd.find("w:rPrDefault/w:rPr", NS) if dd is not None else None
        self.def_ppr = dd.find("w:pPrDefault/w:pPr", NS) if dd is not None else None

    def chain(self, sid):
        out = []; seen = set()
        while sid and sid in self.by_id and sid not in seen:
            seen.add(sid); out.append(self.by_id[sid]); sid = self.by_id[sid]["based"]
        return list(reversed(out))  # 从根到叶

def merge_rpr(dst, rp):
    if rp is None: return
    f = rp.find("w:rFonts", NS)
    if f is not None:
        for a in ("eastAsia", "ascii", "hAnsi"):
            v = f.get(q(a))
            if v: dst[a] = v.split(";")[0].strip()
    sz = rp.find("w:sz", NS)
    if sz is not None and sz.get(q("val")): dst["sz"] = int(sz.get(q("val"))) / 2
    b = rp.find("w:b", NS)
    if b is not None: dst["b"] = b.get(q("val"), "1") not in ("0", "false")

def merge_ppr(dst, pp):
    if pp is None: return
    sp = pp.find("w:spacing", NS)
    if sp is not None:
        for a in ("line", "lineRule", "before", "after"):
            v = sp.get(q(a))
            if v is not None: dst[a] = v
    ind = pp.find("w:ind", NS)
    if ind is not None:
        for a in ("firstLineChars", "firstLine", "leftChars", "left", "rightChars", "right", "hanging", "hangingChars"):
            v = ind.get(q(a))
            if v is not None: dst[a] = v
    jc = pp.find("w:jc", NS)
    if jc is not None: dst["jc"] = jc.get(q("val"))
    ol = pp.find("w:outlineLvl", NS)
    if ol is not None: dst["outline"] = int(ol.get(q("val")))
    np_ = pp.find("w:numPr", NS)
    if np_ is not None: dst["num"] = True

def effective(styles, p):
    """段落有效格式：docDefaults → 样式链 → 段落直接 pPr/rPr → 首个有文字 run 的 rPr。"""
    r = {}; pp = {}
    merge_rpr(r, styles.def_rpr); merge_ppr(pp, styles.def_ppr)
    sid = D.style_id(p) or styles.default_p
    for st in styles.chain(sid):
        merge_rpr(r, st["rPr"]); merge_ppr(pp, st["pPr"])
    ppr = p.find("w:pPr", NS)
    if ppr is not None:
        merge_ppr(pp, ppr); merge_rpr(r, ppr.find("w:rPr", NS))
    # 取文字最多的 run 作为代表
    best = None; best_len = -1
    for run in p.iter(q("r")):
        t = "".join(x.text or "" for x in run.findall("w:t", NS))
        if len(t.strip()) > best_len:
            best_len = len(t.strip()); best = run
    if best is not None:
        rr = dict(r); merge_rpr(rr, best.find("w:rPr", NS)); r = rr
    return r, pp, sid

def para_fmt(r, pp):
    """转成规则里的段落格式字典。"""
    out = {}
    if r.get("sz"): out["字号"] = pt_name(r["sz"])
    out["加粗"] = bool(r.get("b", False))
    out["对齐"] = pp.get("jc", "both") if pp.get("jc") in ("both", "left", "center", "right") else "both"
    line = pp.get("line"); rule = pp.get("lineRule", "auto")
    if line:
        if rule == "exact": out["行距类型"], out["行距值"] = "固定值", int(line) / 20
        elif rule == "atLeast": out["行距类型"], out["行距值"] = "最小值", int(line) / 20
        else:
            mult = int(line) / 240
            out["行距类型"], out["行距值"] = ("单倍", 1) if abs(mult - 1) < 0.05 else ("多倍", round(mult, 2))
    else:
        out["行距类型"], out["行距值"] = "单倍", 1
    out["段前"] = int(pp.get("before", 0)) / 20
    out["段后"] = int(pp.get("after", 0)) / 20
    size = float(r.get("sz") or 12)
    def chars(chars_key, twip_key):
        if pp.get(chars_key) is not None: return round(int(pp[chars_key]) / 100, 1)
        if pp.get(twip_key) is not None: return round(int(pp[twip_key]) / 20 / size, 1)
        return 0
    fc = chars("firstLineChars", "firstLine")
    hc = chars("hangingChars", "hanging")
    out["首行缩进字符"] = -hc if hc else fc
    out["左缩进字符"] = chars("leftChars", "left")
    out["右缩进字符"] = chars("rightChars", "right")
    return out

# ---------------------------------------------------------------- 主识别
def infer(path, base_rules=None):
    with zipfile.ZipFile(path) as z:
        items = {i.filename: z.read(i.filename) for i in z.infolist()}
    doc = ET.fromstring(items["word/document.xml"]); sty = ET.fromstring(items["word/styles.xml"])
    styles = Styles(sty)
    body = doc.find("w:body", NS)
    R = copy.deepcopy(base_rules) if base_rules else D.normalize_rules(json.load(open(__import__("paths").rules_path(), encoding="utf-8")))
    R = D.normalize_rules(R)
    R["标题"]["级数"] = 9  # 识别阶段允许全部 9 级，识别后按实际最大级别收敛
    notes = []

    # ---- 页面
    sects = list(body.iter(q("sectPr")))
    if sects:
        sp = sects[-1]
        sz = sp.find("w:pgSz", NS); mar = sp.find("w:pgMar", NS)
        if mar is not None:
            for k, a in (("上边距", "top"), ("下边距", "bottom"), ("左边距", "left"), ("右边距", "right"), ("页眉距", "header"), ("页脚距", "footer")):
                v = mar.get(q(a))
                if v: R["页面"][k] = round(abs(int(v)) / 1440 * 2.54, 2)
        notes.append("页面：页边距取自末节")

    # ---- 分类段落
    fm = D.Formatter(R)
    fm.sid = {}
    for k in range(1, 10):
        for sid, st in styles.by_id.items():
            if st["type"] == "paragraph" and st["name"].lower() == "heading %d" % k: fm.sid["Heading%d" % k] = sid
    kids = list(body)
    fm.toc_range = fm.find_toc(kids)
    buckets = {"body": [], "figcap": [], "tabcap": [], "cover": []}
    heads = {}
    prev_img = False
    # 封面候选：首个 sectPr 之前
    cover_end = -1
    for i, k in enumerate(kids):
        if k.tag == q("p") and k.find("w:pPr/w:sectPr", NS) is not None: cover_end = i; break
        if k.tag == q("tbl"): break
    if fm.toc_range and fm.toc_range[0] <= cover_end: cover_end = fm.toc_range[0] - 1
    first_table_cell = None
    for i, k in enumerate(kids):
        if k.tag == q("tbl"):
            if first_table_cell is None:
                rows = k.findall("w:tr", NS)
                for tr in rows[1:] + rows[:1]:
                    for tc in tr.findall("w:tc", NS):
                        for pp_ in tc.findall("w:p", NS):
                            if D.para_text(pp_).strip(): first_table_cell = pp_; break
                        if first_table_cell is not None: break
                    if first_table_cell is not None: break
            prev_img = False; continue
        if k.tag != q("p"): continue
        txt = D.para_text(k).strip()
        if not txt and not D.has_image(k): continue
        next_tbl = i + 1 < len(kids) and kids[i + 1].tag == q("tbl")
        cls = fm.classify(k, None, next_tbl, prev_img)
        if cls == "figure": prev_img = True; continue
        if i <= cover_end and not cls.startswith("h"): buckets["cover"].append(k); prev_img = False; continue
        if cls in ("figcap", "figcap_auto"): buckets["figcap"].append(k)
        elif cls in ("tabcap", "tabcap_auto"): buckets["tabcap"].append(k)
        elif cls.startswith("h"): heads.setdefault(int(cls[1]), []).append(k)
        elif cls == "body" and len(txt) > 8: buckets["body"].append(k)
        prev_img = False

    def dominant(paras):
        """多段落取众数格式。"""
        if not paras: return None, None
        votes = Counter(); samples = {}
        for p in paras:
            r, pp, sid = effective(styles, p)
            key = json.dumps({"f": r.get("eastAsia"), "sz": r.get("sz"), "line": pp.get("line"), "rule": pp.get("lineRule"), "jc": pp.get("jc"), "b": r.get("b")}, sort_keys=True)
            votes[key] += 1; samples.setdefault(key, (r, pp))
        key = votes.most_common(1)[0][0]
        return samples[key]

    # ---- 正文
    r, pp = dominant(buckets["body"])
    if r:
        R["正文"].update(para_fmt(r, pp))
        if r.get("eastAsia"): R["字体"]["正文"] = r["eastAsia"]
        if r.get("ascii"): R["字体"]["西文"] = r["ascii"]
        notes.append("正文：由 %d 段众数得出（%s %s）" % (len(buckets["body"]), r.get("eastAsia"), R["正文"].get("字号")))
    # ---- 标题
    fmt_of = lambda t: ("第X章" if re.match(r"^\s*第[一二三四五六七八九十]", t) else "汉字顿号" if fm.RE_H1.match(t) else "括号汉字" if fm.RE_H2.match(t)
                        else "多级数字" if fm.RE_H4.match(t) else "括号数字" if fm.RE_HPARENNUM.match(t) else "圈数字" if fm.RE_HCIRCLE.match(t)
                        else "字母点" if fm.RE_HALPHA.match(t) else "数字点" if fm.RE_H3.match(t) else None)
    R["标题"]["级数"] = max(1, min(9, max(heads))) if heads else 4
    if heads:
        for lvl, ps in sorted(heads.items()):
            r, pp = dominant(ps)
            key = D.LEVEL_KEYS[lvl - 1]
            if r:
                R["标题"][key].update(para_fmt(r, pp))
                if r.get("eastAsia"): R["字体"][key + "标题"] = r["eastAsia"]
            fv = Counter(f for f in (fmt_of(D.para_text(p)) for p in ps) if f)
            if fv: R["标题"][key]["格式"] = fv.most_common(1)[0][0]
            notes.append("%s标题：%d 段（%s，%s，格式 %s）" % (key, len(ps), r.get("eastAsia") if r else "-", R["标题"][key].get("字号"), R["标题"][key].get("格式")))
    # ---- 题注
    caps = buckets["figcap"] + buckets["tabcap"]
    r, pp = dominant(caps)
    if r:
        R["题注"].update({k: v for k, v in para_fmt(r, pp).items() if k in ("字号", "加粗", "对齐", "行距类型", "行距值", "段前", "段后")})
        if r.get("eastAsia"): R["字体"]["题注"] = r["eastAsia"]
        notes.append("题注：%d 段" % len(caps))
    # ---- 表格
    if first_table_cell is not None:
        r, pp = effective(styles, first_table_cell)[:2]
        R["表格"].update({k: v for k, v in para_fmt(r, pp).items() if k in ("字号", "对齐", "行距类型", "行距值")})
        if r.get("eastAsia"): R["字体"]["表格"] = r["eastAsia"]
        notes.append("表格：取首张表第二行")
    # ---- 封面
    cov = [p for p in buckets["cover"] if D.para_text(p).strip()]
    if cov:
        r, pp = effective(styles, cov[0])[:2]
        R["封面"]["标题"].update({k: v for k, v in para_fmt(r, pp).items() if k in ("字号", "加粗", "对齐")})
        if r.get("eastAsia"): R["字体"]["封面标题"] = r["eastAsia"]
        if len(cov) > 1:
            r2, pp2 = effective(styles, cov[-1])[:2]
            R["封面"]["落款"].update({k: v for k, v in para_fmt(r2, pp2).items() if k in ("字号", "对齐")})
            if r2.get("eastAsia"): R["字体"]["封面落款"] = r2["eastAsia"]
        notes.append("封面：%d 段（标题 %s %s）" % (len(cov), R["字体"]["封面标题"], R["封面"]["标题"].get("字号")))
    else:
        R["封面"]["启用"] = False; notes.append("封面：未识别到，已关闭")
    # ---- 页码
    has_pn = False
    for name, data in items.items():
        if re.match(r"word/footer\d*\.xml", name) and re.search(r"\bPAGE\b", data.decode("utf-8", "ignore")):
            has_pn = True
            x = data.decode("utf-8", "ignore")
            jc = re.search(r'<w:jc w:val="(\w+)"', x)
            R["页码"]["位置"] = {"center": "底部居中", "right": "底部右侧", "left": "底部左侧", "both": "底部两端对齐"}.get(jc.group(1) if jc else "center", "底部居中")
            f = re.search(r'w:ascii="([^"]+)"', x); s = re.search(r'<w:sz w:val="(\d+)"', x)
            if f: R["页码"]["字体"] = f.group(1)
            if s: R["页码"]["字号"] = pt_name(int(s.group(1)) / 2)
            break
    R["页码"]["启用"] = has_pn
    # Read complete PAGE decoration with XML, including non-w namespace prefixes.
    for name,data in items.items():
        if not re.match(r"word/footer\d*\.xml$",name):continue
        footer=ET.fromstring(data)
        for p in footer.findall('.//w:p',NS):
            children=list(p);start=end=None;format_run=None
            for i,node in enumerate(children):
                if node.tag==q('fldSimple') and re.search(r'\bPAGE\b',node.get(q('instr'),'')):
                    start=end=i;format_run=node.find('w:r',NS);break
                instr=node.find('w:instrText',NS)
                if instr is not None and re.search(r'\bPAGE\b',instr.text or ''):
                    start=i;end=i;format_run=node
                    for j in range(i-1,-1,-1):
                        f=children[j].find('w:fldChar',NS)
                        if f is not None and f.get(q('fldCharType'))=='begin':start=j;break
                    for j in range(i+1,len(children)):
                        f=children[j].find('w:fldChar',NS)
                        if f is not None and f.get(q('fldCharType'))=='end':end=j;break
                    break
            if start is None:continue
            pn=R['页码'];pn['启用']=has_pn=True
            pn['左侧字符']=''.join(t.text or '' for c in children[:start] for t in c.iter(q('t')))
            pn['右侧字符']=''.join(t.text or '' for c in children[end+1:] for t in c.iter(q('t')))
            jc=p.find('w:pPr/w:jc',NS)
            if jc is not None:pn['位置']={'left':'底部左侧','right':'底部右侧','center':'底部居中','both':'底部两端对齐'}.get(jc.get(q('val')),'底部居中')
            rp=format_run.find('w:rPr',NS) if format_run is not None else None
            if rp is not None:
                fonts=rp.find('w:rFonts',NS);size=rp.find('w:sz',NS);spacing=rp.find('w:spacing',NS)
                if fonts is not None:
                    pn['字体']=fonts.get(q('ascii'),pn['字体']);pn['中文字体']=fonts.get(q('eastAsia'),pn.get('中文字体','宋体'))
                    pn['统一字体']=pn['字体']==pn['中文字体']
                if size is not None:pn['字号']=pt_name(int(size.get(q('val')))/2)
                pn['字间距']=int(spacing.get(q('val')))/20 if spacing is not None else 0
            notes.append('页码：已读取左右字符与字符格式；起始位置仍需人工复核')
            break
        if has_pn and '左侧字符' in R['页码']:break
    notes.append("页码：%s" % ("页脚含 PAGE 域，已启用" if has_pn else "未发现页脚页码，已关闭"))
    R["_识别说明"] = "由「%s」反向识别；以下为识别依据，请复核后保存为预设：%s" % (os.path.basename(path), "；".join(notes))
    return R, notes

def main():
    if len(sys.argv) < 2:
        print("用法：python infer.py 文件.docx"); return 1
    R, notes = infer(sys.argv[1])
    print(json.dumps(R, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())
