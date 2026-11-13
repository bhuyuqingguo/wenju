import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET

import image_size
from wenju_format import WenjuDoc, load as load_package, save as save_package, validate


def load(path):
    """Load a package. Section headers are kept when this branch wrote them beside blocks."""
    doc = load_package(path)
    with zipfile.ZipFile(str(path)) as package:
        document = json.loads(package.read("document.json").decode("utf-8"))
    sections = document.get("sections")
    if isinstance(sections, list):
        doc.sections = sections
    return doc


def save(doc, path):
    """Save with the baseline package writer, then keep section headers next to blocks."""
    save_package(doc, path)
    sections = getattr(doc, "sections", None)
    if not sections:
        return path
    with zipfile.ZipFile(str(path)) as package:
        document = json.loads(package.read("document.json").decode("utf-8"))
        others = [(info, package.read(info.filename)) for info in package.infolist() if info.filename != "document.json"]
    document["sections"] = sections
    with zipfile.ZipFile(str(path), "w") as package:
        package.writestr("document.json", json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8"))
        for info, data in others:
            package.writestr(info, data)
    return path

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
EMU_PER_PT = 12700
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


def merge(docs):
    """Concatenate documents. The caller's list order is the section order. Source toc blocks are dropped."""
    blocks = []
    sections = []
    assets = {}
    for index, doc in enumerate(docs):
        copied = _copy_blocks(doc, index, assets)
        stripped = 0
        if index and copied and copied[0].get("type") == "pagebreak":
            copied = copied[1:]
            stripped = 1
        if index and (not blocks or blocks[-1].get("type") != "pagebreak"):
            blocks.append({"type": "pagebreak"})
        start = len(blocks)
        blocks.extend(copied)
        incoming = getattr(doc, "sections", None) or [{"at": 0, "header": "", "footer": ""}]
        for order, section in enumerate(incoming):
            brk = section.get("break") or "nextPage"
            if order == 0 and index > 0:
                brk = "nextPage"
            rel = _content_index(doc.blocks, int(section.get("at") or 0))
            if stripped and rel:
                rel -= 1
            sections.append({
                "at": start + rel,
                "header": section.get("header") or "",
                "footer": section.get("footer") or "",
                "break": brk,
            })
    if any(block.get("type") == "heading" for block in blocks) and not any(block.get("type") == "toc" for block in blocks):
        blocks.insert(0, {"type": "toc"})
        for section in sections:
            if section["at"] > 0:
                section["at"] += 1
    merged = WenjuDoc(blocks=blocks, styles={}, assets=assets, source={"kind": "merge", "name": ""})
    merged.sections = sections
    return merged


def _content_index(blocks, at):
    """Index within the blocks that remain after toc entries are dropped."""
    kept = 0
    for index, block in enumerate(blocks):
        if index >= at:
            return kept
        if block.get("type") != "toc":
            kept += 1
    return kept


def _copy_blocks(doc, index, assets):
    mapping = {}
    for name in sorted(doc.assets):
        base = name.split("/")[-1]
        target = "%d_%s" % (index, base)
        serial = 1
        while target in assets:
            target = "%d_%d_%s" % (index, serial, base)
            serial += 1
        assets[target] = doc.assets[name]
        mapping[name] = target
    copied = []
    for block in doc.blocks:
        if block.get("type") == "toc":
            continue
        block = json.loads(json.dumps(block))
        if block.get("type") == "image":
            block["asset"] = mapping.get(block["asset"], block["asset"])
        elif block.get("type") == "chart":
            if block.get("asset") in mapping:
                block["asset"] = mapping[block["asset"]]
            if block.get("preview") in mapping:
                block["preview"] = mapping[block["preview"]]
            _remap_chart_rels(block.get("rels") or [], mapping)
        elif block.get("type") == "table":
            for row in block.get("rows") or []:
                for cell in row or []:
                    if not isinstance(cell, dict):
                        continue
                    for image in cell.get("images") or []:
                        if isinstance(image, dict) and image.get("asset") in mapping:
                            image["asset"] = mapping[image["asset"]]
        copied.append(block)
    return copied


def _remap_chart_rels(rels, mapping):
    for rel in rels or []:
        if not isinstance(rel, dict):
            continue
        if rel.get("asset") in mapping:
            rel["asset"] = mapping[rel["asset"]]
        if rel.get("rels"):
            _remap_chart_rels(rel.get("rels"), mapping)


def merge_export(paths, out_wenju, out_docx, template=None, progress=None):
    """Load paths in the given order, save one .wenju, and write a Word file with TOC and page fields.

    progress(percents, overall) receives one percent per input file and the overall percent.
    """
    if not paths:
        raise ValueError("没有可合稿的文档")
    docs = []
    percents = [0 for _ in paths]
    count = len(paths)

    def emit(overall):
        if progress:
            progress(list(percents), overall)

    for index, path in enumerate(paths):
        percents[index] = 50
        emit(int(sum(percents) / float(count) * 0.9))
        docs.append(load(path))
        percents[index] = 100
        emit(int(sum(percents) / float(count) * 0.9))
    merged = merge(docs)
    if template:
        apply_template(merged, template)
    save(merged, out_wenju)
    to_docx(merged, out_docx, template=None)
    emit(100)
    return {"wenju": out_wenju, "docx": out_docx}


def _w(tag):
    return "{%s}%s" % (W, tag)


def _r(tag):
    return "{%s}%s" % (R, tag)

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
    """Renumber headings to 1. / 1.1 / 1.1.1 and record the requested font name."""
    default = None
    renumber = False
    if template:
        renumber = True
        if isinstance(template, dict):
            default = template.get("font")
            renumber = template.get("number", "多级数字") == "多级数字"
    _walk_runs(doc, default)
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
        if run.get("eastAsia"):
            return run["eastAsia"]
        if run.get("font"):
            return run["font"]
    return None


def _styled(text, font, default):
    run = {"text": text, "size_pt": 12}
    chosen = font or default
    if chosen:
        run["eastAsia"] = chosen
    return run


def _walk_runs(doc, default):
    def fix(runs):
        for run in runs or []:
            if run.get("font") and not run.get("eastAsia"):
                run["eastAsia"] = run.pop("font")
            elif "font" in run:
                run.pop("font", None)
            if not run.get("eastAsia") and default:
                run["eastAsia"] = default
            if not run.get("size_pt"):
                run["size_pt"] = 12
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
    if kind in ("image", "chart"):
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
        for section in doc.sections or []:
            if section.get("at", 0) > 0:
                section["at"] = section["at"] + 1
    if any(block.get("type") == "toc" for block in doc.blocks):
        doc.blocks = [
            block for block in doc.blocks
            if not (block.get("type") == "paragraph" and _run_text(block.get("runs")) == "目录")
        ]

def to_docx(doc, path, template=None):
    """Write a Word file with a TOC field and PAGE fields. template restyles headings and fonts."""
    errors = validate(doc)
    if errors:
        raise ValueError("；".join(errors))
    working = WenjuDoc(
        blocks=json.loads(json.dumps(doc.blocks)),
        styles=json.loads(json.dumps(doc.styles or {})),
        assets=dict(doc.assets),
        title=getattr(doc, "title", "") or "",
        source=dict(getattr(doc, "source", None) or {"kind": "new", "name": ""}),
    )
    working.sections = json.loads(json.dumps(getattr(doc, "sections", None) or []))
    apply_template(working, template)
    _ensure_toc(working)
    pages = dict((id(block), number) for block, number in heading_pages(working.blocks, working.sections or None))
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
    sections = doc.sections or [{"at": 0, "header": "", "footer": ""}]
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
    chart_seq = 1
    chart_plans = {}
    chart_overrides = []
    import wenju_format
    for block in doc.blocks:
        if block.get("type") == "image":
            asset = block["asset"]
            ext = os.path.splitext(asset)[1].lower() or ".png"
            target = "media/%d%s" % (drawing_seq, ext)
            parts["word/" + target] = doc.assets[asset]
            media_ids[id(block)] = (add_rel("image", target), drawing_seq, ext)
            drawing_seq += 1
        elif block.get("type") == "chart":
            plan = wenju_format.prepare_chart(block, doc.assets, chart_seq)
            ids = []
            for rel_kind, target in plan["doc_rels"]:
                ids.append(add_rel(rel_kind, target))
            plan["ids"] = ids
            plan["seq"] = drawing_seq
            for part_name, blob in plan["files"]:
                parts[part_name] = blob
            chart_overrides.extend(plan["overrides"])
            chart_plans[id(block)] = plan
            chart_seq += 1
            drawing_seq += 1
    document, overrides = _document_xml(doc, pages, sections, header_ids, footer_ids, media_ids, chart_plans)
    overrides = list(overrides) + chart_overrides
    parts["word/document.xml"] = document
    parts["word/styles.xml"] = _styles_xml(_first_font(_all_runs(doc)) or "仿宋")
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


def _document_xml(doc, pages, sections, header_ids, footer_ids, media_ids, chart_plans=None):
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
            last_p = _emit_runs(body, block.get("runs"), style="Heading%d" % block["level"], outline=block["level"] - 1)
        elif kind == "paragraph":
            last_p = _emit_runs(body, block.get("runs"), style=block.get("style") or "Normal")
        elif kind == "image":
            rel_id, seq, _ext = media_ids[id(block)]
            shown_w, shown_h = image_size.fit_points(block.get("w") or 40, block.get("h") or 20, image_size.content_width_pt())
            last_p = _emit_image(body, rel_id, seq, shown_w, shown_h)
        elif kind == "chart":
            plan = (chart_plans or {}).get(id(block))
            if plan and plan.get("ids"):
                import wenju_format
                fitted = dict(block)
                fitted["w"], fitted["h"] = image_size.fit_points(block.get("w") or 40, block.get("h") or 20, image_size.content_width_pt())
                last_p = wenju_format.write_chart_paragraph(body, fitted, plan["ids"], plan.get("seq") or 1)
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


def _emit_runs(parent, runs, style=None, outline=None):
    paragraph = _emit_paragraph(parent, None, style=style, outline=outline)
    for run in runs or []:
        _text_run(
            paragraph,
            run.get("text") or "",
            run.get("eastAsia"),
            run.get("size_pt") or 12,
            run.get("ascii"),
            run.get("hAnsi"),
            run.get("bold"),
            run.get("italic"),
            run.get("underline"),
            run.get("color"),
        )
    if not runs:
        _text_run(paragraph, "", "仿宋", 12, None)
    return paragraph


def _text_run(paragraph, text, font, size_pt=12, ascii_font=None, h_ansi=None, bold=None, italic=None, underline=None, color=None):
    run = ET.SubElement(paragraph, _w("r"))
    rpr = ET.SubElement(run, _w("rPr"))
    fonts = ET.SubElement(rpr, _w("rFonts"))
    face = font or "仿宋"
    fonts.set(_w("eastAsia"), face)
    western = ascii_font or face
    fonts.set(_w("ascii"), western)
    fonts.set(_w("hAnsi"), h_ansi or western)
    fonts.set(_w("cs"), western)
    if size_pt:
        half = str(int(round(float(size_pt) * 2)))
        ET.SubElement(rpr, _w("sz")).set(_w("val"), half)
        ET.SubElement(rpr, _w("szCs")).set(_w("val"), half)
    if bold:
        ET.SubElement(rpr, _w("b"))
    if italic:
        ET.SubElement(rpr, _w("i"))
    if underline:
        ET.SubElement(rpr, _w("u")).set(_w("val"), "single")
    if color:
        ET.SubElement(rpr, _w("color")).set(_w("val"), str(color))
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


def _all_runs(doc):
    found = []
    for block in doc.blocks:
        found.extend(block.get("runs") or [])
        if block.get("type") == "table":
            for row in block.get("rows") or []:
                for cell in row:
                    if isinstance(cell, dict):
                        found.extend(cell.get("runs") or [])
    return found


def _run_font(runs):
    for run in runs or []:
        if run.get("eastAsia"):
            return run["eastAsia"]
    return "仿宋"


def _pt_to_emu(value):
    return int(round(float(value) * EMU_PER_PT))


def _emit_image(parent, rel_id, seq, width, height):
    paragraph = ET.SubElement(parent, _w("p"))
    run = ET.SubElement(paragraph, _w("r"))
    drawing = ET.SubElement(run, _w("drawing"))
    inline = ET.SubElement(drawing, "{%s}inline" % WP)
    extent = ET.SubElement(inline, "{%s}extent" % WP)
    extent.set("cx", str(_pt_to_emu(width)))
    extent.set("cy", str(_pt_to_emu(height)))
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
            c_i = c0 + _colspan(merge) if r_i > found[0] and c_i == c0 else c_i + 1
            continue
        if found is not None:
            merge = found[2]
            count = 0
            for r in range(merge["row"], merge["row"] + _rowspan(merge)):
                for c in range(merge["col"], merge["col"] + _colspan(merge)):
                    raw = _run_text(block["rows"][r][c].get("runs"))
                    if raw:
                        count += _text_lines(raw)
            lines = max(lines, count or 1)
            c_i += _colspan(merge)
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
                c_i = c0 + _colspan(merge) if r_i > r0 and c_i == c0 else c_i + 1
                continue
            tc = ET.SubElement(tr, _w("tc"))
            tcpr = ET.SubElement(tc, _w("tcPr"))
            if found is not None:
                _r0, _c0, merge = found
                if _colspan(merge) > 1:
                    grid = ET.SubElement(tcpr, _w("gridSpan"))
                    grid.set(_w("val"), str(_colspan(merge)))
                if _rowspan(merge) > 1:
                    vm = ET.SubElement(tcpr, _w("vMerge"))
                    vm.set(_w("val"), "restart")
                _emit_rectangle(tc, block, merge)
                c_i += _colspan(merge)
            else:
                _emit_cell_runs(tc, row[c_i].get("runs"))
                c_i += 1
    return tbl


def _rowspan(merge):
    return int(merge.get("rowspan", merge.get("rows", 1)) or 1)


def _colspan(merge):
    return int(merge.get("colspan", merge.get("cols", 1)) or 1)


def _merge_at(spans, row, col):
    for (r0, c0), merge in spans.items():
        if r0 <= row < r0 + _rowspan(merge) and c0 <= col < c0 + _colspan(merge):
            return r0, c0, merge
    return None


def _emit_continue(tr, merge):
    tc = ET.SubElement(tr, _w("tc"))
    tcpr = ET.SubElement(tc, _w("tcPr"))
    if _colspan(merge) > 1:
        grid = ET.SubElement(tcpr, _w("gridSpan"))
        grid.set(_w("val"), str(_colspan(merge)))
    ET.SubElement(tcpr, _w("vMerge"))
    _emit_paragraph(tc, "")


def _emit_rectangle(parent, block, merge):
    runs = []
    for r in range(merge["row"], merge["row"] + _rowspan(merge)):
        for c in range(merge["col"], merge["col"] + _colspan(merge)):
            cell = block["rows"][r][c]
            found = [run for run in (cell.get("runs") or []) if isinstance(run, dict) and run.get("text")]
            if not found:
                continue
            if runs and _run_text(runs) and not str(runs[-1].get("text") or "").endswith("\n"):
                runs.append({"text": "\n"})
            runs.extend(found)
    if runs:
        _emit_cell_runs(parent, runs)
    else:
        _emit_paragraph(parent, "")


def _emit_cell_runs(parent, runs):
    paragraphs = [[]]
    for run in runs or []:
        if not isinstance(run, dict):
            continue
        parts = (run.get("text") or "").split("\n")
        for index, part in enumerate(parts):
            if part:
                copied = dict(run)
                copied["text"] = part
                paragraphs[-1].append(copied)
            if index < len(parts) - 1:
                paragraphs.append([])
    paragraphs = [item for item in paragraphs if item] or [[]]
    for item in paragraphs:
        if not item:
            _emit_paragraph(parent, "")
            continue
        paragraph = _emit_paragraph(parent, None)
        for run in item:
            _text_run(
                paragraph,
                run.get("text") or "",
                run.get("eastAsia"),
                run.get("size_pt") or 12,
                run.get("ascii"),
                run.get("hAnsi"),
                run.get("bold"),
                run.get("italic"),
                run.get("underline"),
                run.get("color"),
            )


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
    face = font or "仿宋"
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
        "chart": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart",
        "chartex": "http://schemas.microsoft.com/office/2014/relationships/chartEx",
    }
    lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', '<Relationships xmlns="%s">' % REL_NS]
    for rel_id, kind, target in rels:
        lines.append('<Relationship Id="%s" Type="%s" Target="%s"/>' % (rel_id, types[kind], target))
    lines.append("</Relationships>")
    return "\n".join(lines).encode("utf-8")


def _content_types(parts, extra_overrides):
    defaults = (
        ("rels", "application/vnd.openxmlformats-package.relationships+xml"),
        ("xml", "application/xml"),
        ("png", "image/png"),
        ("jpeg", "image/jpeg"),
        ("jpg", "image/jpeg"),
        ("gif", "image/gif"),
        ("bmp", "image/bmp"),
        ("emf", "image/x-emf"),
        ("wmf", "image/x-wmf"),
        ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
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
    for part, value in extra_overrides or []:
        overrides.append((part, value))
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
