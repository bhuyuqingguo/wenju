# -*- coding: utf-8 -*-
"""文矩 .wenju package and the docx conversion used by the other three lines."""
from __future__ import annotations

import json
import os
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import fontfallback

APP_VERSION = "3.3.0"
FORMAT = "wenju"

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
DC = "http://purl.org/dc/elements/1.1/"
DCTERMS = "http://purl.org/dc/terms/"
CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"

EMU_PER_PT = 12700
BLOCK_TYPES = ("heading", "paragraph", "table", "image", "pagebreak", "toc")
HEADING_NAME = re.compile(r"^(?:heading|标题)\s*(\d)$", re.I)
ALIGNS = {
    "left": "left", "center": "center", "right": "right", "both": "both",
    "distribute": "distribute", "justify": "both",
    "左": "left", "中": "center", "右": "right",
    "左对齐": "left", "居中": "center", "右对齐": "right",
    "两端对齐": "both", "分散对齐": "distribute",
}
RUN_KEYS = ("text", "eastAsia", "ascii", "hAnsi", "size_pt", "bold", "italic", "underline", "color")

for _prefix, _uri in (
    ("w", W), ("r", R), ("wp", WP), ("a", A), ("pic", PIC),
    ("pr", REL), ("ct", CT), ("dc", DC), ("cp", CP),
):
    ET.register_namespace(_prefix, _uri)


def q(ns, tag):
    return "{%s}%s" % (ns, tag)


def local(tag):
    return tag.rsplit("}", 1)[-1]


def utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def num(value):
    number = float(value)
    if number == int(number):
        return int(number)
    return round(number, 2)


def emu_to_pt(value):
    return num(float(value) / EMU_PER_PT)


def pt_to_emu(value):
    return int(round(float(value) * EMU_PER_PT))


@dataclass
class WenjuDoc:
    blocks: list
    styles: dict
    assets: dict
    title: str = ""
    source: dict = field(default_factory=lambda: {"kind": "new", "name": ""})
    app_version: str = APP_VERSION
    created: str = ""
    version: int = 1

    def __post_init__(self):
        if not self.created:
            self.created = utcnow()
        if not self.source:
            self.source = {"kind": "new", "name": ""}


def manifest_of(doc):
    return {
        "format": FORMAT,
        "version": doc.version,
        "app_version": doc.app_version,
        "created": doc.created,
        "title": doc.title,
        "source": {"kind": doc.source.get("kind", ""), "name": doc.source.get("name", "")},
    }


def validate(doc):
    """Return a list of problems. An empty list means the document is usable."""
    errors = []
    if not isinstance(doc, WenjuDoc):
        return ["文档不是 WenjuDoc"]
    if doc.version != 1:
        errors.append("只支持 version 1，当前是 %s" % doc.version)
    if not isinstance(doc.source, dict) or "kind" not in doc.source or "name" not in doc.source:
        errors.append("manifest.source 需要 kind 和 name")
    if not isinstance(doc.blocks, list):
        errors.append("document.blocks 必须是有序列表")
        return errors
    if not isinstance(doc.styles, dict):
        errors.append("styles 必须是命名样式表")
    else:
        for name, style in doc.styles.items():
            if not isinstance(name, str) or not isinstance(style, dict):
                errors.append("样式 %s 无法识别" % name)
                continue
            _check_style(style, "样式「%s」" % name, errors)
    if not isinstance(doc.assets, dict):
        errors.append("assets 必须是文件名到字节的映射")
        doc_assets = {}
    else:
        doc_assets = doc.assets
    for index, block in enumerate(doc.blocks):
        _check_block(block, index, doc_assets, errors)
    return errors


def load(path):
    path = str(path)
    try:
        with zipfile.ZipFile(path) as package:
            names = set(package.namelist())
            for required in ("manifest.json", "document.json", "styles.json"):
                if required not in names:
                    raise ValueError("文矩包缺少 %s" % required)
            manifest = json.loads(package.read("manifest.json").decode("utf-8"))
            document = json.loads(package.read("document.json").decode("utf-8"))
            styles = json.loads(package.read("styles.json").decode("utf-8"))
            assets = {}
            for name in names:
                if name.startswith("assets/") and not name.endswith("/"):
                    _safe_zip_name(name)
                    assets[name.split("/", 1)[1]] = package.read(name)
    except ValueError:
        raise
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("无法读取文矩包：%s" % exc)
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise ValueError("这不是文矩文档")
    if not isinstance(document, dict) or not isinstance(document.get("blocks"), list):
        raise ValueError("document.json 缺少 blocks")
    if not isinstance(styles, dict):
        raise ValueError("styles.json 必须是命名样式表")
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    doc = WenjuDoc(
        blocks=document["blocks"],
        styles=styles,
        assets=assets,
        title=manifest.get("title") or "",
        source={"kind": source.get("kind", ""), "name": source.get("name", "")},
        app_version=manifest.get("app_version") or APP_VERSION,
        created=manifest.get("created") or utcnow(),
        version=manifest.get("version") or 0,
    )
    errors = validate(doc)
    if errors:
        raise ValueError("文矩文档无效：%s" % "；".join(errors))
    return doc


def save(doc, path):
    errors = validate(doc)
    if errors:
        raise ValueError("文矩文档无效：%s" % "；".join(errors))
    path = str(path)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    files = [
        ("manifest.json", _dump(manifest_of(doc))),
        ("document.json", _dump({"blocks": doc.blocks})),
        ("styles.json", _dump(doc.styles)),
    ]
    for name, data in doc.assets.items():
        _safe_zip_name("assets/" + name)
        if not isinstance(data, (bytes, bytearray)):
            raise ValueError("图片 %s 不是字节" % name)
        files.append(("assets/" + name, bytes(data)))
    _write_zip(path, files)


def from_docx(path):
    path = str(path)
    with zipfile.ZipFile(path) as package:
        files = {info.filename: package.read(info.filename) for info in package.infolist()}
    if "word/document.xml" not in files:
        raise ValueError("docx 缺少 word/document.xml")
    styles, style_names = _read_styles(files.get("word/styles.xml", b""))
    rels = _read_rels(files.get("word/_rels/document.xml.rels", b""))
    root = ET.fromstring(files["word/document.xml"])
    body = root.find(q(W, "body"))
    blocks = _read_container(body, rels, files, style_names) if body is not None else []
    assets = _store_images(blocks)
    title = _title_from(blocks) or Path(path).stem
    return WenjuDoc(
        blocks=blocks,
        styles=styles,
        assets=assets,
        title=title,
        source={"kind": "docx", "name": os.path.basename(path)},
    )


def to_docx(doc, path, template=None):
    errors = validate(doc)
    if errors:
        raise ValueError("文矩文档无效：%s" % "；".join(errors))
    brush = _template_styles(template)
    styles = dict(doc.styles)
    if brush:
        styles.update(brush)
    style_ids = _style_ids(styles)
    image_rels = []
    body = ET.Element(q(W, "body"))
    picture_id = 1
    for block in doc.blocks:
        kind = block["type"]
        if kind in ("heading", "paragraph"):
            _write_paragraph(body, block, styles, style_ids, brush is not None)
        elif kind == "table":
            _write_table(body, block, styles, style_ids, brush is not None)
        elif kind == "image":
            rel_id = "rId%d" % (len(image_rels) + 2)
            image_rels.append((rel_id, block["asset"]))
            _write_image(body, block, rel_id, picture_id)
            picture_id += 1
        elif kind == "pagebreak":
            _write_page_break(body)
        elif kind == "toc":
            _write_toc(body)
    sect = ET.SubElement(body, q(W, "sectPr"))
    ET.SubElement(sect, q(W, "pgSz")).set(q(W, "w"), "11906")
    sect.find(q(W, "pgSz")).set(q(W, "h"), "16838")
    files = {
        "[Content_Types].xml": _content_types(doc.assets),
        "_rels/.rels": _package_rels(),
        "docProps/core.xml": _core_xml(doc.title),
        "word/document.xml": _xml(ET.ElementTree(_document_root(body))),
        "word/styles.xml": _styles_xml(styles, style_ids),
        "word/_rels/document.xml.rels": _document_rels(image_rels),
    }
    for _rel_id, asset in image_rels:
        files["word/media/" + asset] = bytes(doc.assets[asset])
    path = str(path)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    _write_zip(path, list(files.items()))


def convert_file(src, dest, template=None):
    """Open a .wenju or .docx and write a .wenju or .docx."""
    src = str(src)
    dest = str(dest)
    if src.lower().endswith(".wenju"):
        doc = load(src)
    elif src.lower().endswith(".docx"):
        doc = from_docx(src)
    else:
        raise ValueError("只能打开 .wenju 或 .docx")
    if dest.lower().endswith(".wenju"):
        save(doc, dest)
    elif dest.lower().endswith(".docx"):
        to_docx(doc, dest, template=template)
    else:
        raise ValueError("只能保存为 .wenju 或 .docx")
    return dest


def _check_block(block, index, assets, errors):
    where = "第 %d 块" % (index + 1)
    if not isinstance(block, dict) or block.get("type") not in BLOCK_TYPES:
        errors.append("%s 类型无法识别" % where)
        return
    kind = block["type"]
    if kind in ("heading", "paragraph"):
        if not isinstance(block.get("runs"), list):
            errors.append("%s 缺少 runs" % where)
        else:
            for run in block["runs"]:
                _check_run(run, where, errors)
        if kind == "heading":
            level = block.get("level")
            if not isinstance(level, int) or isinstance(level, bool) or not 1 <= level <= 9:
                errors.append("%s 标题层级必须是 1 到 9" % where)
        _check_style(block, where, errors)
    elif kind == "table":
        rows = block.get("rows")
        if not rows or not isinstance(rows, list) or not all(isinstance(row, list) and row for row in rows):
            errors.append("%s 表格至少要有一行一列" % where)
            return
        width = len(rows[0])
        if any(len(row) != width for row in rows):
            errors.append("%s 表格每一行的列数要相同" % where)
        for row in rows:
            for cell in row:
                if not isinstance(cell, dict):
                    errors.append("%s 单元格无法识别" % where)
                    continue
                if cell.get("covered") is True:
                    continue
                if not isinstance(cell.get("runs"), list):
                    errors.append("%s 单元格缺少 runs" % where)
                else:
                    for run in cell["runs"]:
                        _check_run(run, where, errors)
        occupied = set()
        for merge in block.get("merges") or []:
            span = _check_merge(merge, len(rows), width, where, errors)
            if not span:
                continue
            row, col, rowspan, colspan = span
            for dr in range(rowspan):
                for dc in range(colspan):
                    pos = (row + dr, col + dc)
                    if pos in occupied:
                        errors.append("%s 的合并范围重叠" % where)
                    occupied.add(pos)
    elif kind == "image":
        asset = block.get("asset")
        if not isinstance(asset, str) or not asset or "/" in asset or "\\" in asset:
            errors.append("%s 图片 asset 必须是 assets 目录下的文件名" % where)
        elif asset not in assets:
            errors.append("%s 找不到图片 %s" % (where, asset))
        for key in ("w", "h"):
            if not isinstance(block.get(key), (int, float)) or isinstance(block.get(key), bool) or block.get(key) <= 0:
                errors.append("%s 图片%s必须是正数磅值" % (where, key))


def _check_run(run, where, errors):
    if not isinstance(run, dict) or not isinstance(run.get("text", ""), str):
        errors.append("%s 的 run 缺少文本" % where)
        return
    if "size_pt" in run and run["size_pt"] is not None:
        if not isinstance(run["size_pt"], (int, float)) or isinstance(run["size_pt"], bool) or run["size_pt"] <= 0:
            errors.append("%s 的字号必须是正数" % where)


def _check_style(style, where, errors):
    if not isinstance(style, dict):
        return
    for key in ("size_pt",):
        if key in style and style[key] is not None:
            if not isinstance(style[key], (int, float)) or isinstance(style[key], bool) or style[key] <= 0:
                errors.append("%s 的字号必须是正数" % where)
    indent = style.get("indent")
    if indent is not None and not isinstance(indent, dict):
        errors.append("%s 的缩进无法识别" % where)
    line = style.get("line")
    if line is not None:
        if not isinstance(line, dict) or line.get("rule") not in ("exact", "atLeast", "auto"):
            errors.append("%s 的行距无法识别" % where)
    align = style.get("align")
    if align is not None and align not in ALIGNS:
        errors.append("%s 的对齐无法识别" % where)


def _check_merge(merge, rows, cols, where, errors):
    if not isinstance(merge, dict):
        errors.append("%s 的合并信息无法识别" % where)
        return
    try:
        row, col = int(merge["row"]), int(merge["col"])
        rowspan, colspan = int(merge["rowspan"]), int(merge["colspan"])
    except (KeyError, TypeError, ValueError):
        errors.append("%s 的合并信息需要 row、col、rowspan、colspan" % where)
        return
    if row < 0 or col < 0 or rowspan < 1 or colspan < 1 or row + rowspan > rows or col + colspan > cols:
        errors.append("%s 的合并范围超出表格" % where)
        return None
    return (row, col, rowspan, colspan)


def _dump(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _safe_zip_name(name):
    parts = name.replace("\\", "/").split("/")
    if not name or name.startswith("/") or ".." in parts:
        raise ValueError("压缩包路径不安全：%s" % name)
    return name


def _write_zip(path, files):
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for name, data in files:
            info = zipfile.ZipInfo(filename=_safe_zip_name(name))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.flag_bits |= 0x800
            package.writestr(info, data)
    os.replace(tmp, path)


def _read_rels(blob):
    rels = {}
    if not blob:
        return rels
    root = ET.fromstring(blob)
    for rel in root:
        rels[rel.get("Id")] = rel.get("Target")
    return rels


def _read_styles(blob):
    styles = {}
    names = {}
    if not blob:
        return styles, names
    root = ET.fromstring(blob)
    raw = {}
    order = []
    for node in root.findall(q(W, "style")):
        sid = node.get(q(W, "styleId"))
        if not sid:
            continue
        name_node = node.find(q(W, "name"))
        name = name_node.get(q(W, "val")) if name_node is not None else sid
        based = node.find(q(W, "basedOn"))
        raw[sid] = {
            "name": name,
            "based": based.get(q(W, "val")) if based is not None else "",
            "props": _props_from(node),
        }
        order.append(sid)
    resolved = {}

    def walk(sid, seen):
        if sid in resolved:
            return resolved[sid]
        if sid in seen or sid not in raw:
            return {}
        item = raw[sid]
        props = dict(walk(item["based"], seen | {sid}))
        props.update({k: v for k, v in item["props"].items() if v not in (None, {}, "")})
        resolved[sid] = props
        return props

    for sid in order:
        props = walk(sid, set())
        name = raw[sid]["name"]
        if name in styles and styles[name] != props:
            name = "%s (%s)" % (name, sid)
        styles[name] = _public_style(props)
        names[sid] = name
    return styles, names


def _props_from(node):
    props = {}
    ppr = node.find(q(W, "pPr"))
    rpr = node.find(q(W, "rPr"))
    if ppr is not None:
        props.update(_paragraph_props(ppr))
    if rpr is not None:
        props.update(_run_props(rpr))
    return props


def _public_style(props):
    style = {}
    for key in ("eastAsia", "ascii", "size_pt", "bold", "indent", "line", "align"):
        if props.get(key) not in (None, {}, ""):
            style[key] = props[key]
    if props.get("hAnsi") and props.get("hAnsi") != props.get("ascii"):
        style["hAnsi"] = props["hAnsi"]
    return style


def _read_container(node, rels, files, style_names):
    blocks = []
    for child in list(node):
        kind = local(child.tag)
        if kind == "p":
            blocks.extend(_read_paragraph(child, rels, files, style_names))
        elif kind == "tbl":
            table, images = _read_table(child, rels, files, style_names)
            blocks.append(table)
            blocks.extend(images)
        elif kind == "sdt":
            if _is_toc(child):
                blocks.append({"type": "toc"})
            else:
                content = child.find(q(W, "sdtContent"))
                if content is not None:
                    blocks.extend(_read_container(content, rels, files, style_names))
    return blocks


def _read_paragraph(paragraph, rels, files, style_names):
    if _is_toc(paragraph):
        return [{"type": "toc"}]
    ppr = paragraph.find(q(W, "pPr"))
    style_id = ""
    if ppr is not None:
        mark = ppr.find(q(W, "pStyle"))
        if mark is not None:
            style_id = mark.get(q(W, "val")) or ""
    style_name = style_names.get(style_id, style_id)
    level = _heading_level(style_id, style_name, ppr)
    direct = _paragraph_props(ppr) if ppr is not None else {}
    pieces = []
    text_runs = []

    def flush_text():
        if not text_runs:
            return
        block = {"type": "heading" if level else "paragraph", "runs": list(text_runs)}
        if level:
            block["level"] = level
        if style_name:
            block["style"] = style_name
        for key in ("align", "indent", "line"):
            if direct.get(key) not in (None, {}, ""):
                block[key] = direct[key]
        pieces.append(block)
        text_runs.clear()

    for run_node in _iter_runs(paragraph):
        if _has_page_break(run_node):
            flush_text()
            pieces.append({"type": "pagebreak"})
        for image in _images_in(run_node, rels, files):
            flush_text()
            pieces.append(image)
        run = _read_run(run_node)
        if run.get("text"):
            text_runs.append(run)
    flush_text()
    if _section_break(ppr):
        pieces.append({"type": "pagebreak"})
    if not pieces:
        block = {"type": "heading" if level else "paragraph", "runs": []}
        if level:
            block["level"] = level
        if style_name:
            block["style"] = style_name
        pieces.append(block)
    return pieces


def _iter_runs(paragraph):
    for child in list(paragraph):
        if local(child.tag) == "r":
            yield child
        elif local(child.tag) == "hyperlink":
            for run in child.findall(q(W, "r")):
                yield run


def _read_run(node):
    run = {"text": "".join((item.text or "") for item in node.findall(q(W, "t")))}
    rpr = node.find(q(W, "rPr"))
    if rpr is not None:
        run.update(_run_props(rpr))
    ordered = {"text": run.get("text", "")}
    for key in RUN_KEYS[1:]:
        if key in run and run[key] not in (None, ""):
            ordered[key] = run[key]
    return ordered


def _run_props(rpr):
    props = {}
    fonts = rpr.find(q(W, "rFonts"))
    if fonts is not None:
        for key in ("eastAsia", "ascii", "hAnsi"):
            value = fonts.get(q(W, key))
            if value:
                props[key] = value
    size = rpr.find(q(W, "sz"))
    if size is not None and size.get(q(W, "val")):
        props["size_pt"] = num(int(size.get(q(W, "val"))) / 2.0)
    for key, tag in (("bold", "b"), ("italic", "i")):
        mark = rpr.find(q(W, tag))
        if mark is not None and _flag(mark):
            props[key] = True
    underline = rpr.find(q(W, "u"))
    if underline is not None:
        props["underline"] = (underline.get(q(W, "val")) or "single") != "none"
    color = rpr.find(q(W, "color"))
    if color is not None and color.get(q(W, "val")) and color.get(q(W, "val")) != "auto":
        props["color"] = color.get(q(W, "val"))
    return props


def _paragraph_props(ppr):
    props = {}
    align = ppr.find(q(W, "jc"))
    if align is not None and align.get(q(W, "val")):
        value = align.get(q(W, "val"))
        props["align"] = "both" if value == "justify" else value
    spacing = ppr.find(q(W, "spacing"))
    if spacing is not None and spacing.get(q(W, "line")):
        rule = spacing.get(q(W, "lineRule")) or "auto"
        line = int(spacing.get(q(W, "line")))
        if rule == "auto":
            props["line"] = {"rule": "auto", "multiple": num(line / 240.0)}
        else:
            props["line"] = {"rule": "exact" if rule == "exact" else "atLeast", "pt": num(line / 20.0)}
    indent_node = ppr.find(q(W, "ind"))
    if indent_node is not None:
        indent = {}
        for src, dst, scale in (
            ("firstLineChars", "first_chars", 100),
            ("leftChars", "left_chars", 100),
            ("rightChars", "right_chars", 100),
        ):
            if indent_node.get(q(W, src)):
                indent[dst] = num(int(indent_node.get(q(W, src))) / float(scale))
        if not indent and indent_node.get(q(W, "firstLine")):
            indent["first_twips"] = int(indent_node.get(q(W, "firstLine")))
        if indent:
            props["indent"] = indent
    return props


def _heading_level(style_id, style_name, ppr):
    for text in (style_name, style_id):
        if not text:
            continue
        match = HEADING_NAME.match(text.strip())
        if match:
            level = int(match.group(1))
            if 1 <= level <= 9:
                return level
    if ppr is not None:
        outline = ppr.find(q(W, "outlineLvl"))
        if outline is not None and outline.get(q(W, "val")) not in (None, ""):
            return int(outline.get(q(W, "val"))) + 1
    return None


def _has_page_break(run):
    for br in run.findall(q(W, "br")):
        if br.get(q(W, "type")) == "page":
            return True
    return False


def _section_break(ppr):
    if ppr is None:
        return False
    sect = ppr.find(q(W, "sectPr"))
    if sect is None:
        return False
    kind = sect.find(q(W, "type"))
    value = kind.get(q(W, "val")) if kind is not None else "nextPage"
    return value in ("nextPage", "oddPage", "evenPage")


def _images_in(run, rels, files):
    images = []
    for blip in run.iter(q(A, "blip")):
        embed = blip.get(q(R, "embed"))
        target = rels.get(embed or "")
        if not target:
            continue
        width, height = _extent(run)
        images.append(_image_block(target, files, width, height))
    return [image for image in images if image]


def _extent(run):
    extent = next(run.iter(q(WP, "extent")), None)
    if extent is None:
        return 100, 100
    return emu_to_pt(extent.get("cx") or 0), emu_to_pt(extent.get("cy") or 0)


def _image_block(target, files, width, height):
    target = target.replace("\\", "/").lstrip("/")
    if target.startswith("../"):
        target = target[3:]
    key = target if target.startswith("word/") else "word/" + target
    blob = files.get(key)
    if blob is None:
        return None
    name = key.split("/")[-1] or "image.bin"
    return {"type": "image", "asset": name, "w": width or 100, "h": height or 100, "_bytes": blob}


def _read_table(table, rels, files, style_names):
    parsed = []
    loose = []
    for tr in table.findall(q(W, "tr")):
        row = []
        for tc in tr.findall(q(W, "tc")):
            tcpr = tc.find(q(W, "tcPr"))
            span = 1
            vmerge = None
            if tcpr is not None:
                grid = tcpr.find(q(W, "gridSpan"))
                if grid is not None and grid.get(q(W, "val")):
                    span = int(grid.get(q(W, "val")))
                merge = tcpr.find(q(W, "vMerge"))
                if merge is not None:
                    vmerge = merge.get(q(W, "val")) or "continue"
            runs = []
            for paragraph in tc.findall(q(W, "p")):
                if runs and _paragraph_text(paragraph):
                    runs.append({"text": "\n"})
                for run_node in _iter_runs(paragraph):
                    for image in _images_in(run_node, rels, files):
                        loose.append(image)
                    run = _read_run(run_node)
                    if run.get("text"):
                        runs.append(run)
            row.append({"span": max(span, 1), "vmerge": vmerge, "runs": runs})
        parsed.append(row)
    grid, merges = _expand_table(parsed)
    return {"type": "table", "rows": grid, "merges": merges}, loose


def _paragraph_text(paragraph):
    return "".join((item.text or "") for item in paragraph.iter(q(W, "t")))


def _expand_table(parsed):
    grid = []
    merges = []
    anchors = {}
    merge_at = {}
    for ri, cells in enumerate(parsed):
        row = []
        col = 0
        bumped = set()
        for cell in cells:
            span = cell["span"]
            if cell["vmerge"] == "continue":
                anchor = anchors.get(col)
                if anchor and anchor not in bumped:
                    merge_at[anchor]["rowspan"] += 1
                    bumped.add(anchor)
                row.extend({"covered": True} for _ in range(span))
                col += span
                continue
            entry = {"runs": cell["runs"]}
            row.append(entry)
            if span > 1 or cell["vmerge"] == "restart":
                item = {"row": ri, "col": col, "rowspan": 1, "colspan": span}
                merges.append(item)
                merge_at[(ri, col)] = item
                if cell["vmerge"] == "restart":
                    for offset in range(span):
                        anchors[col + offset] = (ri, col)
                else:
                    for offset in range(span):
                        anchors.pop(col + offset, None)
            else:
                for offset in range(span):
                    anchors.pop(col + offset, None)
            row.extend({"covered": True} for _ in range(span - 1))
            col += span
        grid.append(row)
    width = max((len(row) for row in grid), default=0)
    for row in grid:
        while len(row) < width:
            row.append({"runs": []})
    merges = [item for item in merges if item["rowspan"] > 1 or item["colspan"] > 1]
    if not grid:
        grid = [[{"runs": []}]]
    return grid, merges


def _is_toc(node):
    gallery = node.find(".//" + q(W, "docPartGallery"))
    if gallery is not None and "Table of Contents" in (gallery.get(q(W, "val")) or ""):
        return True
    for instr in node.iter(q(W, "instrText")):
        if instr.text and "TOC" in instr.text.upper():
            return True
    return False


def _flag(node):
    value = node.get(q(W, "val"))
    return value not in ("0", "false", "off")


def _store_images(blocks):
    assets = {}
    for block in blocks:
        if block.get("type") != "image":
            continue
        blob = bytes(block.pop("_bytes", b"") or b"")
        name = block.get("asset") or "image.bin"
        if name in assets and assets[name] != blob:
            stem, dot, ext = name.rpartition(".")
            number = 2
            while True:
                candidate = "%s-%d.%s" % (stem, number, ext) if dot else "%s-%d" % (name, number)
                if candidate not in assets:
                    name = candidate
                    break
                number += 1
            block["asset"] = name
        assets[name] = blob
    return assets


def _title_from(blocks):
    for block in blocks:
        if block.get("type") in ("heading", "paragraph"):
            text = "".join(run.get("text", "") for run in block.get("runs") or []).strip()
            if text:
                return text[:80]
    return ""


def _template_styles(template):
    if template is None:
        return None
    if isinstance(template, WenjuDoc):
        return dict(template.styles)
    if isinstance(template, dict):
        return dict(template)
    path = str(template)
    if path.lower().endswith(".wenju"):
        return dict(load(path).styles)
    if path.lower().endswith(".json"):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("模板样式必须是对象")
        return data
    raise ValueError("模板只接受样式字典、.json 或 .wenju")


def _style_ids(styles):
    mapping = {}
    used = set()
    for index, name in enumerate(styles):
        level = None
        match = HEADING_NAME.match(name.strip())
        if match:
            level = int(match.group(1))
        if name in ("正文", "Normal"):
            sid = "Normal"
        elif level:
            sid = "Heading%d" % level
        else:
            sid = "wenju%d" % index
        base = sid
        extra = 2
        while sid in used:
            sid = "%s_%d" % (base, extra)
            extra += 1
        used.add(sid)
        mapping[name] = sid
    return mapping


def _brush_style(block, styles, brush):
    if not brush:
        return {}
    name = block.get("style")
    if name in styles:
        return styles[name]
    if block.get("type") == "heading":
        level = block.get("level")
        for key in ("标题%d" % level, "标题 %d" % level, "Heading %d" % level, "Heading%d" % level):
            if key in styles:
                return styles[key]
    for key in ("正文", "Normal"):
        if key in styles:
            return styles[key]
    return {}


def _effective_run(run, style, brush):
    if not brush:
        return run
    out = dict(run)
    if style.get("eastAsia"):
        out["eastAsia"] = style["eastAsia"]
    if style.get("ascii"):
        out["ascii"] = style["ascii"]
        out["hAnsi"] = style.get("hAnsi") or style["ascii"]
    if style.get("size_pt") is not None:
        out["size_pt"] = style["size_pt"]
    if "bold" in style:
        out["bold"] = bool(style["bold"])
    return out


def _first_size(block):
    for run in block.get("runs") or []:
        if run.get("size_pt"):
            return run["size_pt"]
    return None


def _write_paragraph(body, block, styles, style_ids, brush):
    linked = styles.get(block.get("style") or "", {})
    if brush:
        style = _brush_style(block, styles, True)
        geom = dict(style)
    else:
        style = {}
        geom = {}
        for key in ("align", "indent", "line"):
            if block.get(key) not in (None, {}, ""):
                geom[key] = block[key]
        geom["size_pt"] = linked.get("size_pt") or _first_size(block) or 16
    paragraph = ET.SubElement(body, q(W, "p"))
    sid = style_ids.get(block.get("style") or "")
    if block.get("type") == "heading" and not sid:
        sid = "Heading%d" % block["level"]
    _write_ppr(paragraph, sid, geom, block.get("level") if block.get("type") == "heading" else None)
    runs = block.get("runs") or []
    if not runs:
        runs = [{"text": ""}]
    for run in runs:
        _write_run(paragraph, _effective_run(run, style, brush))


def _write_ppr(paragraph, style_id, geom, level):
    ppr = ET.SubElement(paragraph, q(W, "pPr"))
    if style_id:
        ET.SubElement(ppr, q(W, "pStyle")).set(q(W, "val"), style_id)
    line = geom.get("line") or {}
    if line.get("rule") == "auto" and line.get("multiple"):
        spacing = ET.SubElement(ppr, q(W, "spacing"))
        spacing.set(q(W, "line"), str(int(round(float(line["multiple"]) * 240))))
        spacing.set(q(W, "lineRule"), "auto")
    elif line.get("rule") in ("exact", "atLeast") and line.get("pt"):
        spacing = ET.SubElement(ppr, q(W, "spacing"))
        spacing.set(q(W, "line"), str(int(round(float(line["pt"]) * 20))))
        spacing.set(q(W, "lineRule"), "exact" if line["rule"] == "exact" else "atLeast")
    indent = geom.get("indent") or {}
    if any(indent.get(key) not in (None, 0) for key in ("first_chars", "left_chars", "right_chars", "first_twips")):
        node = ET.SubElement(ppr, q(W, "ind"))
        size = float(geom.get("size_pt") or 16)
        for src, chars_attr, twip_attr in (
            ("first_chars", "firstLineChars", "firstLine"),
            ("left_chars", "leftChars", "left"),
            ("right_chars", "rightChars", "right"),
        ):
            if indent.get(src):
                node.set(q(W, chars_attr), str(int(round(float(indent[src]) * 100))))
                node.set(q(W, twip_attr), str(int(round(float(indent[src]) * size * 20))))
        if indent.get("first_twips") and "first_chars" not in indent:
            node.set(q(W, "firstLine"), str(int(indent["first_twips"])))
    align = ALIGNS.get(geom.get("align") or "")
    if align:
        ET.SubElement(ppr, q(W, "jc")).set(q(W, "val"), align)
    if level:
        ET.SubElement(ppr, q(W, "outlineLvl")).set(q(W, "val"), str(int(level) - 1))


def _write_run(paragraph, run):
    node = ET.SubElement(paragraph, q(W, "r"))
    rpr = ET.SubElement(node, q(W, "rPr"))
    east = fontfallback.resolve(run.get("eastAsia"))
    ascii_font = run.get("ascii")
    hansi = run.get("hAnsi") or ascii_font
    if east or ascii_font or hansi:
        fonts = ET.SubElement(rpr, q(W, "rFonts"))
        if ascii_font:
            fonts.set(q(W, "ascii"), ascii_font)
        if hansi:
            fonts.set(q(W, "hAnsi"), hansi)
        if east:
            fonts.set(q(W, "eastAsia"), east)
        fonts.set(q(W, "hint"), "eastAsia" if east else "default")
    if run.get("size_pt"):
        half = str(int(round(float(run["size_pt"]) * 2)))
        ET.SubElement(rpr, q(W, "sz")).set(q(W, "val"), half)
        ET.SubElement(rpr, q(W, "szCs")).set(q(W, "val"), half)
    if run.get("bold"):
        ET.SubElement(rpr, q(W, "b"))
        ET.SubElement(rpr, q(W, "bCs"))
    if run.get("italic"):
        ET.SubElement(rpr, q(W, "i"))
    if run.get("underline"):
        ET.SubElement(rpr, q(W, "u")).set(q(W, "val"), "single")
    if run.get("color"):
        ET.SubElement(rpr, q(W, "color")).set(q(W, "val"), run["color"])
    text = ET.SubElement(node, q(W, "t"))
    text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    text.text = run.get("text") or ""


def _write_table(body, block, styles, style_ids, brush):
    table = ET.SubElement(body, q(W, "tbl"))
    grid_pr = ET.SubElement(table, q(W, "tblGrid"))
    width = len(block["rows"][0])
    for _ in range(width):
        ET.SubElement(grid_pr, q(W, "gridCol")).set(q(W, "w"), "2400")
    anchors = {}
    covered = {}
    for merge in block.get("merges") or []:
        anchors[(merge["row"], merge["col"])] = merge
        for dr in range(int(merge["rowspan"])):
            for dc in range(int(merge["colspan"])):
                if dr or dc:
                    covered[(merge["row"] + dr, merge["col"] + dc)] = merge
    for ri, row in enumerate(block["rows"]):
        tr = ET.SubElement(table, q(W, "tr"))
        for ci, cell in enumerate(row):
            merge = anchors.get((ri, ci))
            cover = covered.get((ri, ci))
            if cover and cover["col"] != ci:
                continue
            tc = ET.SubElement(tr, q(W, "tc"))
            tcpr = ET.SubElement(tc, q(W, "tcPr"))
            colspan = 1
            if merge:
                colspan = int(merge["colspan"])
            elif cover:
                colspan = int(cover["colspan"])
            if colspan > 1:
                ET.SubElement(tcpr, q(W, "gridSpan")).set(q(W, "val"), str(colspan))
            if merge and int(merge["rowspan"]) > 1:
                ET.SubElement(tcpr, q(W, "vMerge")).set(q(W, "val"), "restart")
            elif cover and cover["col"] == ci:
                ET.SubElement(tcpr, q(W, "vMerge"))
            paragraph = ET.SubElement(tc, q(W, "p"))
            runs = [] if cover else cell.get("runs") or []
            if not runs:
                _write_run(paragraph, {"text": ""})
            else:
                for run in runs:
                    _write_run(paragraph, _effective_run(run, _brush_style({"type": "paragraph", "style": "正文"}, styles, brush), brush))


def _write_image(body, block, rel_id, picture_id):
    paragraph = ET.SubElement(body, q(W, "p"))
    run = ET.SubElement(paragraph, q(W, "r"))
    drawing = ET.SubElement(run, q(W, "drawing"))
    inline = ET.SubElement(drawing, q(WP, "inline"))
    cx, cy = str(pt_to_emu(block["w"])), str(pt_to_emu(block["h"]))
    extent = ET.SubElement(inline, q(WP, "extent"))
    extent.set("cx", cx)
    extent.set("cy", cy)
    doc_pr = ET.SubElement(inline, q(WP, "docPr"))
    doc_pr.set("id", str(picture_id))
    doc_pr.set("name", block["asset"])
    graphic = ET.SubElement(inline, q(A, "graphic"))
    data = ET.SubElement(graphic, q(A, "graphicData"))
    data.set("uri", PIC)
    pic = ET.SubElement(data, q(PIC, "pic"))
    nv = ET.SubElement(pic, q(PIC, "nvPicPr"))
    c_nv = ET.SubElement(nv, q(PIC, "cNvPr"))
    c_nv.set("id", str(picture_id))
    c_nv.set("name", block["asset"])
    ET.SubElement(nv, q(PIC, "cNvPicPr"))
    fill = ET.SubElement(pic, q(PIC, "blipFill"))
    ET.SubElement(fill, q(A, "blip")).set(q(R, "embed"), rel_id)
    stretch = ET.SubElement(fill, q(A, "stretch"))
    ET.SubElement(stretch, q(A, "fillRect"))
    sp = ET.SubElement(pic, q(PIC, "spPr"))
    xfrm = ET.SubElement(sp, q(A, "xfrm"))
    ET.SubElement(xfrm, q(A, "off")).attrib.update({"x": "0", "y": "0"})
    ext = ET.SubElement(xfrm, q(A, "ext"))
    ext.set("cx", cx)
    ext.set("cy", cy)
    ET.SubElement(sp, q(A, "prstGeom")).set("prst", "rect")


def _write_page_break(body):
    paragraph = ET.SubElement(body, q(W, "p"))
    run = ET.SubElement(paragraph, q(W, "r"))
    ET.SubElement(run, q(W, "br")).set(q(W, "type"), "page")


def _write_toc(body):
    paragraph = ET.SubElement(body, q(W, "p"))
    begin = ET.SubElement(paragraph, q(W, "r"))
    ET.SubElement(begin, q(W, "fldChar")).set(q(W, "fldCharType"), "begin")
    instr = ET.SubElement(paragraph, q(W, "r"))
    text = ET.SubElement(instr, q(W, "instrText"))
    text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    text.text = ' TOC \\o "1-3" \\h \\z \\u '
    separate = ET.SubElement(paragraph, q(W, "r"))
    ET.SubElement(separate, q(W, "fldChar")).set(q(W, "fldCharType"), "separate")
    shown = ET.SubElement(paragraph, q(W, "r"))
    ET.SubElement(shown, q(W, "t")).text = "目录"
    end = ET.SubElement(paragraph, q(W, "r"))
    ET.SubElement(end, q(W, "fldChar")).set(q(W, "fldCharType"), "end")


def _document_root(body):
    root = ET.Element(q(W, "document"))
    root.append(body)
    return root


def _xml(tree):
    return ET.tostring(tree.getroot(), encoding="utf-8", xml_declaration=True)


def _content_types(assets):
    root = ET.Element(q(CT, "Types"))
    defaults = {
        "rels": "application/vnd.openxmlformats-package.relationships+xml",
        "xml": "application/xml",
    }
    for name in assets:
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext in ("png",):
            defaults[ext] = "image/png"
        elif ext in ("jpg", "jpeg"):
            defaults[ext] = "image/jpeg"
        elif ext == "gif":
            defaults[ext] = "image/gif"
        elif ext == "emf":
            defaults[ext] = "image/x-emf"
    for ext, content in defaults.items():
        node = ET.SubElement(root, q(CT, "Default"))
        node.set("Extension", ext)
        node.set("ContentType", content)
    for part, content in (
        ("/word/document.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"),
        ("/word/styles.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"),
        ("/docProps/core.xml", "application/vnd.openxmlformats-package.core-properties+xml"),
    ):
        node = ET.SubElement(root, q(CT, "Override"))
        node.set("PartName", part)
        node.set("ContentType", content)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _package_rels():
    root = ET.Element(q(REL, "Relationships"))
    _rel(root, "rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument", "word/document.xml")
    _rel(root, "rId2", "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties", "docProps/core.xml")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _document_rels(images):
    root = ET.Element(q(REL, "Relationships"))
    _rel(root, "rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles", "styles.xml")
    for rel_id, asset in images:
        _rel(root, rel_id, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image", "media/" + asset)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _rel(root, rel_id, rel_type, target):
    node = ET.SubElement(root, q(REL, "Relationship"))
    node.set("Id", rel_id)
    node.set("Type", rel_type)
    node.set("Target", target)


def _core_xml(title):
    root = ET.Element(q(CP, "coreProperties"))
    ET.SubElement(root, q(DC, "title")).text = title or ""
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _styles_xml(styles, style_ids):
    root = ET.Element(q(W, "styles"))
    for name, style in styles.items():
        node = ET.SubElement(root, q(W, "style"))
        node.set(q(W, "type"), "paragraph")
        node.set(q(W, "styleId"), style_ids[name])
        if style_ids[name] == "Normal":
            node.set(q(W, "default"), "1")
        ET.SubElement(node, q(W, "name")).set(q(W, "val"), name)
        _write_ppr(node, None, style, None)
        rpr = ET.SubElement(node, q(W, "rPr"))
        _fill_rpr(rpr, style)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _fill_rpr(rpr, style):
    east = fontfallback.resolve(style.get("eastAsia"))
    ascii_font = style.get("ascii")
    if east or ascii_font:
        fonts = ET.SubElement(rpr, q(W, "rFonts"))
        if ascii_font:
            fonts.set(q(W, "ascii"), ascii_font)
            fonts.set(q(W, "hAnsi"), style.get("hAnsi") or ascii_font)
        if east:
            fonts.set(q(W, "eastAsia"), east)
    if style.get("size_pt"):
        half = str(int(round(float(style["size_pt"]) * 2)))
        ET.SubElement(rpr, q(W, "sz")).set(q(W, "val"), half)
    if style.get("bold"):
        ET.SubElement(rpr, q(W, "b"))
