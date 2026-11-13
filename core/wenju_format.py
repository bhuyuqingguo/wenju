from __future__ import annotations

import json
import os
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import image_size

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
MAX_ASSET_BYTES = 64 * 1024 * 1024
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
    sections: list = field(default_factory=list)

    def __post_init__(self):
        if not self.created:
            self.created = utcnow()
        if not self.source:
            self.source = {"kind": "new", "name": ""}
        if self.sections is None:
            self.sections = []


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
    _check_sections(getattr(doc, "sections", None), errors)
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
        for name, data in doc_assets.items():
            if not isinstance(name, str) or _unsafe_asset_name(name):
                errors.append("图片名不安全：%s" % name)
            elif isinstance(data, (bytes, bytearray)) and len(data) > MAX_ASSET_BYTES:
                errors.append("图片超过 64MB：%s" % name)
    for index, block in enumerate(doc.blocks):
        _check_block(block, index, doc_assets, errors)
    return errors


def load(path):
    path = str(path)
    try:
        with zipfile.ZipFile(path) as package:
            infos = package.infolist()
            for info in infos:
                _safe_zip_name(info.filename)
                normalized = info.filename.replace("\\", "/")
                if normalized.startswith("assets/") and not normalized.endswith("/") and info.file_size > MAX_ASSET_BYTES:
                    raise ValueError("图片超过 64MB：%s" % info.filename)
            names = {info.filename for info in infos}
            for required in ("manifest.json", "document.json", "styles.json"):
                if required not in names:
                    raise ValueError("文矩包缺少 %s" % required)
            manifest = json.loads(package.read("manifest.json").decode("utf-8"))
            document = json.loads(package.read("document.json").decode("utf-8"))
            styles = json.loads(package.read("styles.json").decode("utf-8"))
            assets = {}
            for name in names:
                if name.startswith("assets/") and not name.endswith("/"):
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
    sections = document.get("sections") if isinstance(document.get("sections"), list) else []
    doc = WenjuDoc(
        blocks=document["blocks"],
        styles=styles,
        assets=assets,
        title=manifest.get("title") or "",
        source={"kind": source.get("kind", ""), "name": source.get("name", "")},
        app_version=manifest.get("app_version") or APP_VERSION,
        created=manifest.get("created") or utcnow(),
        version=manifest.get("version") or 0,
        sections=sections,
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
        ("document.json", _dump({"blocks": doc.blocks, "sections": list(getattr(doc, "sections", None) or [])})),
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
    theme = _read_theme(files)
    styles, style_names, outlines, defaults = _read_styles(files.get("word/styles.xml", b""), theme)
    rels = _read_rels(files.get("word/_rels/document.xml.rels", b""))
    root = ET.fromstring(files["word/document.xml"])
    body = root.find(q(W, "body"))
    ctx = {"rels": rels, "files": files, "names": style_names, "styles": styles, "outlines": outlines, "defaults": defaults, "theme": theme}
    if body is not None:
        blocks, sections = _read_body(body, ctx)
    else:
        blocks, sections = [], []
    assets = _store_images(blocks)
    title = _title_from(blocks) or Path(path).stem
    return WenjuDoc(
        blocks=blocks,
        styles=styles,
        assets=assets,
        title=title,
        source={"kind": "docx", "name": os.path.basename(path)},
        sections=sections,
    )


def to_docx(doc, path, template=None):
    errors = validate(doc)
    if errors:
        raise ValueError("文矩文档无效：%s" % "；".join(errors))
    brush = _template_styles(template)
    styles = dict(doc.styles)
    if brush:
        for name, override in brush.items():
            styles[name] = _merge_style(styles.get(name), override)
    style_ids = _style_ids(styles)
    sections = [dict(item) for item in (getattr(doc, "sections", None) or []) if isinstance(item, dict)]
    active = _sections_active(sections)
    header_ids = []
    footer_ids = []
    next_rid = 2
    if active:
        for _section in sections:
            header_ids.append("rId%d" % next_rid)
            next_rid += 1
            footer_ids.append("rId%d" % next_rid)
            next_rid += 1
    image_start = next_rid
    image_rels = []
    body = ET.Element(q(W, "body"))
    picture_id = 1
    last_p = None
    open_section = None
    for index, block in enumerate(doc.blocks):
        section = _section_at(index, sections) if active else None
        if active and open_section is not None and section is not open_section:
            if last_p is None:
                last_p = ET.SubElement(body, q(W, "p"))
            _attach_sect(last_p, open_section, sections, header_ids, footer_ids, section.get("break") or "nextPage")
            last_p = None
        if active:
            open_section = section
        kind = block["type"]
        if kind in ("heading", "paragraph"):
            _write_paragraph(body, block, styles, style_ids, brush)
            last_p = body[-1]
        elif kind == "table":
            _write_table(body, block, styles, style_ids, brush)
            last_p = None
        elif kind == "image":
            rel_id = "rId%d" % (image_start + len(image_rels))
            image_rels.append((rel_id, block["asset"]))
            _write_image(body, block, rel_id, picture_id)
            picture_id += 1
            last_p = body[-1]
        elif kind == "pagebreak":
            if active:
                following = _section_at(index + 1, sections) if index + 1 < len(doc.blocks) else section
                if following is section:
                    _write_page_break(body)
                    last_p = body[-1]
                elif last_p is None:
                    last_p = ET.SubElement(body, q(W, "p"))
            else:
                _write_page_break(body)
                last_p = body[-1]
        elif kind == "toc":
            _write_toc(body, doc.blocks, sections)
            last_p = body[-1]
    if active:
        if open_section is None and sections:
            open_section = sections[0]
        body.append(_sect_element(open_section or {}, sections, header_ids, footer_ids, True, ""))
    else:
        sect = ET.SubElement(body, q(W, "sectPr"))
        ET.SubElement(sect, q(W, "pgSz")).set(q(W, "w"), "11906")
        sect.find(q(W, "pgSz")).set(q(W, "h"), "16838")
    part_files = {}
    if active:
        for index, section in enumerate(sections):
            part_files["word/header%d.xml" % (index + 1)] = _header_xml(section.get("header") or "")
            part_files["word/footer%d.xml" % (index + 1)] = _footer_xml(section.get("footer") or "", _footer_has_page(section, sections))
    files = {
        "[Content_Types].xml": _content_types(doc.assets, len(sections) if active else 0),
        "_rels/.rels": _package_rels(),
        "docProps/core.xml": _core_xml(doc.title),
        "word/document.xml": _xml(ET.ElementTree(_document_root(body))),
        "word/styles.xml": _styles_xml(styles, style_ids),
        "word/_rels/document.xml.rels": _document_rels(image_rels, header_ids if active else None, footer_ids if active else None),
    }
    files.update(part_files)
    for _rel_id, asset in image_rels:
        files["word/media/" + asset] = bytes(doc.assets[asset])
    path = str(path)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    _write_zip(path, list(files.items()))


def convert_file(src, dest, template=None):
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


def _check_sections(sections, errors):
    if sections is None:
        return
    if not isinstance(sections, list):
        errors.append("document.sections 必须是列表")
        return
    allowed = ("nextPage", "continuous", "evenPage", "oddPage", "nextColumn")
    for index, section in enumerate(sections):
        where = "第 %d 节" % (index + 1)
        if not isinstance(section, dict):
            errors.append("%s 无法识别" % where)
            continue
        at = section.get("at", 0)
        if isinstance(at, bool) or not isinstance(at, int) or at < 0:
            errors.append("%s 的起始位置无法识别" % where)
        brk = section.get("break", "nextPage")
        if brk is not None and brk not in allowed:
            errors.append("%s 的分节方式无法识别" % where)
        for key in ("header", "footer"):
            if key in section and section[key] is not None and not isinstance(section[key], str):
                errors.append("%s 的页眉页脚必须是文字" % where)


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
                    if dr or dc:
                        covered = rows[row + dr][col + dc]
                        if not (isinstance(covered, dict) and covered.get("covered") is True) or _cell_text(covered):
                            errors.append("%s 的合并盖住了仍有内容的单元格" % where)
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


def _cell_text(cell):
    if not isinstance(cell, dict):
        return ""
    parts = []
    for run in cell.get("runs") or []:
        if isinstance(run, dict) and run.get("text"):
            parts.append(run["text"])
    return "".join(parts)


def _unsafe_asset_name(name):
    normalized = str(name).replace("\\", "/")
    parts = normalized.split("/")
    return not normalized or normalized.startswith("/") or "/" in normalized or ".." in parts


def _safe_zip_name(name):
    normalized = name.replace("\\", "/")
    parts = normalized.split("/")
    if not name or normalized.startswith("/") or ".." in parts:
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


def _read_theme(files):
    theme = {"major": {}, "minor": {}}
    blob = files.get("word/theme/theme1.xml")
    if not blob:
        return theme
    root = ET.fromstring(blob)
    for scheme in root.iter():
        name = local(scheme.tag)
        if name not in ("majorFont", "minorFont"):
            continue
        slot = theme["major" if name == "majorFont" else "minor"]
        latin = scheme.find(q(A, "latin"))
        east = scheme.find(q(A, "ea"))
        if latin is not None and latin.get("typeface"):
            slot["latin"] = latin.get("typeface")
        if east is not None and east.get("typeface"):
            slot["ea"] = east.get("typeface")
        for font in scheme.findall(q(A, "font")):
            if font.get("script") == "Hans" and font.get("typeface"):
                slot["hans"] = font.get("typeface")
    return theme


def _theme_face(theme, token):
    if not token:
        return None
    faces = theme.get("major" if str(token).startswith("major") else "minor") or {}
    if "East" in token or str(token).endswith("Bidi"):
        return faces.get("hans") or faces.get("ea")
    return faces.get("latin")


def _read_styles(blob, theme=None):
    styles = {}
    names = {}
    outlines = {}
    theme = theme or {"major": {}, "minor": {}}
    if not blob:
        return styles, names, outlines, {}
    root = ET.fromstring(blob)
    defaults = _doc_defaults(root, theme)
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
            "props": _props_from(node, theme),
            "level": _style_level(node),
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
        if raw[sid]["level"]:
            outlines[name] = raw[sid]["level"]
    return styles, names, outlines, defaults


def _doc_defaults(root, theme):
    node = root.find(q(W, "docDefaults"))
    if node is None:
        return {}
    rpr = node.find(q(W, "rPrDefault") + "/" + q(W, "rPr"))
    if rpr is None:
        return {}
    return _run_props(rpr, theme)


def _style_level(node):
    ppr = node.find(q(W, "pPr"))
    if ppr is None:
        return None
    outline = ppr.find(q(W, "outlineLvl"))
    if outline is None or outline.get(q(W, "val")) in (None, ""):
        return None
    raw = int(outline.get(q(W, "val")))
    if 0 <= raw <= 8:
        return raw + 1
    return None


def _props_from(node, theme):
    props = {}
    ppr = node.find(q(W, "pPr"))
    rpr = node.find(q(W, "rPr"))
    if ppr is not None:
        props.update(_paragraph_props(ppr))
    if rpr is not None:
        props.update(_run_props(rpr, theme))
    return props


def _public_style(props):
    style = {}
    for key in ("eastAsia", "ascii", "size_pt", "bold", "indent", "line", "align"):
        if props.get(key) not in (None, {}, ""):
            style[key] = props[key]
    if props.get("hAnsi"):
        style["hAnsi"] = props["hAnsi"]
    return style


def _read_body(body, ctx):
    return _read_blocks(body, ctx, True)


def _read_container(node, ctx):
    blocks, _sections = _read_blocks(node, ctx, False)
    return blocks


def _read_blocks(node, ctx, track_sections):
    blocks = []
    sections = []
    current = _blank_section(0, "nextPage")
    saw = False
    for child in list(node):
        kind = local(child.tag)
        if kind == "sectPr" and track_sections:
            _apply_sect(current, child, ctx)
            sections.append(_public_section(current))
            saw = True
            continue
        if kind == "p":
            blocks.extend(_read_paragraph(child, ctx))
            if track_sections:
                ppr = child.find(q(W, "pPr"))
                sect = ppr.find(q(W, "sectPr")) if ppr is not None else None
                if sect is not None:
                    _apply_sect(current, sect, ctx)
                    sections.append(_public_section(current))
                    saw = True
                    current = _blank_section(len(blocks), "nextPage")
        elif kind == "tbl":
            table, images = _read_table(child, ctx)
            blocks.append(table)
            blocks.extend(images)
        elif kind == "sdt":
            if _is_toc(child):
                blocks.append({"type": "toc"})
            else:
                content = child.find(q(W, "sdtContent"))
                if content is not None:
                    blocks.extend(_read_container(content, ctx))
    if track_sections and saw:
        return blocks, sections
    return blocks, []


def _blank_section(at, brk):
    return {
        "at": at,
        "header": "",
        "footer": "",
        "break": brk or "nextPage",
        "footer_page": False,
    }


def _apply_sect(section, sect, ctx):
    section["break"] = _sect_break(sect)
    header_id = _part_ref(sect, "headerReference")
    footer_id = _part_ref(sect, "footerReference")
    header, _page = _part_story(ctx, header_id)
    footer, page = _part_story(ctx, footer_id)
    section["header"] = header
    section["footer"] = footer
    section["footer_page"] = page
    page_box = _page_box(sect)
    section.update(page_box)


def _public_section(section):
    public = {
        "at": int(section.get("at") or 0),
        "header": section.get("header") or "",
        "footer": section.get("footer") or "",
        "break": section.get("break") or "nextPage",
        "footer_page": bool(section.get("footer_page")),
    }
    if section.get("pgSz"):
        public["pgSz"] = section["pgSz"]
    if section.get("pgMar"):
        public["pgMar"] = section["pgMar"]
    return public


def _sect_break(sect):
    kind = sect.find(q(W, "type"))
    value = kind.get(q(W, "val")) if kind is not None and kind.get(q(W, "val")) else "nextPage"
    if value not in ("nextPage", "continuous", "evenPage", "oddPage", "nextColumn"):
        return "nextPage"
    return value


def _part_ref(sect, tag):
    chosen = None
    for node in sect.findall(q(W, tag)):
        rel_id = node.get(q(R, "id"))
        if node.get(q(W, "type")) in (None, "default"):
            return rel_id
        chosen = rel_id
    return chosen


def _part_story(ctx, rel_id):
    if not rel_id:
        return "", False
    target = (ctx.get("rels") or {}).get(rel_id)
    blob = (ctx.get("files") or {}).get(_word_part(target)) if target else None
    if not blob:
        return "", False
    try:
        root = ET.fromstring(blob)
    except ET.ParseError:
        return "", False
    parts = []
    page = False
    in_result = False
    instr = ""
    for node in root.iter():
        name = local(node.tag)
        if name == "fldChar":
            kind = node.get(q(W, "fldCharType"))
            if kind == "begin":
                in_result = False
                instr = ""
            elif kind == "separate":
                in_result = "PAGE" in instr.upper()
            elif kind == "end":
                in_result = False
                instr = ""
        elif name == "instrText":
            instr += node.text or ""
            if "PAGE" in (node.text or "").upper():
                page = True
        elif name == "t" and not in_result:
            parts.append(node.text or "")
    return "".join(parts), page


def _word_part(target):
    target = (target or "").replace("\\", "/").strip()
    while target.startswith("./"):
        target = target[2:]
    while target.startswith("../"):
        target = target[3:]
    target = target.lstrip("/")
    if not target:
        return ""
    if target.startswith("word/"):
        return target
    return "word/" + target


def _page_box(sect):
    found = {}
    pg = sect.find(q(W, "pgSz"))
    if pg is not None:
        box = {}
        for key in ("w", "h"):
            raw = pg.get(q(W, key))
            if raw and raw.isdigit():
                box[key] = int(raw)
        orient = pg.get(q(W, "orient"))
        if orient:
            box["orient"] = orient
        if box:
            found["pgSz"] = box
    mar = sect.find(q(W, "pgMar"))
    if mar is not None:
        edges = {}
        for key in ("top", "right", "bottom", "left", "header", "footer", "gutter"):
            raw = mar.get(q(W, key))
            if raw and (raw.lstrip("-").isdigit()):
                edges[key] = int(raw)
        if edges:
            found["pgMar"] = edges
    return found


def _read_paragraph(paragraph, ctx):
    if _is_toc(paragraph):
        return [{"type": "toc"}]
    ppr = paragraph.find(q(W, "pPr"))
    style_id = ""
    if ppr is not None:
        mark = ppr.find(q(W, "pStyle"))
        if mark is not None:
            style_id = mark.get(q(W, "val")) or ""
    style_name = ctx["names"].get(style_id, style_id)
    level = _heading_level(style_id, style_name, ppr, ctx["outlines"].get(style_name))
    direct = _paragraph_props(ppr) if ppr is not None else {}
    inherited = _inherited_props(style_name, ctx)
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

    for kind, node in _walk_paragraph(paragraph):
        if kind == "run":
            events = _run_events(node, ctx)
        elif kind == "alt":
            events = (("image", image) for image in _alternate_images(node, ctx))
        else:
            events = (("image", image) for image in _images_in(node, ctx["rels"], ctx["files"]))
        for event, payload in events:
            if event == "text":
                text_runs.append(_inherit_run(payload, inherited))
            elif event == "break":
                flush_text()
                pieces.append({"type": "pagebreak"})
            elif event == "image" and payload:
                flush_text()
                pieces.append(payload)
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


def _walk_paragraph(paragraph):
    for child in list(paragraph):
        name = local(child.tag)
        if name == "AlternateContent":
            yield "alt", child
        elif name in ("drawing", "pict", "object"):
            yield "media", child
        else:
            for run in _runs_under(child):
                yield "run", run


def _iter_runs(paragraph):
    for kind, node in _walk_paragraph(paragraph):
        if kind == "run":
            yield node


def _runs_under(node):
    name = local(node.tag)
    if name == "r":
        yield node
        return
    if name in ("hyperlink", "smartTag", "ins", "sdt", "sdtContent", "customXml"):
        for child in list(node):
            for run in _runs_under(child):
                yield run


def _read_run(node, text=None, theme=None):
    run = {"text": text if text is not None else "".join((item.text or "") for item in node.findall(q(W, "t")))}
    rpr = node.find(q(W, "rPr"))
    if rpr is not None:
        run.update(_run_props(rpr, theme))
    return _order_run(run)


def _order_run(run):
    ordered = {"text": run.get("text", "")}
    for key in RUN_KEYS[1:]:
        if key in run and run[key] not in (None, ""):
            ordered[key] = run[key]
    return ordered


def _inherited_props(style_name, ctx):
    inherited = dict(ctx.get("defaults") or {})
    style = (ctx.get("styles") or {}).get(style_name) or {}
    for key, value in style.items():
        if value not in (None, "", {}):
            inherited[key] = value
    return inherited


def _is_cjk_font(name):
    if not name:
        return False
    if any("\u4e00" <= char <= "\u9fff" for char in name):
        return True
    return str(name).casefold() in (
        "fangsong_gb2312", "kaiti_gb2312", "simsun", "simhei", "fangsong", "kaiti",
        "nsimsun", "stfangsong", "stkaiti", "stsong", "stheiti", "stzhongsong",
    )


def _explicit_cjk(run):
    for key in ("ascii", "hAnsi"):
        name = run.get(key)
        if _is_cjk_font(name):
            return name
    return None


def _inherit_run(run, inherited):
    # WPS often stores 仿宋_GB2312 in ascii/hAnsi and leaves eastAsia empty.
    # Keep that requested name; do not replace it with a document default.
    if run.get("eastAsia") in (None, ""):
        face = _explicit_cjk(run)
        if face:
            run["eastAsia"] = face
    if not inherited:
        return _order_run(run)
    for key in ("eastAsia", "ascii", "hAnsi", "size_pt"):
        if run.get(key) in (None, "") and inherited.get(key) not in (None, ""):
            run[key] = inherited[key]
    if "bold" not in run and inherited.get("bold") is True:
        run["bold"] = True
    return _order_run(run)


def _run_events(run_node, ctx):
    pending = []

    def flush_text():
        if not pending:
            return None
        payload = _read_run(run_node, "".join(pending), ctx.get("theme"))
        pending[:] = []
        return payload

    for child in list(run_node):
        name = local(child.tag)
        if name == "t":
            pending.append(child.text or "")
        elif name == "br" and child.get(q(W, "type")) == "page":
            text = flush_text()
            if text is not None:
                yield "text", text
            yield "break", None
        elif name in ("drawing", "pict", "object"):
            text = flush_text()
            if text is not None:
                yield "text", text
            for image in _images_in(child, ctx["rels"], ctx["files"]):
                yield "image", image
        elif name == "AlternateContent":
            text = flush_text()
            if text is not None:
                yield "text", text
            for image in _alternate_images(child, ctx):
                yield "image", image
    text = flush_text()
    if text is not None:
        yield "text", text


def _run_images(run_node, ctx):
    images = []
    for kind, payload in _run_events(run_node, ctx):
        if kind == "image" and payload:
            images.append(payload)
    if images:
        return images
    return _images_in(run_node, ctx["rels"], ctx["files"])


def _alternate_images(node, ctx):
    choice = None
    fallback = None
    for child in list(node):
        name = local(child.tag)
        if name == "Choice" and choice is None:
            choice = child
        elif name == "Fallback" and fallback is None:
            fallback = child
    images = _images_in(choice, ctx["rels"], ctx["files"]) if choice is not None else []
    if images:
        return _unique_images(images)
    if fallback is None:
        return []
    return _unique_images(_images_in(fallback, ctx["rels"], ctx["files"]))


def _unique_images(images):
    found = []
    seen = set()
    for image in images:
        if not image:
            continue
        key = (image.get("asset"), image.get("w"), image.get("h"))
        if key in seen:
            continue
        seen.add(key)
        found.append(image)
    return found


def _run_props(rpr, theme=None):
    theme = theme or {"major": {}, "minor": {}}
    props = {}
    fonts = rpr.find(q(W, "rFonts"))
    if fonts is not None:
        for key in ("eastAsia", "ascii", "hAnsi"):
            value = fonts.get(q(W, key))
            if value:
                props[key] = value
        for key, token_name in (("eastAsia", "eastAsiaTheme"), ("ascii", "asciiTheme"), ("hAnsi", "hAnsiTheme")):
            if key not in props:
                face = _theme_face(theme, fonts.get(q(W, token_name)))
                if face:
                    props[key] = face
    size = rpr.find(q(W, "sz"))
    if size is not None and size.get(q(W, "val")):
        props["size_pt"] = num(int(size.get(q(W, "val"))) / 2.0)
    for key, tag in (("bold", "b"), ("italic", "i")):
        mark = rpr.find(q(W, tag))
        if mark is not None:
            props[key] = _flag(mark)
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


def _heading_level(style_id, style_name, ppr, style_level=None):
    if ppr is not None:
        outline = ppr.find(q(W, "outlineLvl"))
        if outline is not None and outline.get(q(W, "val")) not in (None, ""):
            raw = int(outline.get(q(W, "val")))
            if 0 <= raw <= 8:
                return raw + 1
            return None
    for text in (style_name, style_id):
        if not text:
            continue
        match = HEADING_NAME.match(text.strip())
        if match:
            level = int(match.group(1))
            if 1 <= level <= 9:
                return level
    if style_level:
        return style_level
    return None


def _section_break(ppr):
    if ppr is None:
        return False
    sect = ppr.find(q(W, "sectPr"))
    if sect is None:
        return False
    kind = sect.find(q(W, "type"))
    value = kind.get(q(W, "val")) if kind is not None else "nextPage"
    return value in ("nextPage", "oddPage", "evenPage")


VML = "urn:schemas-microsoft-com:vml"


def _images_in(run, rels, files):
    images = []
    for blip in run.iter(q(A, "blip")):
        embed = blip.get(q(R, "embed"))
        target = rels.get(embed or "")
        if not target:
            continue
        width, height = _extent(run)
        images.append(_image_block(target, files, width, height))
    for data in run.iter(q(VML, "imagedata")):
        embed = data.get(q(R, "id"))
        target = rels.get(embed or "")
        if not target:
            continue
        width, height = _vml_extent(run, data)
        images.append(_image_block(target, files, width, height))
    return [image for image in images if image]


def _extent(run):
    extent = next(run.iter(q(WP, "extent")), None)
    if extent is None:
        return None, None
    return emu_to_pt(extent.get("cx") or 0), emu_to_pt(extent.get("cy") or 0)


def _vml_extent(run, data):
    for shape in run.iter(q(VML, "shape")):
        if data not in list(shape.iter()):
            continue
        style = shape.get("style") or ""
        return _css_pt(style, "width"), _css_pt(style, "height")
    return None, None


def _css_pt(style, key):
    for part in style.split(";"):
        name, _, value = part.partition(":")
        if name.strip() != key:
            continue
        value = value.strip().lower()
        if value.endswith("pt"):
            return num(float(value[:-2]))
        if value.endswith("in"):
            return num(float(value[:-2]) * 72)
        if value.endswith("cm"):
            return num(float(value[:-2]) * 72 / 2.54)
    return None


def _image_block(target, files, width, height):
    target = target.replace("\\", "/").strip()
    while target.startswith("./"):
        target = target[2:]
    target = target.lstrip("/")
    while target.startswith("../"):
        target = target[3:]
    key = target if target.startswith("word/") else "word/" + target
    blob = files.get(key)
    if blob is None:
        return None
    name = key.split("/")[-1] or "image.bin"
    shown_w, shown_h = image_size.display_size(blob, width, height)
    return {"type": "image", "asset": name, "w": shown_w, "h": shown_h, "_bytes": blob}


def _read_table(table, ctx):
    parsed = []
    befores = []
    loose = []
    columns = _grid_widths(table)
    for tr in table.findall(q(W, "tr")):
        row = []
        trpr = tr.find(q(W, "trPr"))
        before = 0
        if trpr is not None:
            marker = trpr.find(q(W, "gridBefore"))
            if marker is not None and marker.get(q(W, "val")):
                before = int(marker.get(q(W, "val")))
        befores.append(before)
        for tc in tr.findall(q(W, "tc")):
            tcpr = tc.find(q(W, "tcPr"))
            span = 1
            vmerge = None
            hmerge = None
            if tcpr is not None:
                grid = tcpr.find(q(W, "gridSpan"))
                if grid is not None and grid.get(q(W, "val")):
                    span = int(grid.get(q(W, "val")))
                merge = tcpr.find(q(W, "vMerge"))
                if merge is not None:
                    vmerge = merge.get(q(W, "val")) or "continue"
                horizontal = tcpr.find(q(W, "hMerge"))
                if horizontal is not None:
                    hmerge = horizontal.get(q(W, "val")) or "continue"
            runs = []
            cell_images = []
            for paragraph in tc.findall(q(W, "p")):
                if runs and _paragraph_text(paragraph):
                    runs.append({"text": "\n"})
                inherited = _inherited_props("", ctx)
                for kind, node in _walk_paragraph(paragraph):
                    if kind == "alt":
                        cell_images.extend(image for image in _alternate_images(node, ctx) if image)
                        continue
                    if kind == "media":
                        cell_images.extend(image for image in _images_in(node, ctx["rels"], ctx["files"]) if image)
                        continue
                    for image in _run_images(node, ctx):
                        cell_images.append(image)
                    run = _inherit_run(_read_run(node, theme=ctx.get("theme")), inherited)
                    if run.get("text"):
                        runs.append(run)
            limit = _cell_width_pt(tcpr, columns, len(row), span)
            for image in cell_images:
                image["w"], image["h"] = image_size.fit_points(image["w"], image["h"], limit)
            loose.extend(cell_images)
            row.append({"span": max(span, 1), "vmerge": vmerge, "hmerge": hmerge, "runs": runs})
        parsed.append(row)
    grid, merges = _expand_table(parsed, befores)
    return {"type": "table", "rows": grid, "merges": merges}, loose


def _grid_widths(table):
    grid = table.find(q(W, "tblGrid"))
    if grid is None:
        return []
    widths = []
    for col in grid.findall(q(W, "gridCol")):
        try:
            widths.append(int(col.get(q(W, "w")) or 0))
        except ValueError:
            widths.append(0)
    return widths


def _cell_width_pt(tcpr, columns, col, span):
    if tcpr is not None:
        tcw = tcpr.find(q(W, "tcW"))
        if tcw is not None and (tcw.get(q(W, "type")) in (None, "dxa")):
            try:
                stated = int(tcw.get(q(W, "w")) or 0)
            except ValueError:
                stated = 0
            if stated > 0:
                return stated / 20.0
    if columns:
        width = sum(columns[col:col + span]) or columns[min(col, len(columns) - 1)]
        if width > 0:
            return width / 20.0
    return image_size.content_width_pt()


def _paragraph_text(paragraph):
    return "".join((item.text or "") for item in paragraph.iter(q(W, "t")))


def _expand_table(parsed, befores=None):
    grid = []
    merges = []
    anchors = {}
    merge_at = {}
    befores = befores or [0] * len(parsed)
    for ri, cells in enumerate(parsed):
        before = befores[ri] if ri < len(befores) else 0
        row = [{"runs": []} for _ in range(before)]
        col = before
        bumped = set()
        h_anchor = None
        for cell in cells:
            span = cell["span"]
            if cell.get("hmerge") == "continue" and h_anchor:
                merge_at[h_anchor]["colspan"] += span
                row.extend({"covered": True} for _ in range(span))
                col += span
                continue
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
            h_anchor = None
            if cell.get("hmerge") == "restart":
                item = {"row": ri, "col": col, "rowspan": 1, "colspan": span}
                merges.append(item)
                merge_at[(ri, col)] = item
                h_anchor = (ri, col)
            elif span > 1 or cell["vmerge"] == "restart":
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


def _merge_style(base, override):
    merged = dict(base or {})
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            inner = dict(merged[key])
            inner.update(value)
            merged[key] = inner
        else:
            merged[key] = value
    return merged


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
    overlay = _brush_style(block, brush, True) if brush else {}
    geom = {}
    for key in ("align", "indent", "line"):
        if block.get(key) not in (None, {}, ""):
            geom[key] = block[key]
        elif brush and linked.get(key) not in (None, {}, ""):
            geom[key] = linked[key]
    for key in ("align", "indent", "line"):
        if key in overlay:
            geom[key] = overlay[key]
    geom["size_pt"] = overlay.get("size_pt", linked.get("size_pt") or _first_size(block) or 16)
    paragraph = ET.SubElement(body, q(W, "p"))
    sid = style_ids.get(block.get("style") or "")
    if block.get("type") == "heading" and not sid:
        sid = "Heading%d" % block["level"]
    _write_ppr(paragraph, sid, geom, block.get("level") if block.get("type") == "heading" else None)
    runs = block.get("runs") or []
    if not runs:
        runs = [{"text": ""}]
    for run in runs:
        _write_run(paragraph, _effective_run(run, overlay, bool(overlay)))


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
    _fill_rpr(rpr, run, for_run=True)
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
                    cell_overlay = _brush_style({"type": "paragraph", "style": "正文"}, brush, True) if brush else {}
                    _write_run(paragraph, _effective_run(run, cell_overlay, bool(cell_overlay)))


def _write_image(body, block, rel_id, picture_id):
    paragraph = ET.SubElement(body, q(W, "p"))
    run = ET.SubElement(paragraph, q(W, "r"))
    drawing = ET.SubElement(run, q(W, "drawing"))
    inline = ET.SubElement(drawing, q(WP, "inline"))
    shown_w, shown_h = image_size.fit_points(block["w"], block["h"], image_size.content_width_pt())
    cx, cy = str(pt_to_emu(shown_w)), str(pt_to_emu(shown_h))
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


def _write_toc(body, blocks=None, sections=None):
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
    for label, page in _toc_entries(blocks, sections):
        label_run = ET.SubElement(paragraph, q(W, "r"))
        label_text = ET.SubElement(label_run, q(W, "t"))
        label_text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        label_text.text = label
        if page is not None:
            page_run = ET.SubElement(paragraph, q(W, "r"))
            page_text = ET.SubElement(page_run, q(W, "t"))
            page_text.text = str(page)
    end = ET.SubElement(paragraph, q(W, "r"))
    ET.SubElement(end, q(W, "fldChar")).set(q(W, "fldCharType"), "end")


def _toc_entries(blocks, sections):
    if not blocks:
        return []
    pages = {}
    try:
        import compose
        pages = dict((id(block), number) for block, number in compose.heading_pages(blocks, sections or None))
    except (ImportError, ValueError, TypeError):
        pages = {}
    entries = []
    for block in blocks:
        if block.get("type") != "heading":
            continue
        label = "".join(run.get("text", "") for run in block.get("runs") or []).strip()
        if not label:
            continue
        entries.append((label + "\t", pages.get(id(block))))
    return entries


def _sections_active(sections):
    if not sections:
        return False
    if len(sections) > 1:
        return True
    section = sections[0]
    if section.get("header") or section.get("footer") or section.get("footer_page"):
        return True
    if section.get("pgSz") or section.get("pgMar"):
        return True
    return False


def _section_at(index, sections):
    chosen = sections[0]
    for section in sections:
        if int(section.get("at") or 0) <= index:
            chosen = section
        else:
            break
    return chosen


def _footer_has_page(section, sections):
    if section.get("footer_page") is True:
        return True
    if section.get("footer_page") is False:
        return False
    if len(sections) > 1 or section.get("header") or section.get("footer"):
        return True
    return False


def _attach_sect(paragraph, section, sections, header_ids, footer_ids, next_break):
    ppr = paragraph.find(q(W, "pPr"))
    if ppr is None:
        ppr = ET.Element(q(W, "pPr"))
        paragraph.insert(0, ppr)
    ppr.append(_sect_element(section, sections, header_ids, footer_ids, False, next_break))


def _sect_element(section, sections, header_ids, footer_ids, final, next_break):
    index = 0
    for cursor, item in enumerate(sections):
        if item is section:
            index = cursor
            break
    sect = ET.Element(q(W, "sectPr"))
    if header_ids:
        header = ET.SubElement(sect, q(W, "headerReference"))
        header.set(q(W, "type"), "default")
        header.set(q(R, "id"), header_ids[index])
        footer = ET.SubElement(sect, q(W, "footerReference"))
        footer.set(q(W, "type"), "default")
        footer.set(q(R, "id"), footer_ids[index])
    if not final:
        kind = ET.SubElement(sect, q(W, "type"))
        kind.set(q(W, "val"), section.get("break") or next_break or "nextPage")
    _write_page_box(sect, section)
    return sect


def _write_page_box(sect, section):
    pg = section.get("pgSz") if isinstance(section.get("pgSz"), dict) else {}
    size = ET.SubElement(sect, q(W, "pgSz"))
    size.set(q(W, "w"), str(int(pg.get("w") or 11906)))
    size.set(q(W, "h"), str(int(pg.get("h") or 16838)))
    if pg.get("orient"):
        size.set(q(W, "orient"), str(pg.get("orient")))
    edges = section.get("pgMar") if isinstance(section.get("pgMar"), dict) else {}
    mar = ET.SubElement(sect, q(W, "pgMar"))
    for key, default in (
        ("top", 1440), ("right", 1440), ("bottom", 1440), ("left", 1440),
        ("header", 720), ("footer", 720), ("gutter", 0),
    ):
        mar.set(q(W, key), str(int(edges.get(key) if edges.get(key) is not None else default)))


def _header_xml(text):
    root = ET.Element(q(W, "hdr"))
    paragraph = ET.SubElement(root, q(W, "p"))
    if text:
        node = ET.SubElement(ET.SubElement(paragraph, q(W, "r")), q(W, "t"))
        node.text = text
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _footer_xml(text, with_page):
    root = ET.Element(q(W, "ftr"))
    paragraph = ET.SubElement(root, q(W, "p"))
    if text:
        node = ET.SubElement(ET.SubElement(paragraph, q(W, "r")), q(W, "t"))
        node.text = text
    if with_page:
        begin = ET.SubElement(paragraph, q(W, "r"))
        ET.SubElement(begin, q(W, "fldChar")).set(q(W, "fldCharType"), "begin")
        instr = ET.SubElement(paragraph, q(W, "r"))
        token = ET.SubElement(instr, q(W, "instrText"))
        token.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        token.text = " PAGE "
        separate = ET.SubElement(paragraph, q(W, "r"))
        ET.SubElement(separate, q(W, "fldChar")).set(q(W, "fldCharType"), "separate")
        shown = ET.SubElement(paragraph, q(W, "r"))
        ET.SubElement(shown, q(W, "t")).text = "1"
        end = ET.SubElement(paragraph, q(W, "r"))
        ET.SubElement(end, q(W, "fldChar")).set(q(W, "fldCharType"), "end")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _document_root(body):
    root = ET.Element(q(W, "document"))
    root.append(body)
    return root


def _xml(tree):
    return ET.tostring(tree.getroot(), encoding="utf-8", xml_declaration=True)


def _content_types(assets, section_count=0):
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
    for index in range(section_count or 0):
        for name, content in (
            ("/word/header%d.xml" % (index + 1), "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"),
            ("/word/footer%d.xml" % (index + 1), "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"),
        ):
            node = ET.SubElement(root, q(CT, "Override"))
            node.set("PartName", name)
            node.set("ContentType", content)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _package_rels():
    root = ET.Element(q(REL, "Relationships"))
    _rel(root, "rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument", "word/document.xml")
    _rel(root, "rId2", "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties", "docProps/core.xml")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _document_rels(images, header_ids=None, footer_ids=None):
    root = ET.Element(q(REL, "Relationships"))
    _rel(root, "rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles", "styles.xml")
    for index, rel_id in enumerate(header_ids or []):
        _rel(root, rel_id, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/header", "header%d.xml" % (index + 1))
    for index, rel_id in enumerate(footer_ids or []):
        _rel(root, rel_id, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer", "footer%d.xml" % (index + 1))
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
        _fill_rpr(rpr, style, for_run=False)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _fill_rpr(rpr, props, for_run=False):
    east = props.get("eastAsia")
    ascii_font = props.get("ascii")
    hansi = props.get("hAnsi") or props.get("ascii")
    if east or ascii_font or hansi:
        fonts = ET.SubElement(rpr, q(W, "rFonts"))
        if ascii_font:
            fonts.set(q(W, "ascii"), ascii_font)
        if hansi:
            fonts.set(q(W, "hAnsi"), hansi)
        if east:
            fonts.set(q(W, "eastAsia"), east)
        if for_run:
            fonts.set(q(W, "hint"), "eastAsia" if east else "default")
    if props.get("size_pt"):
        half = str(int(round(float(props["size_pt"]) * 2)))
        ET.SubElement(rpr, q(W, "sz")).set(q(W, "val"), half)
        if for_run:
            ET.SubElement(rpr, q(W, "szCs")).set(q(W, "val"), half)
    if "bold" in props:
        bold = ET.SubElement(rpr, q(W, "b"))
        bold_cs = ET.SubElement(rpr, q(W, "bCs")) if for_run else None
        if not props["bold"]:
            bold.set(q(W, "val"), "0")
            if bold_cs is not None:
                bold_cs.set(q(W, "val"), "0")
