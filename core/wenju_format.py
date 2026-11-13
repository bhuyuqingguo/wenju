import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET

import fontfallback

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

ET.register_namespace("w", W)
ET.register_namespace("r", R)
ET.register_namespace("wp", WP)
ET.register_namespace("a", A)
ET.register_namespace("pic", PIC)

BLOCK_TYPES = ("heading", "paragraph", "table", "image", "pagebreak", "toc")
PAGE_HEIGHT = 16838
PAGE_MARGIN = 1440
LINE_TWIP = 240
PAGE_LINES = (PAGE_HEIGHT - 2 * PAGE_MARGIN) // LINE_TWIP
CHARS_PER_LINE = (11906 - 2 * PAGE_MARGIN) // LINE_TWIP
_PREFIXES = (
    re.compile(r"^\s*第[0-9一二三四五六七八九十百千]+[章节部分篇]\s*"),
    re.compile(r"^\s*[一二三四五六七八九十百千]{1,3}[、.．]\s*"),
    re.compile(r"^\s*[（(][0-9一二三四五六七八九十百千]{1,3}[）)]\s*"),
    re.compile(r"^\s*\d+(?:[.．]\d+)*[.．、]\s*"),
    re.compile(r"^\s*\d+(?:[.．]\d+)+\s+"),
)
_PAGE_STARTS = ("nextPage", "evenPage", "oddPage")


def _w(tag):
    return "{%s}%s" % (W, tag)


def _r(tag):
    return "{%s}%s" % (R, tag)


class WenjuDoc(object):
    def __init__(self, blocks, styles=None, assets=None, manifest=None):
        self.blocks = blocks
        self.styles = styles or {}
        self.assets = assets or {}
        self.manifest = manifest or {"wenju": 1}


def validate(doc):
    """Return a list of problems. An empty list means the document matches the container contract."""
    errors = []
    if not isinstance(doc, WenjuDoc):
        return ["not a WenjuDoc"]
    if not isinstance(doc.blocks, list):
        errors.append("document.json must be a list")
        return errors
    if not isinstance(doc.styles, dict):
        errors.append("styles.json must be an object")
    if not isinstance(doc.assets, dict):
        errors.append("assets must be a map of names to bytes")
    for index, block in enumerate(doc.blocks):
        if not isinstance(block, dict) or block.get("type") not in BLOCK_TYPES:
            errors.append("block %d has an unknown type" % index)
            continue
        kind = block["type"]
        if kind == "heading":
            level = block.get("level")
            if not isinstance(level, int) or level < 1 or level > 9:
                errors.append("heading %d level must be 1..9" % index)
            _check_runs(block.get("runs"), "heading %d" % index, errors)
        elif kind == "paragraph":
            _check_runs(block.get("runs"), "paragraph %d" % index, errors)
        elif kind == "table":
            rows = block.get("rows")
            if not isinstance(rows, list) or not rows:
                errors.append("table %d needs rows" % index)
            else:
                width = None
                for r_i, row in enumerate(rows):
                    if not isinstance(row, list) or not row:
                        errors.append("table %d row %d is empty" % (index, r_i))
                        continue
                    width = width or len(row)
                    if len(row) != width:
                        errors.append("table %d is not rectangular" % index)
                    for c_i, cell in enumerate(row):
                        if not isinstance(cell, dict):
                            errors.append("table %d cell %d,%d is not an object" % (index, r_i, c_i))
                        else:
                            _check_runs(cell.get("runs"), "table %d cell %d,%d" % (index, r_i, c_i), errors)
        elif kind == "image":
            asset = block.get("asset")
            if not asset or asset not in doc.assets:
                errors.append("image %d asset is missing" % index)
    return errors


def _check_runs(runs, where, errors):
    if not isinstance(runs, list):
        errors.append("%s runs must be a list" % where)
        return
    for run in runs:
        if not isinstance(run, dict) or not isinstance(run.get("text", ""), str):
            errors.append("%s has a run without text" % where)


def save(doc, path):
    errors = validate(doc)
    if errors:
        raise ValueError("；".join(errors))
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        _put(archive, "manifest.json", _dump(doc.manifest))
        _put(archive, "document.json", _dump(doc.blocks))
        _put(archive, "styles.json", _dump(doc.styles))
        for name in sorted(doc.assets):
            _put(archive, name, doc.assets[name])


def load(path):
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        blocks = json.loads(archive.read("document.json").decode("utf-8"))
        try:
            styles = json.loads(archive.read("styles.json").decode("utf-8"))
        except KeyError:
            styles = {}
        assets = {}
        for info in archive.infolist():
            if info.filename.startswith("assets/") and not info.is_dir():
                assets[info.filename] = archive.read(info.filename)
    doc = WenjuDoc(blocks, styles, assets, manifest)
    errors = validate(doc)
    if errors:
        raise ValueError("；".join(errors))
    return doc


def _dump(value):
    return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")


def _put(archive, name, data):
    info = zipfile.ZipInfo(name)
    info.flag_bits |= 0x800
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, data)


def _run_text(runs):
    return "".join(run.get("text", "") for run in runs or [])


def _strip_number(text):
    for pattern in _PREFIXES:
        updated = pattern.sub("", text, count=1)
        if updated != text:
            return updated.strip()
    return text.strip()


def _label(counters, level):
    if level == 1:
        return "%d." % counters[0]
    return ".".join(str(value) for value in counters[:level])


def apply_template(doc, template):
    """Renumber headings to 1. / 1.1 / 1.1.1 and resolve font faces. None only resolves fonts."""
    default = None
    renumber = False
    if template:
        renumber = True
        if isinstance(template, dict):
            default = template.get("font")
            renumber = template.get("number", "多级数字") == "多级数字"
    _walk_runs(doc, default)
    if isinstance(doc.styles, dict) and default:
        doc.styles["font"] = fontfallback.resolve(default)
    if not renumber:
        return doc
    counters = []
    for block in doc.blocks:
        if block.get("type") != "heading":
            continue
        level = block["level"]
        counters = counters[:level]
        while len(counters) < level:
            counters.append(1 if len(counters) < level - 1 else 0)
        counters[level - 1] += 1
        body = _strip_number(_run_text(block.get("runs")))
        label = _label(counters, level)
        text = (label + " " + body).strip() if body else label
        block["runs"] = [_styled(text, _first_font(block.get("runs")), default)]
    return doc


def _first_font(runs):
    for run in runs or []:
        if run.get("font"):
            return run["font"]
    return None


def _styled(text, font, default):
    run = {"text": text}
    chosen = font or default
    if chosen:
        run["font"] = fontfallback.resolve(chosen)
    return run


def _walk_runs(doc, default):
    def fix(runs):
        for run in runs or []:
            if run.get("font"):
                run["font"] = fontfallback.resolve(run["font"])
            elif default:
                run["font"] = fontfallback.resolve(default)
    for block in doc.blocks:
        fix(block.get("runs"))
        if block.get("type") == "table":
            for row in block.get("rows") or []:
                for cell in row:
                    fix(cell.get("runs"))


def _lines(block):
    kind = block.get("type")
    if kind == "table":
        spans = _span_map(block)
        return max(1, sum(_row_span_lines(block, spans, r) for r in range(len(block.get("rows") or []))))
    if kind == "image":
        return max(1, int(round(float(block.get("h") or 20) / 20.0)))
    if kind in ("heading", "paragraph"):
        count = len(_run_text(block.get("runs")))
        return max(1, (count + CHARS_PER_LINE - 1) // CHARS_PER_LINE)
    return 1


def heading_pages(blocks, sections=None):
    """Estimate the page each heading lands on, including a TOC that shares the first page."""
    sections = sections or [{"at": 0, "break": "nextPage"}]
    page = 1
    used = 0
    found = []
    open_section = None
    for index, block in enumerate(blocks):
        section = _section_for(index, sections)
        if block.get("type") == "pagebreak":
            nxt = _section_for(index + 1, sections) if index + 1 < len(blocks) else section
            if not _starts_page(nxt, section):
                page += 1
                used = 0
            open_section = section
            continue
        if _starts_page(section, open_section):
            page += 1
            used = 0
        open_section = section
        if block.get("type") == "toc":
            need = _toc_lines(blocks)
        else:
            need = _lines(block)
        start, page, used = _place(page, used, need)
        if block.get("type") == "heading":
            found.append((block, start))
    return found


def _place(page, used, need):
    if need < 1:
        need = 1
    if used >= PAGE_LINES:
        page += 1
        used = 0
    start = page
    while need:
        room = PAGE_LINES - used
        take = need if need < room else room
        used += take
        need -= take
        if need:
            page += 1
            used = 0
    return start, page, used


def _starts_page(section, previous):
    return previous is not None and section is not previous and section.get("break", "nextPage") in _PAGE_STARTS


def _toc_lines(blocks):
    headings = sum(1 for block in blocks if block.get("type") == "heading")
    if not headings:
        return 1
    return 2 + headings


def _ensure_toc(doc):
    if any(block.get("type") == "heading" for block in doc.blocks) and not any(block.get("type") == "toc" for block in doc.blocks):
        doc.blocks.insert(0, {"type": "toc"})
        for section in doc.styles.get("sections") or []:
            if section.get("at", 0) > 0:
                section["at"] = section["at"] + 1


def from_docx(path):
    with zipfile.ZipFile(path) as archive:
        package = {name: archive.read(name) for name in archive.namelist()}
    root = ET.fromstring(package["word/document.xml"])
    rels = _rels(package.get("word/_rels/document.xml.rels", b""))
    body = root.find(_w("body"))
    blocks = []
    assets = {}
    image_seq = 0
    in_toc = False
    emitted_toc = False
    sections = []
    current = {"at": 0, "header": "", "footer": "", "break": "nextPage"}
    for child in list(body):
        if child.tag == _w("sectPr"):
            _finish_section(current, child, rels, package, sections)
            continue
        if child.tag == _w("tbl"):
            blocks.append(_read_table(child))
            continue
        if child.tag != _w("p"):
            continue
        if _paragraph_has_toc(child):
            if not emitted_toc:
                blocks.append({"type": "toc"})
                emitted_toc = True
            in_toc = "end" not in _field_types(child) or "begin" in _field_types(child)
            if "end" in _field_types(child) and "begin" not in _field_types(child):
                in_toc = False
            continue
        if in_toc:
            if "end" in _field_types(child):
                in_toc = False
            continue
        if _read_image(child, rels, package) is not None:
            image_seq = _append_rich(blocks, child, rels, package, assets, image_seq)
        else:
            _append_paragraph(blocks, child)
        sect = child.find("w:pPr/w:sectPr", {"w": W})
        if sect is not None:
            _finish_section(current, sect, rels, package, sections)
            current = {"at": len(blocks), "header": "", "footer": "", "break": _break_type(sect)}
    if not sections:
        final = body.find(_w("sectPr"))
        if final is not None:
            _finish_section(current, final, rels, package, sections)
    styles = {"sections": sections} if sections else {}
    return WenjuDoc(blocks, styles, assets, {"wenju": 1})


def _finish_section(current, sect, rels, package, sections):
    current["header"] = _part_text(sect, rels, package, "headerReference")
    current["footer"] = _part_text(sect, rels, package, "footerReference", skip_field=True)
    sections.append(dict(current))


def _typed_ref(sect, tag):
    found = sect.findall(_w(tag))
    for ref in found:
        if ref.get(_w("type"), "default") == "default":
            return ref
    if found:
        return found[0]
    return None


def _rels(data):
    found = {}
    if not data:
        return found
    root = ET.fromstring(data)
    for rel in root:
        found[rel.get("Id")] = rel.get("Target")
    return found


def _break_type(sect):
    node = sect.find(_w("type"))
    if node is None:
        return "nextPage"
    return node.get(_w("val")) or "nextPage"


def _part_text(sect, rels, package, tag, skip_field=False):
    ref = _typed_ref(sect, tag)
    if ref is None:
        return ""
    target = rels.get(ref.get(_r("id")))
    if not target:
        return ""
    name = "word/" + target.lstrip("/")
    if name not in package:
        return ""
    return _visible_text(ET.fromstring(package[name]), skip_field).strip()


def _visible_text(root, skip_field):
    texts = []
    skip = False
    for el in root.iter():
        if el.tag == _w("fldChar"):
            kind = el.get(_w("fldCharType"))
            if kind == "separate":
                skip = True
            elif kind in ("end", "begin"):
                skip = False
        elif el.tag == _w("t") and not (skip_field and skip):
            texts.append(el.text or "")
    return "".join(texts)


def _read_table(tbl):
    rows = []
    merges = []
    vmerge_open = {}
    for r_i, tr in enumerate(tbl.findall(_w("tr"))):
        row = []
        col = 0
        for tc in tr.findall(_w("tc")):
            span = 1
            grid = tc.find("w:tcPr/w:gridSpan", {"w": W})
            if grid is not None:
                span = int(grid.get(_w("val")) or 1)
            vm = tc.find("w:tcPr/w:vMerge", {"w": W})
            text = _cell_text(tc)
            row.append({"runs": [{"text": text}]})
            if span > 1 or (vm is not None and vm.get(_w("val")) == "restart"):
                merges.append({"row": r_i, "col": col, "rows": 1, "cols": span})
            if vm is not None and vm.get(_w("val"), "continue") != "restart":
                anchor = vmerge_open.get(col)
                if anchor is not None:
                    anchor["rows"] += 1
            elif vm is not None:
                vmerge_open[col] = merges[-1]
            for _extra in range(span - 1):
                row.append({"runs": [{"text": ""}]})
            col += span
        rows.append(row)
    block = {"type": "table", "rows": rows}
    if merges:
        block["merges"] = merges
    return block


def _append_rich(blocks, paragraph, rels, package, assets, image_seq):
    if _page_break_before(paragraph):
        blocks.append({"type": "pagebreak"})
    style = _style_of(paragraph)
    level = _heading_level(paragraph, style)
    buf = []

    def flush():
        text = "".join(buf)
        del buf[:]
        if text:
            blocks.append(_text_block(level, style, text))

    for child in list(paragraph):
        if child.tag != _w("r"):
            continue
        if _run_has_drawing(child):
            flush()
            image = _read_image(child, rels, package)
            if image is None:
                continue
            image_seq += 1
            name = "assets/image%d%s" % (image_seq, image[0])
            assets[name] = image[1]
            blocks.append({"type": "image", "asset": name, "w": image[2], "h": image[3]})
            continue
        for el in list(child):
            if el.tag == _w("br") and el.get(_w("type")) == "page":
                flush()
                blocks.append({"type": "pagebreak"})
            elif el.tag == _w("t"):
                buf.append(el.text or "")
            elif el.tag == _w("tab"):
                buf.append("\t")
    flush()
    return image_seq


def _run_has_drawing(run):
    for el in run.iter():
        if el.tag == "{%s}blip" % A:
            return True
    return False


def _read_image(paragraph, rels, package):
    blip = None
    for el in paragraph.iter():
        if el.tag == "{%s}blip" % A:
            blip = el
            break
    if blip is None:
        return None
    target = rels.get(blip.get(_r("embed")))
    if not target:
        return None
    name = "word/" + target.lstrip("/")
    if name not in package:
        return None
    extent = None
    for el in paragraph.iter():
        if el.tag == "{%s}extent" % WP:
            extent = el
            break
    width = int(int(extent.get("cx") or 0) / 9525) if extent is not None else 0
    height = int(int(extent.get("cy") or 0) / 9525) if extent is not None else 0
    ext = os.path.splitext(target)[1] or ".bin"
    return ext, package[name], width, height


def _style_of(paragraph):
    node = paragraph.find("w:pPr/w:pStyle", {"w": W})
    if node is None:
        return ""
    return node.get(_w("val")) or ""


def _heading_level(paragraph, style):
    outline = paragraph.find("w:pPr/w:outlineLvl", {"w": W})
    if outline is not None and outline.get(_w("val"), "").isdigit():
        return int(outline.get(_w("val"))) + 1
    match = re.match(r"(?i)^heading\s*(\d)$", style or "")
    if match:
        return int(match.group(1))
    return None


def _plain_text(node):
    return "".join(el.text or "" for el in node.iter(_w("t")))


def _cell_text(cell):
    paragraphs = cell.findall(_w("p"))
    if not paragraphs:
        return _plain_text(cell)
    return "\n".join(_plain_text(paragraph) for paragraph in paragraphs)


def _append_paragraph(blocks, paragraph):
    if _page_break_before(paragraph):
        blocks.append({"type": "pagebreak"})
    style = _style_of(paragraph)
    level = _heading_level(paragraph, style)
    pieces = list(_run_pieces(paragraph))
    if not pieces:
        text = _plain_text(paragraph)
        if text or style:
            blocks.append(_text_block(level, style, text))
        return
    buf = []
    emitted = [False]

    def flush():
        text = "".join(buf)
        del buf[:]
        if not text and not (style and not emitted[0]):
            return
        emitted[0] = True
        blocks.append(_text_block(level, style, text))

    for kind, value in pieces:
        if kind == "break":
            flush()
            blocks.append({"type": "pagebreak"})
        else:
            buf.append(value)
    flush()


def _text_block(level, style, text):
    if level:
        return {"type": "heading", "level": level, "runs": [{"text": text}]}
    return {"type": "paragraph", "style": style or "Normal", "runs": [{"text": text}]}


def _run_pieces(paragraph):
    for child in paragraph:
        if child.tag != _w("r"):
            continue
        for el in child:
            if el.tag == _w("br") and el.get(_w("type")) == "page":
                yield ("break", "")
            elif el.tag == _w("t"):
                yield ("text", el.text or "")
            elif el.tag == _w("tab"):
                yield ("text", "\t")


def _page_break_before(paragraph):
    return paragraph.find("w:pPr/w:pageBreakBefore", {"w": W}) is not None


def _field_types(paragraph):
    return [el.get(_w("fldCharType")) for el in paragraph.iter(_w("fldChar"))]


def _paragraph_has_toc(paragraph):
    for el in paragraph.iter(_w("instrText")):
        if el.text and re.search(r"\bTOC\b", el.text):
            return True
    return False


def to_docx(doc, path, template=None):
    """Write a Word file with a TOC field and PAGE fields. template restyles headings and fonts."""
    errors = validate(doc)
    if errors:
        raise ValueError("；".join(errors))
    working = WenjuDoc(json.loads(json.dumps(doc.blocks)), json.loads(json.dumps(doc.styles)), dict(doc.assets), dict(doc.manifest))
    apply_template(working, template)
    _ensure_toc(working)
    pages = dict((id(block), number) for block, number in heading_pages(working.blocks, working.styles.get("sections") or None))
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    package = _build_docx(working, pages)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in package:
            archive.writestr(name, package[name])
    return path


def _build_docx(doc, pages):
    parts = {}
    rels = []
    media_ids = {}
    next_id = 1

    def add_rel(rel_type, target):
        nonlocal next_id
        rel_id = "rId%d" % next_id
        next_id += 1
        rels.append((rel_id, rel_type, target))
        return rel_id

    add_rel("styles", "styles.xml")
    add_rel("settings", "settings.xml")
    sections = doc.styles.get("sections") or [{"at": 0, "header": "", "footer": ""}]
    header_ids = []
    footer_ids = []
    for index, section in enumerate(sections):
        header_name = "header%d.xml" % (index + 1)
        footer_name = "footer%d.xml" % (index + 1)
        parts["word/" + header_name] = _header_xml(section.get("header") or "")
        parts["word/" + footer_name] = _footer_xml(section.get("footer") or "")
        header_ids.append(add_rel("header", header_name))
        footer_ids.append(add_rel("footer", footer_name))
    drawing_seq = 1
    for block in doc.blocks:
        if block.get("type") != "image":
            continue
        asset = block["asset"]
        ext = os.path.splitext(asset)[1].lower() or ".png"
        target = "media/%d%s" % (drawing_seq, ext)
        parts["word/" + target] = doc.assets[asset]
        media_ids[id(block)] = (add_rel("image", target), drawing_seq, ext)
        drawing_seq += 1
    document, overrides = _document_xml(doc, pages, sections, header_ids, footer_ids, media_ids)
    parts["word/document.xml"] = document
    parts["word/styles.xml"] = _styles_xml(doc.styles.get("font") or "仿宋")
    parts["word/settings.xml"] = _xml(_settings())
    parts["word/_rels/document.xml.rels"] = _rels_xml(rels)
    parts["[Content_Types].xml"] = _content_types(parts, overrides)
    parts["_rels/.rels"] = _xml_bytes(
        '<Relationships xmlns="%s"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>' % REL_NS
    )
    return parts


def _section_for(index, sections):
    chosen = sections[0]
    for section in sections:
        if section.get("at", 0) <= index:
            chosen = section
        else:
            break
    return chosen


def _document_xml(doc, pages, sections, header_ids, footer_ids, media_ids):
    body = ET.Element(_w("body"))
    last_p = None
    open_section = None
    heading_ordinal = 0
    for index, block in enumerate(doc.blocks):
        section = _section_for(index, sections)
        if open_section is not None and section is not open_section:
            if last_p is None:
                last_p = ET.SubElement(body, _w("p"))
            _attach_sect(last_p, open_section, sections, header_ids, footer_ids, final=False, next_break=section.get("break") or "nextPage")
            last_p = None
        open_section = section
        kind = block["type"]
        if kind == "toc":
            last_p = _emit_toc(body, doc.blocks, pages)
        elif kind == "pagebreak":
            following = _section_for(index + 1, sections) if index + 1 < len(doc.blocks) else section
            last_p = _emit_paragraph(body, "", break_page=following is section)
        elif kind == "heading":
            heading_ordinal += 1
            last_p = _emit_paragraph(body, _run_text(block.get("runs")), style="Heading%d" % block["level"], font=_run_font(block.get("runs")), outline=block["level"] - 1)
        elif kind == "paragraph":
            last_p = _emit_paragraph(body, _run_text(block.get("runs")), style=block.get("style") or "Normal", font=_run_font(block.get("runs")))
        elif kind == "image":
            rel_id, seq, _ext = media_ids[id(block)]
            last_p = _emit_image(body, rel_id, seq, block.get("w") or 40, block.get("h") or 20)
        elif kind == "table":
            _emit_table(body, block)
            last_p = None
    if open_section is None:
        open_section = sections[0]
    body.append(_sect_element(open_section, sections, header_ids, footer_ids, final=True))
    document = ET.Element(_w("document"))
    document.append(body)
    return _xml(document), []


def _attach_sect(paragraph, section, sections, header_ids, footer_ids, final, next_break="nextPage"):
    ppr = paragraph.find(_w("pPr"))
    if ppr is None:
        ppr = ET.Element(_w("pPr"))
        paragraph.insert(0, ppr)
    ppr.append(_sect_element(section, sections, header_ids, footer_ids, final=final, next_break=next_break))


def _sect_element(section, sections, header_ids, footer_ids, final, next_break="nextPage"):
    index = next(i for i, item in enumerate(sections) if item is section)
    sect = ET.Element(_w("sectPr"))
    header = ET.SubElement(sect, _w("headerReference"))
    header.set(_w("type"), "default")
    header.set(_r("id"), header_ids[index])
    footer = ET.SubElement(sect, _w("footerReference"))
    footer.set(_w("type"), "default")
    footer.set(_r("id"), footer_ids[index])
    if not final:
        kind = ET.SubElement(sect, _w("type"))
        kind.set(_w("val"), next_break or "nextPage")
    page = ET.SubElement(sect, _w("pgSz"))
    page.set(_w("w"), "11906")
    page.set(_w("h"), str(PAGE_HEIGHT))
    mar = ET.SubElement(sect, _w("pgMar"))
    for edge in ("top", "right", "bottom", "left"):
        mar.set(_w(edge), str(PAGE_MARGIN))
    mar.set(_w("header"), "720")
    mar.set(_w("footer"), "720")
    mar.set(_w("gutter"), "0")
    numbering = ET.SubElement(sect, _w("pgNumType"))
    numbering.set(_w("fmt"), "decimal")
    if index == 0:
        numbering.set(_w("start"), "1")
    return sect


def _emit_toc(body, blocks, pages):
    title = _emit_paragraph(body, "目录", style="TOCHeading")
    begin = _emit_paragraph(body, "")
    _field_char(begin, "begin")
    _instr(begin, ' TOC \\o "1-3" \\h \\z \\u ')
    _field_char(begin, "separate")
    last = begin
    for block in blocks:
        if block.get("type") != "heading":
            continue
        level = min(block["level"], 3)
        last = _emit_paragraph(body, "", style="TOC%d" % level)
        _text_run(last, _run_text(block.get("runs")), "仿宋")
        tab = ET.SubElement(last, _w("r"))
        ET.SubElement(tab, _w("tab"))
        _text_run(last, str(pages[id(block)]), "仿宋")
    if last is begin:
        last = _emit_paragraph(body, "")
    _field_char(last, "end")
    return last if title is not None else last


def _field_char(paragraph, kind):
    run = ET.SubElement(paragraph, _w("r"))
    el = ET.SubElement(run, _w("fldChar"))
    el.set(_w("fldCharType"), kind)


def _instr(paragraph, text):
    run = ET.SubElement(paragraph, _w("r"))
    el = ET.SubElement(run, _w("instrText"))
    el.set(XML_SPACE, "preserve")
    el.text = text


def _text_run(paragraph, text, font):
    run = ET.SubElement(paragraph, _w("r"))
    rpr = ET.SubElement(run, _w("rPr"))
    fonts = ET.SubElement(rpr, _w("rFonts"))
    face = fontfallback.resolve(font or "仿宋")
    for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
        fonts.set(_w(attr), face)
    node = ET.SubElement(run, _w("t"))
    if text.startswith(" ") or text.endswith(" "):
        node.set(XML_SPACE, "preserve")
    node.text = text


def _emit_paragraph(parent, text, style=None, font=None, outline=None, break_page=False):
    paragraph = ET.SubElement(parent, _w("p"))
    ppr = ET.SubElement(paragraph, _w("pPr"))
    if style:
        node = ET.SubElement(ppr, _w("pStyle"))
        node.set(_w("val"), style)
    if outline is not None:
        node = ET.SubElement(ppr, _w("outlineLvl"))
        node.set(_w("val"), str(outline))
    if break_page:
        run = ET.SubElement(paragraph, _w("r"))
        br = ET.SubElement(run, _w("br"))
        br.set(_w("type"), "page")
    if text:
        _text_run(paragraph, text, font or "仿宋")
    return paragraph


def _run_font(runs):
    for run in runs or []:
        if run.get("font"):
            return run["font"]
    return "仿宋"


def _emit_image(parent, rel_id, seq, width, height):
    paragraph = ET.SubElement(parent, _w("p"))
    run = ET.SubElement(paragraph, _w("r"))
    drawing = ET.SubElement(run, _w("drawing"))
    inline = ET.SubElement(drawing, "{%s}inline" % WP)
    extent = ET.SubElement(inline, "{%s}extent" % WP)
    extent.set("cx", str(int(width) * 9525))
    extent.set("cy", str(int(height) * 9525))
    doc_pr = ET.SubElement(inline, "{%s}docPr" % WP)
    doc_pr.set("id", str(seq))
    doc_pr.set("name", "Picture%d" % seq)
    graphic = ET.SubElement(inline, "{%s}graphic" % A)
    data = ET.SubElement(graphic, "{%s}graphicData" % A)
    data.set("uri", PIC)
    pic = ET.SubElement(data, "{%s}pic" % PIC)
    fill = ET.SubElement(pic, "{%s}blipFill" % PIC)
    blip = ET.SubElement(fill, "{%s}blip" % A)
    blip.set(_r("embed"), rel_id)
    return paragraph


def _span_map(block):
    spans = {}
    for merge in block.get("merges") or []:
        spans[(merge["row"], merge["col"])] = merge
    return spans


def _text_lines(text):
    if not text:
        return 1
    return max(1, len(text.split("\n")))


def _row_span_lines(block, spans, r_i):
    row = block["rows"][r_i]
    lines = 1
    c_i = 0
    while c_i < len(row):
        found = _merge_at(spans, r_i, c_i)
        if found is not None and (found[0], found[1]) != (r_i, c_i):
            _r0, c0, merge = found
            c_i = c0 + merge.get("cols", 1) if r_i > found[0] and c_i == c0 else c_i + 1
            continue
        if found is not None:
            merge = found[2]
            count = 0
            for r in range(merge["row"], merge["row"] + merge.get("rows", 1)):
                for c in range(merge["col"], merge["col"] + merge.get("cols", 1)):
                    raw = _run_text(block["rows"][r][c].get("runs"))
                    if raw:
                        count += _text_lines(raw)
            lines = max(lines, count or 1)
            c_i += merge.get("cols", 1)
        else:
            lines = max(lines, _text_lines(_run_text(row[c_i].get("runs"))))
            c_i += 1
    return lines


def _emit_table(parent, block):
    tbl = ET.SubElement(parent, _w("tbl"))
    props = ET.SubElement(tbl, _w("tblPr"))
    margins = ET.SubElement(props, _w("tblCellMar"))
    for edge in ("top", "left", "bottom", "right"):
        node = ET.SubElement(margins, _w(edge))
        node.set(_w("w"), "0")
        node.set(_w("type"), "dxa")
    spans = {}
    for merge in block.get("merges") or []:
        spans[(merge["row"], merge["col"])] = merge
    for r_i, row in enumerate(block["rows"]):
        tr = ET.SubElement(tbl, _w("tr"))
        height = ET.SubElement(ET.SubElement(tr, _w("trPr")), _w("trHeight"))
        height.set(_w("val"), str(LINE_TWIP * _row_span_lines(block, spans, r_i)))
        height.set(_w("hRule"), "exact")
        c_i = 0
        while c_i < len(row):
            found = _merge_at(spans, r_i, c_i)
            if found is not None and (found[0], found[1]) != (r_i, c_i):
                r0, c0, merge = found
                if r_i > r0 and c_i == c0:
                    _emit_continue(tr, merge)
                c_i = c0 + merge.get("cols", 1) if r_i > r0 and c_i == c0 else c_i + 1
                continue
            tc = ET.SubElement(tr, _w("tc"))
            tcpr = ET.SubElement(tc, _w("tcPr"))
            if found is not None:
                _r0, _c0, merge = found
                if merge.get("cols", 1) > 1:
                    grid = ET.SubElement(tcpr, _w("gridSpan"))
                    grid.set(_w("val"), str(merge["cols"]))
                if merge.get("rows", 1) > 1:
                    vm = ET.SubElement(tcpr, _w("vMerge"))
                    vm.set(_w("val"), "restart")
                _emit_rectangle(tc, block, merge)
                c_i += merge.get("cols", 1)
            else:
                _emit_cell_text(tc, _run_text(row[c_i].get("runs")), _run_font(row[c_i].get("runs")))
                c_i += 1
    return tbl


def _merge_at(spans, row, col):
    for (r0, c0), merge in spans.items():
        if r0 <= row < r0 + merge.get("rows", 1) and c0 <= col < c0 + merge.get("cols", 1):
            return r0, c0, merge
    return None


def _emit_continue(tr, merge):
    tc = ET.SubElement(tr, _w("tc"))
    tcpr = ET.SubElement(tc, _w("tcPr"))
    if merge.get("cols", 1) > 1:
        grid = ET.SubElement(tcpr, _w("gridSpan"))
        grid.set(_w("val"), str(merge["cols"]))
    ET.SubElement(tcpr, _w("vMerge"))
    _emit_paragraph(tc, "")


def _emit_rectangle(parent, block, merge):
    emitted = False
    for r in range(merge["row"], merge["row"] + merge.get("rows", 1)):
        for c in range(merge["col"], merge["col"] + merge.get("cols", 1)):
            cell = block["rows"][r][c]
            raw = _run_text(cell.get("runs"))
            if not raw:
                continue
            _emit_cell_text(parent, raw, _run_font(cell.get("runs")))
            emitted = True
    if not emitted:
        _emit_paragraph(parent, "")


def _emit_cell_text(parent, text, font):
    parts = text.split("\n") if text else [""]
    for part in parts:
        _emit_paragraph(parent, part, font=font)


def _header_xml(text):
    root = ET.Element(_w("hdr"))
    _emit_paragraph(root, text, style="Header", font="仿宋")
    return _xml(root)


def _footer_xml(text):
    root = ET.Element(_w("ftr"))
    paragraph = _emit_paragraph(root, "", style="Footer", font="宋体")
    if text:
        _text_run(paragraph, text, "宋体")
    _field_char(paragraph, "begin")
    _instr(paragraph, " PAGE ")
    _field_char(paragraph, "separate")
    _text_run(paragraph, "1", "宋体")
    _field_char(paragraph, "end")
    return _xml(root)


def _styles_xml(font):
    face = fontfallback.resolve(font)
    styles = ET.Element(_w("styles"))
    defaults = ET.SubElement(styles, _w("docDefaults"))
    rdef = ET.SubElement(ET.SubElement(defaults, _w("rPrDefault")), _w("rPr"))
    fonts = ET.SubElement(rdef, _w("rFonts"))
    for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
        fonts.set(_w(attr), face)
    ET.SubElement(rdef, _w("sz")).set(_w("val"), "24")
    ET.SubElement(rdef, _w("szCs")).set(_w("val"), "24")
    _single_spacing(ET.SubElement(ET.SubElement(defaults, _w("pPrDefault")), _w("pPr")))
    normal = ET.SubElement(styles, _w("style"))
    normal.set(_w("type"), "paragraph")
    normal.set(_w("styleId"), "Normal")
    ET.SubElement(normal, _w("name")).set(_w("val"), "Normal")
    rpr = ET.SubElement(normal, _w("rPr"))
    fonts = ET.SubElement(rpr, _w("rFonts"))
    for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
        fonts.set(_w(attr), face)
    _single_spacing(ET.SubElement(normal, _w("pPr")))
    for level in range(1, 10):
        style = ET.SubElement(styles, _w("style"))
        style.set(_w("type"), "paragraph")
        style.set(_w("styleId"), "Heading%d" % level)
        ET.SubElement(style, _w("name")).set(_w("val"), "heading %d" % level)
        ppr = ET.SubElement(style, _w("pPr"))
        ET.SubElement(ppr, _w("outlineLvl")).set(_w("val"), str(level - 1))
        _single_spacing(ppr)
    return _xml(styles)


def _single_spacing(ppr):
    spacing = ET.SubElement(ppr, _w("spacing"))
    spacing.set(_w("before"), "0")
    spacing.set(_w("after"), "0")
    spacing.set(_w("line"), str(LINE_TWIP))
    spacing.set(_w("lineRule"), "auto")


def _settings():
    root = ET.Element(_w("settings"))
    ET.SubElement(root, _w("updateFields")).set(_w("val"), "true")
    return root


def _rels_xml(rels):
    types = {
        "styles": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles",
        "settings": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings",
        "header": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/header",
        "footer": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer",
        "image": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
    }
    lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', '<Relationships xmlns="%s">' % REL_NS]
    for rel_id, kind, target in rels:
        lines.append('<Relationship Id="%s" Type="%s" Target="%s"/>' % (rel_id, types[kind], target))
    lines.append("</Relationships>")
    return "\n".join(lines).encode("utf-8")


def _content_types(parts, _overrides):
    defaults = (
        ("rels", "application/vnd.openxmlformats-package.relationships+xml"),
        ("xml", "application/xml"),
        ("png", "image/png"),
        ("jpeg", "image/jpeg"),
        ("jpg", "image/jpeg"),
        ("bin", "application/octet-stream"),
    )
    overrides = [
        ("/word/document.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"),
        ("/word/styles.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"),
        ("/word/settings.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"),
    ]
    for name in sorted(parts):
        if re.match(r"word/header\d+\.xml$", name):
            overrides.append(("/" + name, "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"))
        if re.match(r"word/footer\d+\.xml$", name):
            overrides.append(("/" + name, "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"))
    lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', '<Types xmlns="%s">' % CT_NS]
    for ext, value in defaults:
        lines.append('<Default Extension="%s" ContentType="%s"/>' % (ext, value))
    for part, value in overrides:
        lines.append('<Override PartName="%s" ContentType="%s"/>' % (part, value))
    lines.append("</Types>")
    return "\n".join(lines).encode("utf-8")


def _xml(element):
    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + ET.tostring(element, encoding="utf-8")


def _xml_bytes(text):
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + text).encode("utf-8")
