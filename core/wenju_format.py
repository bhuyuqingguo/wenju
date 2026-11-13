from __future__ import annotations

import json
import os
import zipfile
import xml.etree.ElementTree as ET
from copy import deepcopy

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
XML = "http://www.w3.org/XML/1998/namespace"
EMU_PER_PX = 914400 / 96
_CN = "一二三四五六七八九"
_BLOCK_TYPES = {"heading", "paragraph", "table", "image", "pagebreak", "toc"}
_SIZE_NAMES = {
    "初号": 42, "小初": 36, "一号": 26, "小一": 24, "二号": 22, "小二": 18,
    "三号": 16, "小三": 15, "四号": 14, "小四": 12, "五号": 10.5, "小五": 9,
    "六号": 7.5, "小六": 6.5, "七号": 5.5, "八号": 5,
}


def _q(ns, tag):
    return "{%s}%s" % (ns, tag)


def _size_pt(value, default=12):
    try:
        import docx_fmt
        return float(docx_fmt.size_pt(value, default))
    except Exception:
        if value is None or value == "":
            return float(default)
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip().replace("磅", "").replace("pt", "").replace("號", "号")
        if text in _SIZE_NAMES:
            return float(_SIZE_NAMES[text])
        try:
            return float(text)
        except ValueError:
            return float(default)


class WenjuDoc(object):
    def __init__(self, blocks=None, styles=None, assets=None, manifest=None):
        self.blocks = [] if blocks is None else blocks
        self.styles = {} if styles is None else styles
        self.assets = {} if assets is None else assets
        self.manifest = {"format": "wenju", "version": 1} if manifest is None else manifest


def validate(doc):
    errors = []
    if not isinstance(doc, WenjuDoc):
        return ["不是文矩文档"]
    manifest = doc.manifest if isinstance(doc.manifest, dict) else {}
    if manifest.get("format") != "wenju":
        errors.append("manifest.format 必须是 wenju")
    if manifest.get("version") != 1:
        errors.append("manifest.version 必须是 1")
    if not isinstance(doc.blocks, list):
        errors.append("document.json 必须是块列表")
        return errors
    if not isinstance(doc.assets, dict):
        errors.append("assets 必须是文件名到内容的映射")
        doc_assets = {}
    else:
        doc_assets = doc.assets
    for index, block in enumerate(doc.blocks):
        where = "第 %d 块" % (index + 1)
        if not isinstance(block, dict) or block.get("type") not in _BLOCK_TYPES:
            errors.append("%s 类型无法识别" % where)
            continue
        kind = block["type"]
        if kind in ("heading", "paragraph"):
            errors.extend(_runs_errors(block.get("runs"), where))
        if kind == "heading":
            level = block.get("level")
            if not isinstance(level, int) or not 1 <= level <= 9:
                errors.append("%s 的标题级别必须是 1 到 9" % where)
        if kind == "paragraph" and "runs" not in block:
            errors.append("%s 缺少 runs" % where)
        if kind == "table":
            rows = block.get("rows")
            if not isinstance(rows, list):
                errors.append("%s 的表格缺少 rows" % where)
            else:
                for r_index, row in enumerate(rows):
                    if not isinstance(row, list):
                        errors.append("%s 第 %d 行不是单元格列表" % (where, r_index + 1))
                        continue
                    for c_index, cell in enumerate(row):
                        if not isinstance(cell, dict):
                            errors.append("%s 单元格 %d,%d 无法识别" % (where, r_index + 1, c_index + 1))
                            continue
                        errors.extend(_runs_errors(cell.get("runs"), "%s 单元格 %d,%d" % (where, r_index + 1, c_index + 1)))
            merges = block.get("merges", [])
            if not isinstance(merges, list):
                errors.append("%s 的 merges 必须是列表" % where)
        if kind == "image":
            asset = block.get("asset")
            if not isinstance(asset, str) or not asset:
                errors.append("%s 缺少图片文件名" % where)
            elif asset not in doc_assets:
                errors.append("%s 引用的图片不在 assets 中：%s" % (where, asset))
            for key in ("w", "h"):
                if not isinstance(block.get(key), (int, float)):
                    errors.append("%s 的 %s 必须是数字" % (where, key))
    return errors


def _runs_errors(runs, where):
    if not isinstance(runs, list):
        return ["%s 缺少 runs" % where]
    errors = []
    for run in runs:
        if not isinstance(run, dict) or not isinstance(run.get("text"), str):
            errors.append("%s 的文字片段必须带 text" % where)
    return errors


def save(doc, path):
    errors = validate(doc)
    if errors:
        raise ValueError("无法保存文矩文件：%s" % "；".join(errors))
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", _dumps(doc.manifest))
        archive.writestr("document.json", _dumps(doc.blocks))
        archive.writestr("styles.json", _dumps(doc.styles))
        archive.writestr("assets/", "")
        for name, payload in doc.assets.items():
            archive.writestr("assets/" + name.replace("\\", "/").split("/")[-1], payload)


def load(path):
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise ValueError("无法打开文矩文件：不是有效的压缩包")
    with archive:
        names = set(archive.namelist())
        for required in ("manifest.json", "document.json", "styles.json"):
            if required not in names:
                raise ValueError("无法打开文矩文件：缺少 %s" % required)
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        document = json.loads(archive.read("document.json").decode("utf-8"))
        styles = json.loads(archive.read("styles.json").decode("utf-8"))
        assets = {}
        for name in names:
            if name.startswith("assets/") and not name.endswith("/"):
                assets[name.split("/")[-1]] = archive.read(name)
    blocks = document if isinstance(document, list) else document.get("blocks") if isinstance(document, dict) else None
    doc = WenjuDoc(blocks, styles if isinstance(styles, dict) else {}, assets, manifest if isinstance(manifest, dict) else {})
    errors = validate(doc)
    if errors:
        raise ValueError("无效的文矩文件：%s" % "；".join(errors))
    return doc


def from_docx(path):
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise ValueError("这个文件不是可读的 docx")
    with archive:
        items = {info.filename: archive.read(info.filename) for info in archive.infolist()}
    if "word/document.xml" not in items:
        raise ValueError("这个文件不是可读的 docx：缺少 word/document.xml")
    rels = _relationships(items.get("word/_rels/document.xml.rels", b""))
    styles = _style_map(items.get("word/styles.xml", b""))
    root = ET.fromstring(items["word/document.xml"])
    body = root.find(_q(W, "body"))
    blocks = []
    assets = {}
    if body is not None:
        for child in list(body):
            blocks.extend(_block_from_body(child, rels, items, styles, assets))
    manifest = {"format": "wenju", "version": 1, "source": os.path.basename(path)}
    return WenjuDoc(blocks, styles, assets, manifest)


def to_docx(doc, path, template=None):
    target = doc
    if template is not None:
        target = _clone(doc)
        brush(target, template)
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    _write_docx(target, path)
    return path


def brush(doc, template):
    rules = _load_rules(template)
    if not rules:
        raise ValueError("按模板刷需要模板规则")
    fonts = rules.get("字体") or {}
    body = rules.get("正文") or {}
    heads = rules.get("标题") or {}
    keep_marks = body.get("保留加粗斜体下划线", True)
    body_font = fonts.get("正文") or ""
    body_size = _size_pt(body.get("字号"), 16)
    body_bold = bool(body.get("加粗"))
    table_font = fonts.get("表格") or body_font
    for block in doc.blocks:
        kind = block.get("type")
        if kind == "heading":
            key = _level_key(block.get("level"))
            spec = heads.get(key) or {} if key else {}
            font = (fonts.get(key + "标题") if key else None) or body_font
            size = _size_pt(spec.get("字号"), body_size)
            bold = bool(spec.get("加粗"))
            for run in block.get("runs") or []:
                _paint(run, font, size, bold, keep_marks)
        elif kind == "paragraph":
            block["style"] = "正文"
            for run in block.get("runs") or []:
                _paint(run, body_font, body_size, body_bold, keep_marks)
        elif kind == "table":
            for row in block.get("rows") or []:
                for cell in row:
                    for run in cell.get("runs") or []:
                        _paint(run, table_font, body_size, False, keep_marks)
    return doc


def _clone(doc):
    return WenjuDoc(deepcopy(doc.blocks), deepcopy(doc.styles), dict(doc.assets), deepcopy(doc.manifest))


def _load_rules(template):
    if template is None or template == "":
        return None
    if isinstance(template, dict):
        return template
    if isinstance(template, str) and os.path.isfile(template):
        with open(template, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            return loaded
    raise ValueError("模板必须是规则对象或 JSON 文件")


def _level_key(level):
    if isinstance(level, int) and 1 <= level <= 9:
        return _CN[level - 1] + "级"
    return None


def _paint(run, font, size, bold, keep_marks):
    if not isinstance(run, dict):
        return
    if font:
        run["font"] = font
        run.pop("ascii", None)
    if size:
        run["size"] = float(size)
    if keep_marks:
        if bold:
            run["bold"] = True
        return
    if bold:
        run["bold"] = True
    else:
        run.pop("bold", None)
    for key in ("italic", "underline", "color"):
        run.pop(key, None)


def _dumps(value):
    return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")


def _relationships(payload):
    found = {}
    if not payload:
        return found
    root = ET.fromstring(payload)
    for rel in list(root):
        rid = rel.attrib.get("Id")
        target = rel.attrib.get("Target")
        if rid and target:
            found[rid] = target
    return found


def _style_map(payload):
    found = {}
    if not payload:
        return found
    root = ET.fromstring(payload)
    for style in root.findall(_q(W, "style")):
        sid = style.attrib.get(_q(W, "styleId"))
        if not sid:
            continue
        name_el = style.find(_q(W, "name"))
        name = name_el.attrib.get(_q(W, "val")) if name_el is not None else sid
        level = _heading_level(name) or _heading_level(sid)
        mark = {}
        props = style.find(_q(W, "rPr"))
        if props is not None:
            mark = _mark_from_rpr(props)
        found[sid] = {"name": name, "level": level, "mark": mark}
    return found


def _heading_level(value):
    if not value:
        return None
    compact = str(value).replace(" ", "")
    for prefix in ("Heading", "heading", "标题"):
        if compact.startswith(prefix):
            rest = compact[len(prefix):]
            if rest.isdigit():
                level = int(rest)
                if 1 <= level <= 9:
                    return level
    return None


def _block_from_body(child, rels, items, styles, assets):
    if child.tag == _q(W, "p"):
        return _paragraph_blocks(child, rels, items, styles, assets)
    if child.tag == _q(W, "tbl"):
        table, images = _table_block(child, rels, items, styles, assets)
        return [table] + images
    if child.tag == _q(W, "sdt"):
        return _sdt_blocks(child, rels, items, styles, assets)
    return []


def _is_toc(element):
    for node in element.iter(_q(W, "instrText")):
        if (node.text or "").strip().upper().startswith("TOC"):
            return True
    return False


_RUN_KEYS = ("bold", "italic", "underline", "font", "ascii", "size", "color")


def _paragraph_blocks(paragraph, rels, items, styles, assets):
    level = _paragraph_level(paragraph, styles)
    base = _paragraph_base_mark(paragraph, styles)
    runs = []
    blocks = []
    current = {"text": ""}
    seen = False

    def flush():
        nonlocal current, seen
        if seen or current.get("text"):
            stored = {"text": current.get("text") or ""}
            for key in _RUN_KEYS:
                if key in current:
                    stored[key] = current[key]
            runs.append(stored)
        current = {"text": ""}
        seen = False

    def emit_text(text):
        nonlocal seen
        if not text:
            return
        current["text"] = current.get("text", "") + text
        seen = True

    def close_text():
        nonlocal runs
        flush()
        if runs:
            blocks.append(_text_block(level, runs))
            runs = []

    def take_drawing(node):
        boxes = _textbox_blocks(node, rels, items, styles, assets)
        if boxes:
            close_text()
            blocks.extend(boxes)
            return
        image = _image_block(node, rels, items, assets)
        if image:
            close_text()
            blocks.append(image)

    def take_run(run):
        mark = _merge_mark(base, _run_mark(run))

        def use_mark():
            for key in _RUN_KEYS:
                current.pop(key, None)
            current.update(mark)

        if _mark_key(mark) != _mark_key(current) and (seen or current.get("text")):
            flush()
        use_mark()
        for node in list(run):
            if node.tag == _q(W, "br") and node.attrib.get(_q(W, "type")) == "page":
                close_text()
                blocks.append({"type": "pagebreak"})
                use_mark()
            elif node.tag == _q(W, "br"):
                emit_text("\n")
            elif node.tag == _q(W, "tab"):
                emit_text("\t")
            elif node.tag == _q(W, "t"):
                emit_text(node.text or "")
            elif node.tag == _q(W, "drawing"):
                take_drawing(node)
                use_mark()

    def walk(node):
        tag = node.tag
        if tag == _q(W, "r"):
            take_run(node)
            return
        if tag == _q(W, "del"):
            return
        if tag == _q(W, "sdt"):
            content = node.find(_q(W, "sdtContent"))
            for child in list(content if content is not None else node):
                walk(child)
            return
        if tag in (_q(W, "hyperlink"), _q(W, "smartTag"), _q(W, "ins"), _q(W, "fldSimple")):
            for child in list(node):
                walk(child)

    for child in list(paragraph):
        if child.tag != _q(W, "pPr"):
            walk(child)
    flush()
    if _is_toc(paragraph):
        blocks.append({"type": "toc"})
        runs = [run for run in runs if run.get("text", "").strip()]
    if runs:
        blocks.append(_text_block(level, runs))
    return blocks


def _sdt_blocks(element, rels, items, styles, assets):
    if _is_toc(element):
        return [{"type": "toc"}]
    content = element.find(_q(W, "sdtContent"))
    blocks = []
    for nested in list(content if content is not None else element):
        if nested.tag in (_q(W, "p"), _q(W, "tbl"), _q(W, "sdt")):
            blocks.extend(_block_from_body(nested, rels, items, styles, assets))
    return blocks


def _textbox_blocks(drawing, rels, items, styles, assets):
    blocks = []
    for box in drawing.iter(_q(W, "txbxContent")):
        for inner in list(box):
            if inner.tag in (_q(W, "p"), _q(W, "tbl"), _q(W, "sdt")):
                blocks.extend(_block_from_body(inner, rels, items, styles, assets))
    return blocks


def _paragraph_base_mark(paragraph, styles):
    props = paragraph.find(_q(W, "pPr"))
    if props is None:
        return {}
    mark = {}
    style = props.find(_q(W, "pStyle"))
    if style is not None:
        mark.update((styles.get(style.attrib.get(_q(W, "val"))) or {}).get("mark") or {})
    direct = props.find(_q(W, "rPr"))
    if direct is not None:
        mark = _merge_mark(mark, _mark_from_rpr(direct))
    return mark


def _merge_mark(base, direct):
    mark = dict(base or {})
    mark.update(direct or {})
    for key in ("bold", "italic", "underline"):
        if mark.get(key) is False:
            mark.pop(key, None)
    return mark


def _mark_key(mark):
    return tuple(sorted((key, mark[key]) for key in _RUN_KEYS if key in mark))


def _text_block(level, runs):
    if level:
        return {"type": "heading", "level": level, "runs": runs}
    return {"type": "paragraph", "style": "Normal", "runs": runs}


def _paragraph_level(paragraph, styles):
    props = paragraph.find(_q(W, "pPr"))
    if props is None:
        return None
    style = props.find(_q(W, "pStyle"))
    if style is not None:
        sid = style.attrib.get(_q(W, "val"))
        mapped = styles.get(sid) or {}
        level = mapped.get("level") or _heading_level(sid)
        if level:
            return level
    outline = props.find(_q(W, "outlineLvl"))
    if outline is not None and str(outline.attrib.get(_q(W, "val"), "")).isdigit():
        level = int(outline.attrib.get(_q(W, "val"))) + 1
        if 1 <= level <= 9:
            return level
    return None


def _run_mark(run):
    props = run.find(_q(W, "rPr"))
    if props is None:
        return {}
    return _mark_from_rpr(props)


def _mark_from_rpr(props):
    mark = {}
    for key, tag in (("bold", "b"), ("italic", "i")):
        flag = _tri(props, tag)
        if flag is not None:
            mark[key] = flag
    underline = props.find(_q(W, "u"))
    if underline is not None:
        mark["underline"] = underline.attrib.get(_q(W, "val"), "single") not in ("none", "false", "0")
    fonts = props.find(_q(W, "rFonts"))
    if fonts is not None:
        east = fonts.attrib.get(_q(W, "eastAsia"))
        latin = fonts.attrib.get(_q(W, "ascii")) or fonts.attrib.get(_q(W, "hAnsi"))
        if east:
            mark["font"] = east
        elif latin:
            mark["font"] = latin
        if latin and latin != mark.get("font"):
            mark["ascii"] = latin
    size = props.find(_q(W, "sz"))
    if size is not None and str(size.attrib.get(_q(W, "val"), "")).isdigit():
        mark["size"] = int(size.attrib.get(_q(W, "val"))) / 2.0
    color = props.find(_q(W, "color"))
    if color is not None:
        value = color.attrib.get(_q(W, "val"))
        if value and value.lower() != "auto":
            mark["color"] = value
    return mark


def _tri(props, tag):
    node = props.find(_q(W, tag))
    if node is None:
        return None
    return node.attrib.get(_q(W, "val")) not in ("false", "0", "off")


def _image_block(drawing, rels, items, assets):
    rid = None
    for node in drawing.iter(_q(A, "blip")):
        rid = node.attrib.get(_q(R, "embed"))
        break
    if not rid or rid not in rels:
        return None
    target = rels[rid].replace("\\", "/").lstrip("/")
    if not target.startswith("word/"):
        target = "word/" + target
    payload = items.get(target)
    if payload is None:
        return None
    name = target.split("/")[-1]
    base, dot, ext = name.rpartition(".")
    stem = base or name
    suffix = ("." + ext) if dot else ""
    unique = name
    number = 2
    while unique in assets and assets[unique] != payload:
        unique = "%s-%d%s" % (stem, number, suffix)
        number += 1
    assets[unique] = payload
    width, height = 0, 0
    for node in drawing.iter(_q(WP, "extent")):
        width = _emu_px(node.attrib.get("cx"))
        height = _emu_px(node.attrib.get("cy"))
        break
    return {"type": "image", "asset": unique, "w": width, "h": height}


def _emu_px(value):
    try:
        return int(round(int(value) / EMU_PER_PX))
    except (TypeError, ValueError):
        return 0


def _table_block(table, rels, items, styles, assets):
    rows = []
    merges = []
    open_merge = {}
    trailing = []
    for r_index, row_el in enumerate(table.findall(_q(W, "tr"))):
        row = []
        col = 0
        for cell in row_el.findall(_q(W, "tc")):
            span = 1
            props = cell.find(_q(W, "tcPr"))
            vertical = None
            if props is not None:
                grid = props.find(_q(W, "gridSpan"))
                if grid is not None and str(grid.attrib.get(_q(W, "val"), "")).isdigit():
                    span = max(1, int(grid.attrib.get(_q(W, "val"))))
                merge = props.find(_q(W, "vMerge"))
                if merge is not None:
                    vertical = merge.attrib.get(_q(W, "val"), "continue")
            runs, extras = _cell_runs(cell, rels, items, styles, assets)
            row.append({"runs": runs})
            trailing.extend(extras)
            if vertical == "restart":
                record = {"row": r_index, "col": col, "rowspan": 1, "colspan": span}
                merges.append(record)
                open_merge[col] = record
            elif vertical is not None and col in open_merge:
                open_merge[col]["rowspan"] += 1
            elif vertical is None:
                open_merge.pop(col, None)
                if span > 1:
                    merges.append({"row": r_index, "col": col, "rowspan": 1, "colspan": span})
            for _extra in range(span - 1):
                row.append({"runs": [{"text": ""}]})
            col += span
        rows.append(row)
    return {"type": "table", "rows": rows, "merges": merges}, trailing


def _cell_runs(cell, rels, items, styles, assets):
    runs = []
    extras = []
    started = False
    for child in list(cell):
        if child.tag == _q(W, "p"):
            for block in _paragraph_blocks(child, rels, items, styles, assets):
                if block.get("type") in ("paragraph", "heading"):
                    piece = [dict(run) for run in block.get("runs") or []]
                    if started and piece:
                        piece[0]["text"] = "\n" + piece[0].get("text", "")
                    if piece:
                        runs.extend(piece)
                        started = True
                else:
                    extras.append(block)
        elif child.tag == _q(W, "tbl"):
            nested, more = _table_block(child, rels, items, styles, assets)
            extras.append(nested)
            extras.extend(more)
    if not runs:
        runs = [{"text": ""}]
    return runs, extras


def _write_docx(doc, path):
    for prefix, uri in (("w", W), ("r", R), ("wp", WP), ("a", A), ("pic", PIC)):
        ET.register_namespace(prefix, uri)
    body = ET.Element(_q(W, "body"))
    rels = []
    media = []
    next_id = 2
    for block in doc.blocks:
        kind = block.get("type")
        if kind in ("paragraph", "heading"):
            body.append(_write_paragraph(block))
        elif kind == "pagebreak":
            body.append(_write_page_break())
        elif kind == "toc":
            body.append(_write_toc())
        elif kind == "table":
            body.append(_write_table(block))
        elif kind == "image":
            payload = doc.assets.get(block.get("asset"))
            if payload is None:
                continue
            rid = "rId%d" % next_id
            next_id += 1
            rels.append((rid, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image", "media/" + block["asset"]))
            media.append((block["asset"], payload))
            body.append(_write_image(block, rid))
    sect = ET.SubElement(body, _q(W, "sectPr"))
    size = ET.SubElement(sect, _q(W, "pgSz"))
    size.set(_q(W, "w"), "11906")
    size.set(_q(W, "h"), "16838")
    margin = ET.SubElement(sect, _q(W, "pgMar"))
    for key, value in (("top", "1440"), ("right", "1440"), ("bottom", "1440"), ("left", "1440")):
        margin.set(_q(W, key), value)
    document = ET.Element(_q(W, "document"))
    document.append(body)
    styles = _styles_root()
    content_types = _content_types(media)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", _package_rels())
        archive.writestr("word/document.xml", ET.tostring(document, encoding="utf-8", xml_declaration=True))
        archive.writestr("word/styles.xml", ET.tostring(styles, encoding="utf-8", xml_declaration=True))
        archive.writestr("word/_rels/document.xml.rels", _document_rels(rels))
        for name, payload in media:
            archive.writestr("word/media/" + name, payload)


def _write_paragraph(block):
    paragraph = ET.Element(_q(W, "p"))
    props = ET.SubElement(paragraph, _q(W, "pPr"))
    if block.get("type") == "heading":
        style = ET.SubElement(props, _q(W, "pStyle"))
        style.set(_q(W, "val"), "Heading%d" % int(block.get("level") or 1))
    for run in block.get("runs") or []:
        _write_run(paragraph, run)
    if not list(paragraph.findall(_q(W, "r"))):
        ET.SubElement(paragraph, _q(W, "r"))
    return paragraph


def _write_run(paragraph, run):
    parts = str(run.get("text") or "").split("\n")
    for index, part in enumerate(parts):
        if index:
            broken = ET.SubElement(paragraph, _q(W, "r"))
            ET.SubElement(broken, _q(W, "br"))
        if part == "" and index == 0 and len(parts) == 1:
            node = ET.SubElement(paragraph, _q(W, "r"))
            _write_rpr(node, run)
            ET.SubElement(node, _q(W, "t"))
            continue
        if part == "":
            continue
        node = ET.SubElement(paragraph, _q(W, "r"))
        _write_rpr(node, run)
        text = ET.SubElement(node, _q(W, "t"))
        text.text = part
        if part[:1].isspace() or part[-1:].isspace() or "  " in part:
            text.set(_q(XML, "space"), "preserve")


def _write_rpr(run, source):
    props = ET.Element(_q(W, "rPr"))
    if source.get("bold"):
        ET.SubElement(props, _q(W, "b"))
    if source.get("italic"):
        ET.SubElement(props, _q(W, "i"))
    if source.get("underline"):
        underline = ET.SubElement(props, _q(W, "u"))
        underline.set(_q(W, "val"), "single")
    east = source.get("font") or source.get("ascii")
    latin = source.get("ascii") or source.get("font")
    if east or latin:
        fonts = ET.SubElement(props, _q(W, "rFonts"))
        for key in ("ascii", "hAnsi", "cs"):
            fonts.set(_q(W, key), latin)
        fonts.set(_q(W, "eastAsia"), east)
    if source.get("size"):
        size = ET.SubElement(props, _q(W, "sz"))
        size.set(_q(W, "val"), str(int(round(float(source["size"]) * 2))))
    if source.get("color"):
        color = ET.SubElement(props, _q(W, "color"))
        color.set(_q(W, "val"), str(source["color"]))
    if list(props):
        run.insert(0, props)


def _write_page_break():
    paragraph = ET.Element(_q(W, "p"))
    run = ET.SubElement(paragraph, _q(W, "r"))
    broken = ET.SubElement(run, _q(W, "br"))
    broken.set(_q(W, "type"), "page")
    return paragraph


def _write_toc():
    paragraph = ET.Element(_q(W, "p"))
    begin = ET.SubElement(paragraph, _q(W, "r"))
    field = ET.SubElement(begin, _q(W, "fldChar"))
    field.set(_q(W, "fldCharType"), "begin")
    instr = ET.SubElement(paragraph, _q(W, "r"))
    text = ET.SubElement(instr, _q(W, "instrText"))
    text.set(_q(XML, "space"), "preserve")
    text.text = ' TOC \\o "1-3" \\h \\z \\u '
    end = ET.SubElement(paragraph, _q(W, "r"))
    field_end = ET.SubElement(end, _q(W, "fldChar"))
    field_end.set(_q(W, "fldCharType"), "end")
    return paragraph


def _write_table(block):
    table = ET.Element(_q(W, "tbl"))
    coverage = _coverage(block.get("merges") or [])
    for r_index, row in enumerate(block.get("rows") or []):
        row_el = ET.SubElement(table, _q(W, "tr"))
        for c_index, cell in enumerate(row):
            role = coverage.get((r_index, c_index))
            if role and role[0] == "skip":
                continue
            cell_el = ET.SubElement(row_el, _q(W, "tc"))
            if role:
                props = ET.SubElement(cell_el, _q(W, "tcPr"))
                if role[0] == "anchor" and role[1]["colspan"] > 1:
                    span = ET.SubElement(props, _q(W, "gridSpan"))
                    span.set(_q(W, "val"), str(role[1]["colspan"]))
                if role[0] == "anchor" and role[1]["rowspan"] > 1:
                    merge = ET.SubElement(props, _q(W, "vMerge"))
                    merge.set(_q(W, "val"), "restart")
                if role[0] == "continue":
                    if role[1].get("colspan", 1) > 1:
                        span = ET.SubElement(props, _q(W, "gridSpan"))
                        span.set(_q(W, "val"), str(role[1]["colspan"]))
                    ET.SubElement(props, _q(W, "vMerge"))
            paragraph = ET.SubElement(cell_el, _q(W, "p"))
            if not role or role[0] != "continue":
                for run in cell.get("runs") or []:
                    _write_run(paragraph, run)
    return table


def _coverage(merges):
    found = {}
    for merge in merges:
        row, col = int(merge["row"]), int(merge["col"])
        rowspan = max(1, int(merge.get("rowspan") or 1))
        colspan = max(1, int(merge.get("colspan") or 1))
        if rowspan == 1 and colspan == 1:
            continue
        for r_index in range(row, row + rowspan):
            for c_index in range(col, col + colspan):
                if r_index == row and c_index == col:
                    found[(r_index, c_index)] = ("anchor", merge)
                elif c_index == col:
                    found[(r_index, c_index)] = ("continue", merge)
                else:
                    found.setdefault((r_index, c_index), ("skip", merge))
    return found


def _write_image(block, rid):
    paragraph = ET.Element(_q(W, "p"))
    run = ET.SubElement(paragraph, _q(W, "r"))
    drawing = ET.SubElement(run, _q(W, "drawing"))
    inline = ET.SubElement(drawing, _q(WP, "inline"))
    extent = ET.SubElement(inline, _q(WP, "extent"))
    extent.set("cx", str(int(round(float(block.get("w") or 0) * EMU_PER_PX))))
    extent.set("cy", str(int(round(float(block.get("h") or 0) * EMU_PER_PX))))
    graphic = ET.SubElement(inline, _q(A, "graphic"))
    data = ET.SubElement(graphic, _q(A, "graphicData"))
    data.set("uri", PIC)
    picture = ET.SubElement(data, _q(PIC, "pic"))
    fill = ET.SubElement(picture, _q(PIC, "blipFill"))
    blip = ET.SubElement(fill, _q(A, "blip"))
    blip.set(_q(R, "embed"), rid)
    return paragraph


def _styles_root():
    root = ET.Element(_q(W, "styles"))
    for level in range(1, 10):
        style = ET.SubElement(root, _q(W, "style"))
        style.set(_q(W, "type"), "paragraph")
        style.set(_q(W, "styleId"), "Heading%d" % level)
        name = ET.SubElement(style, _q(W, "name"))
        name.set(_q(W, "val"), "heading %d" % level)
        props = ET.SubElement(style, _q(W, "pPr"))
        outline = ET.SubElement(props, _q(W, "outlineLvl"))
        outline.set(_q(W, "val"), str(level - 1))
    return root


def _content_types(media):
    root = ET.Element(_q(CT, "Types"))
    defaults = {"rels": "application/vnd.openxmlformats-package.relationships+xml", "xml": "application/xml"}
    for name, _payload in media:
        ext = name.rsplit(".", 1)[-1].lower()
        defaults.setdefault(ext, _image_type(ext))
    for ext, content_type in defaults.items():
        node = ET.SubElement(root, _q(CT, "Default"))
        node.set("Extension", ext)
        node.set("ContentType", content_type)
    for part, content_type in (
        ("/word/document.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"),
        ("/word/styles.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"),
    ):
        node = ET.SubElement(root, _q(CT, "Override"))
        node.set("PartName", part)
        node.set("ContentType", content_type)
    ET.register_namespace("", CT)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _image_type(ext):
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "bmp": "image/bmp",
    }.get(ext, "application/octet-stream")


def _package_rels():
    root = ET.Element(_q(REL, "Relationships"))
    node = ET.SubElement(root, _q(REL, "Relationship"))
    node.set("Id", "rId1")
    node.set("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument")
    node.set("Target", "word/document.xml")
    ET.register_namespace("", REL)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _document_rels(extra):
    root = ET.Element(_q(REL, "Relationships"))
    style = ET.SubElement(root, _q(REL, "Relationship"))
    style.set("Id", "rId1")
    style.set("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles")
    style.set("Target", "styles.xml")
    for rid, kind, target in extra:
        node = ET.SubElement(root, _q(REL, "Relationship"))
        node.set("Id", rid)
        node.set("Type", kind)
        node.set("Target", target)
    ET.register_namespace("", REL)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
