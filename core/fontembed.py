# -*- coding: utf-8 -*-
"""
fontembed.py —— 字体查找与嵌入（纯标准库）
- 解析 TTF/TTC 的 name 表，得到字体家族名（含中文名与英文名）
- 从 TTC 中抽取单个字面为独立 TTF（Word 只能嵌入单字面）
- 按 OOXML 规范混淆（odttf）并写入 docx：word/fonts/*.odttf、fontTable.xml、rels、[Content_Types].xml、settings.xml
"""
import os, re, struct, uuid, sys

# ---------------------------------------------------------------- TTF 解析
def _read_name_table(data, offset):
    """offset 指向 sfnt 表目录（单字面）。返回 {nameID: set(names)}，并返回表目录列表。"""
    tag, numTables = struct.unpack(">4sH", data[offset:offset + 6])
    tables = {}
    for i in range(numTables):
        rec = offset + 12 + 16 * i
        t, cks, off, ln = struct.unpack(">4sIII", data[rec:rec + 16])
        tables[t] = (off, ln)
    names = {}
    if b"name" in tables:
        off, ln = tables[b"name"]
        fmt, count, strOff = struct.unpack(">HHH", data[off:off + 6])
        for i in range(count):
            r = off + 6 + 12 * i
            pid, eid, lid, nid, l, o = struct.unpack(">HHHHHH", data[r:r + 12])
            raw = data[off + strOff + o: off + strOff + o + l]
            try:
                if pid == 3 or (pid == 0):
                    s = raw.decode("utf-16-be")
                elif pid == 1 and eid == 0:
                    s = raw.decode("mac-roman")
                else:
                    continue
            except Exception:
                continue
            names.setdefault(nid, set()).add(s.strip())
    return names, tables

def font_faces(path):
    """返回 [(faceIndex, {family names}, subfamily, isBold, isItalic)]"""
    with open(path, "rb") as f:
        data = f.read()
    faces = []
    if data[:4] == b"ttcf":
        n = struct.unpack(">I", data[8:12])[0]
        offs = struct.unpack(">%dI" % n, data[12:12 + 4 * n])
    else:
        offs = (0,)
    for idx, off in enumerate(offs):
        try:
            names, _ = _read_name_table(data, off)
        except Exception:
            continue
        fam = set(names.get(1, set())) or set(names.get(16, set()))
        sub = " ".join(sorted(names.get(2, set()))).lower()
        faces.append((idx, fam, sub, "bold" in sub, "italic" in sub or "oblique" in sub))
    return faces

def extract_face(path, index):
    """从 TTF/TTC 中取出第 index 个字面，返回独立 TTF 字节串。"""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"ttcf":
        return data
    n = struct.unpack(">I", data[8:12])[0]
    offs = struct.unpack(">%dI" % n, data[12:12 + 4 * n])
    off = offs[index]
    version = data[off:off + 4]
    numTables = struct.unpack(">H", data[off + 4:off + 6])[0]
    entries = []
    for i in range(numTables):
        rec = off + 12 + 16 * i
        t, cks, toff, ln = struct.unpack(">4sIII", data[rec:rec + 16])
        entries.append((t, cks, toff, ln))
    # 重新排布：表目录 + 各表（4 字节对齐）
    hdr_len = 12 + 16 * numTables
    out = bytearray()
    es = 0
    while (1 << (es + 1)) <= numTables: es += 1
    out += version + struct.pack(">HHHH", numTables, 16 << es, es, numTables * 16 - (16 << es))
    body = bytearray(); dir_ = bytearray()
    cur = hdr_len
    for t, cks, toff, ln in entries:
        blob = data[toff:toff + ln]
        dir_ += struct.pack(">4sIII", t, cks, cur, ln)
        body += blob
        pad = (-ln) % 4
        body += b"\0" * pad
        cur += ln + pad
    return bytes(out + dir_ + body)

# ---------------------------------------------------------------- 字体库索引
def font_dirs(extra_dirs):
    dirs = list(extra_dirs)
    if sys.platform.startswith("win"):
        dirs += [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Microsoft\Windows\Fonts")]
    else:
        dirs += ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts"), os.path.expanduser("~/.local/share/fonts"),
                 "/Library/Fonts", "/System/Library/Fonts"]
    return [d for d in dirs if d and os.path.isdir(d)]

def index_fonts(dirs):
    """{family name(lower): [(path, faceIndex, isBold, isItalic)]}"""
    idx = {}
    for d in dirs:
        for root, _, files in os.walk(d):
            for fn in files:
                if not fn.lower().endswith((".ttf", ".ttc")): continue
                p = os.path.join(root, fn)
                try:
                    for fi, fams, sub, b, i in font_faces(p):
                        for fam in fams:
                            idx.setdefault(fam.lower(), []).append((p, fi, b, i))
                except Exception:
                    continue
    return idx

def find_font(idx, name):
    """返回 {'regular': (path, faceIndex), 'bold': ...} 中存在的项。"""
    cands = idx.get(name.lower(), [])
    res = {}
    for p, fi, b, i in cands:
        key = "regular" if not b and not i else "bold" if b and not i else "italic" if i and not b else "boldItalic"
        res.setdefault(key, (p, fi))
    return res

# ---------------------------------------------------------------- 混淆与写入
def obfuscate(data, guid):
    key = bytes.fromhex(guid.replace("-", ""))[::-1]  # 16 字节，逆序
    d = bytearray(data)
    for i in range(min(32, len(d))):
        d[i] ^= key[i % 16]
    return bytes(d)

REL_FONT = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/font"
CT_ODTTF = "application/vnd.openxmlformats-officedocument.obfuscatedFont"
CT_FONTTABLE = "application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

def embed_fonts(items, font_names, dirs, log):
    """
    items: {zip 内路径: bytes}（就地修改）
    font_names: 需要嵌入的字体名集合
    dirs: 额外字体目录
    返回 (已嵌入列表, 未找到列表)
    """
    idx = index_fonts(font_dirs(dirs))
    ft_path = "word/fontTable.xml"
    ft = items.get(ft_path)
    if ft is None:
        ft = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
              '<w:fonts xmlns:w="%s" xmlns:r="%s"></w:fonts>' % (W_NS, R_NS)).encode("utf-8")
        # document.xml.rels 增加 fontTable 关系
        rels = items["word/_rels/document.xml.rels"].decode("utf-8")
        if "fontTable.xml" not in rels:
            rels = rels.replace("</Relationships>",
                '<Relationship Id="rIdFontTable" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable" Target="fontTable.xml"/></Relationships>')
            items["word/_rels/document.xml.rels"] = rels.encode("utf-8")
        ct = items["[Content_Types].xml"].decode("utf-8")
        if "fontTable" not in ct:
            ct = ct.replace("</Types>", '<Override PartName="/word/fontTable.xml" ContentType="%s"/></Types>' % CT_FONTTABLE)
            items["[Content_Types].xml"] = ct.encode("utf-8")
    ft = ft.decode("utf-8")
    if "xmlns:r=" not in ft:
        ft = ft.replace("<w:fonts ", '<w:fonts xmlns:r="%s" ' % R_NS, 1)
    rels_path = "word/_rels/fontTable.xml.rels"
    rels = items.get(rels_path)
    if rels is None:
        rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>').encode("utf-8")
    rels = rels.decode("utf-8")
    ct = items["[Content_Types].xml"].decode("utf-8")
    if 'Extension="odttf"' not in ct:
        ct = ct.replace("<Default ", '<Default Extension="odttf" ContentType="%s"/><Default ' % CT_ODTTF, 1)
    existing_font_files = [k for k in items if k.startswith("word/fonts/")]
    n = len(existing_font_files)
    done, missing = [], []
    for name in sorted(font_names):
        if re.search(r'<w:font w:name="%s">[^§]*?<w:embed' % re.escape(name), ft):
            done.append(name + "（原已嵌入）"); continue
        faces = find_font(idx, name)
        if "regular" not in faces:
            missing.append(name); continue
        # 去掉旧的 <w:font> 声明，重写
        ft = re.sub(r'<w:font w:name="%s">.*?</w:font>' % re.escape(name), "", ft, flags=re.S)
        ft = re.sub(r'<w:font w:name="%s"/>' % re.escape(name), "", ft)
        parts = ['<w:font w:name="%s"><w:charset w:val="86"/><w:family w:val="auto"/><w:pitch w:val="variable"/>' % name]
        for key, tag in (("regular", "embedRegular"), ("bold", "embedBold"), ("italic", "embedItalic"), ("boldItalic", "embedBoldItalic")):
            if key not in faces: continue
            p, fi = faces[key]
            raw = extract_face(p, fi)
            guid = str(uuid.uuid4()).upper()
            n += 1
            fname = "word/fonts/font%d.odttf" % n
            items[fname] = obfuscate(raw, guid)
            rid = "rIdFont%d" % n
            rels = rels.replace("</Relationships>", '<Relationship Id="%s" Type="%s" Target="fonts/font%d.odttf"/></Relationships>' % (rid, REL_FONT, n))
            parts.append('<w:%s r:id="%s" w:fontKey="{%s}"/>' % (tag, rid, guid))
            log.append("嵌入字体：%s ← %s%s（%.1f MB）" % (name, os.path.basename(p), "" if fi == 0 and not p.lower().endswith(".ttc") else "[面%d]" % fi, len(raw) / 1048576))
        parts.append("</w:font>")
        ft = ft.replace("</w:fonts>", "".join(parts) + "</w:fonts>")
        done.append(name)
    items[ft_path] = ft.encode("utf-8")
    items[rels_path] = rels.encode("utf-8")
    items["[Content_Types].xml"] = ct.encode("utf-8")
    # settings.xml：启用嵌入
    sp = "word/settings.xml"
    st = items.get(sp)
    if st is not None and [d for d in done if "原已嵌入" not in d]:
        st = st.decode("utf-8")
        if "<w:embedTrueTypeFonts" not in st:
            flag = "<w:embedTrueTypeFonts/>"
            m = re.search(r"<w:zoom[^>]*/>|<w:zoom[^>]*>.*?</w:zoom>|<w:view[^>]*/>|<w:writeProtection[^>]*/>", st, re.S)
            if m: st = st[:m.end()] + flag + st[m.end():]
            else: st = re.sub(r"(<w:settings[^>]*>)", r"\1" + flag, st, count=1)
        st = st.replace("<w:saveSubsetFonts/>", "")
        items[sp] = st.encode("utf-8")
    return done, missing
