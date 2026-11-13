from __future__ import annotations

import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from wenju_format import WenjuDoc, brush, from_docx, load, save, to_docx

SS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_READERS = {}


class ConvertError(Exception):
    pass


def convert_path(path, mode="preserve", template=None, report=None):
    source = Path(path)
    if not source.is_file():
        raise ConvertError("找不到文件：%s" % source.name)
    if report:
        report(8, "正在读取")
    suffix = source.suffix.lower()
    reader = _READERS.get(suffix)
    if reader is None:
        raise ConvertError(_unsupported(suffix))
    if report:
        report(40, "正在解析")
    doc = reader(str(source))
    return _finish(doc, mode, template, report)


def convert_text(text, mode="preserve", template=None, report=None):
    if report:
        report(8, "正在读取")
    if text is None or not str(text).strip():
        raise ConvertError("没有可转换的内容")
    if report:
        report(40, "正在解析")
    doc = _document_from_blocks(_plain_blocks(str(text)), "粘贴的内容")
    return _finish(doc, mode, template, report)


def run_batch(items, dest_dir, mode="preserve", template=None, on_progress=None):
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    files = []
    for item in items:
        files.append({
            "name": item.get("name") or "未命名",
            "path": item.get("path") or "",
            "percent": 0,
            "state": "等待",
            "message": "",
            "output": "",
        })
    snap = _snapshot(files, 0, False, [], [])
    _emit(snap, on_progress)
    succeeded = []
    failed = []
    count = len(files)
    for index, item in enumerate(items):
        files[index]["state"] = "正在转换"
        files[index]["message"] = "正在读取"

        def report(percent, message, current=index):
            files[current]["percent"] = int(percent)
            files[current]["message"] = message
            _emit(_snapshot(files, _overall(current, count, percent), False, succeeded, failed), on_progress)

        try:
            if "text" in item and item.get("text") is not None and not item.get("path"):
                doc = convert_text(item.get("text"), mode, template, report)
                stem = item.get("name") or "粘贴的内容"
            else:
                doc = convert_path(item.get("path"), mode, template, report)
                stem = Path(item.get("path") or item.get("name") or "未命名").stem
            target = _unique(dest, _safe_stem(stem), ".wenju")
            report(80, "正在写入")
            save(doc, str(target))
            files[index]["output"] = str(target)
            files[index]["percent"] = 100
            files[index]["state"] = "成功"
            files[index]["message"] = target.name
            succeeded.append(target.name)
        except ConvertError as exc:
            files[index]["percent"] = 100
            files[index]["state"] = "失败"
            files[index]["message"] = str(exc)
            failed.append({"name": files[index]["name"], "message": str(exc)})
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            message = str(exc) or exc.__class__.__name__
            files[index]["percent"] = 100
            files[index]["state"] = "失败"
            files[index]["message"] = message
            failed.append({"name": files[index]["name"], "message": message})
        _emit(_snapshot(files, _overall(index, count, 100), False, succeeded, failed), on_progress)
    final = _snapshot(files, 100 if count else 100, True, succeeded, failed)
    _emit(final, on_progress)
    return final


def run_export(items, dest_dir, template=None, on_progress=None):
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    files = []
    for item in items:
        files.append({
            "name": item.get("name") or Path(item.get("path") or "未命名").name,
            "path": item.get("path") or "",
            "percent": 0,
            "state": "等待",
            "message": "",
            "output": item.get("path") or "",
            "docx": "",
        })
    succeeded = []
    failed = []
    count = len(files)
    _emit(_snapshot(files, 0, False, succeeded, failed), on_progress)
    for index, item in enumerate(items):
        def report(percent, message, current=index):
            files[current]["percent"] = int(percent)
            files[current]["message"] = message
            files[current]["state"] = "正在导出"
            _emit(_snapshot(files, _overall(current, count, percent), False, succeeded, failed), on_progress)
        try:
            report(8, "正在读取")
            doc = load(item["path"])
            report(55, "正在生成 docx")
            target = _unique(dest, _safe_stem(Path(item["path"]).stem), ".docx")
            to_docx(doc, str(target), template)
            report(90, "正在写入")
            files[index]["docx"] = str(target)
            files[index]["percent"] = 100
            files[index]["state"] = "成功"
            files[index]["message"] = target.name
            succeeded.append(target.name)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            message = str(exc) or exc.__class__.__name__
            files[index]["percent"] = 100
            files[index]["state"] = "失败"
            files[index]["message"] = message
            failed.append({"name": files[index]["name"], "message": message})
        _emit(_snapshot(files, _overall(index, count, 100), False, succeeded, failed), on_progress)
    final = _snapshot(files, 100 if count else 100, True, succeeded, failed)
    _emit(final, on_progress)
    return final


def summary(snap, title):
    ok = list(snap.get("succeeded") or [])
    bad = list(snap.get("failed") or [])
    lines = [title, "成功 %d 个" % len(ok)]
    lines.extend(ok)
    lines.append("失败 %d 个" % len(bad))
    for item in bad:
        lines.append("%s：%s" % (item.get("name") or "未命名", item.get("message") or ""))
    skipped = list(snap.get("skipped") or [])
    if skipped:
        lines.append("未开始 %d 个" % len(skipped))
        lines.extend(skipped)
    return "\n".join(lines)


def execute(job):
    progress = job.get("progress")
    action = job.get("action")
    def on_progress(snap):
        if not progress:
            return
        payload = json.dumps(snap, ensure_ascii=False).encode("utf-8")
        temporary = progress + ".tmp"
        with open(temporary, "wb") as handle:
            handle.write(payload)
        os.replace(temporary, progress)
    if action == "export":
        snap = run_export(job.get("items") or [], job["outdir"], job.get("template"), on_progress)
    else:
        snap = run_batch(job.get("items") or [], job["outdir"], job.get("mode") or "preserve", job.get("template"), on_progress)
    return {"ok": True, "snapshot": snap}


def _snapshot(files, overall, finished, succeeded, failed):
    return {
        "files": json.loads(json.dumps(files, ensure_ascii=False)),
        "overall": int(overall),
        "finished": bool(finished),
        "succeeded": list(succeeded),
        "failed": json.loads(json.dumps(failed, ensure_ascii=False)),
    }


def _emit(snap, on_progress):
    if on_progress:
        on_progress(snap)


def _overall(index, count, percent):
    if count <= 0:
        return 100
    return int((index * 100 + int(percent)) / count)


def _safe_stem(name):
    stem = Path(name).stem if name else "未命名"
    cleaned = "".join("_" if char in '<>:"/\\|?*' else char for char in stem).strip()
    return cleaned or "未命名"


def _unique(directory, stem, suffix):
    path = directory / (stem + suffix)
    number = 2
    while path.exists():
        path = directory / ("%s-%d%s" % (stem, number, suffix))
        number += 1
    return path


def _unsupported(suffix):
    if suffix == ".xls":
        return "不能直接转换 .xls。请在 Excel 或 WPS 表格中另存为 .xlsx 后再拖入。"
    if suffix == ".doc":
        return "无法转换 .doc：本机没有可用的 Word、WPS 或 LibreOffice。请先在 Word 或 WPS 中另存为 .docx，再拖入转换。"
    shown = suffix or "这个类型"
    return "不支持 %s。可以转换 docx、xlsx、txt、md，以及能用本机 Word、WPS 或 LibreOffice 打开的 doc。" % shown


def _document_from_blocks(blocks, source):
    return WenjuDoc(blocks, {}, {}, {"format": "wenju", "version": 1, "source": source})


def _plain_blocks(text):
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = []
    for piece in re.split(r"\f", normalized):
        if blocks:
            blocks.append({"type": "pagebreak"})
        for paragraph in re.split(r"\n\s*\n", piece):
            body = paragraph.strip("\n")
            if not body.strip():
                continue
            blocks.append({"type": "paragraph", "style": "Normal", "runs": [{"text": body}]})
    return blocks


def _read_txt(path):
    return _document_from_blocks(_plain_blocks(_read_text(path)), Path(path).name)


def _read_md(path):
    text = _read_text(path)
    return _document_from_blocks(_markdown_blocks(text, Path(path).parent), Path(path).name)


def _read_text(path):
    data = Path(path).read_bytes()
    if not data.strip():
        raise ConvertError("文件是空的：%s" % Path(path).name)
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ConvertError("无法识别 %s 的编码。请另存为 UTF-8 后再转换。" % Path(path).name)


def _markdown_blocks(text, folder):
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks = []
    paragraph = []
    index = 0
    fenced = False

    def flush():
        if paragraph:
            body = "\n".join(paragraph).strip("\n")
            if body.strip():
                blocks.append({"type": "paragraph", "style": "Normal", "runs": [{"text": body}]})
            paragraph.clear()

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("```"):
            fenced = not fenced
            paragraph.append(line)
            index += 1
            continue
        if not fenced and stripped in ("<!-- pagebreak -->",):
            flush()
            blocks.append({"type": "pagebreak"})
            index += 1
            continue
        if not fenced and stripped in ("[TOC]", "[[TOC]]"):
            flush()
            blocks.append({"type": "toc"})
            index += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line) if not fenced else None
        if heading:
            flush()
            blocks.append({"type": "heading", "level": len(heading.group(1)), "runs": [{"text": heading.group(2).strip()}]})
            index += 1
            continue
        image = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", stripped) if not fenced else None
        if image:
            flush()
            blocks.extend(_markdown_image(image.group(1), image.group(2).strip(), folder))
            index += 1
            continue
        if not fenced and _looks_like_table(lines, index):
            flush()
            table, index = _markdown_table(lines, index)
            blocks.append(table)
            continue
        if not stripped:
            flush()
            index += 1
            continue
        paragraph.append(line)
        index += 1
    flush()
    return blocks


def _markdown_image(alt, target, folder):
    if re.match(r"^[a-z]+://", target, re.I):
        return [{"type": "paragraph", "style": "Normal", "runs": [{"text": alt or target}]}]
    path = Path(target)
    if not path.is_file():
        path = folder / target
    if not path.is_file():
        return [{"type": "paragraph", "style": "Normal", "runs": [{"text": alt or target}]}]
    payload = path.read_bytes()
    width, height = _png_size(payload)
    return [{"type": "image", "asset": path.name, "w": width, "h": height, "_bytes": payload}]


def _looks_like_table(lines, index):
    if index + 1 >= len(lines) or "|" not in lines[index]:
        return False
    return _is_separator(lines[index + 1])


def _is_separator(line):
    cells = _split_row(line)
    if not cells:
        return False
    return all(set(cell) <= set("-: ") and "-" in cell for cell in cells)


def _split_row(line):
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [cell.strip() for cell in body.split("|")]


def _markdown_table(lines, index):
    header = _split_row(lines[index])
    index += 2
    rows = [[_cell(text) for text in header]]
    while index < len(lines) and "|" in lines[index] and lines[index].strip():
        values = _split_row(lines[index])
        values += [""] * (len(header) - len(values))
        rows.append([_cell(text) for text in values[:len(header)]])
        index += 1
    return {"type": "table", "rows": rows, "merges": []}, index


def _cell(text):
    return {"runs": [{"text": text}]}


def _png_size(payload):
    if payload.startswith(b"\x89PNG\r\n\x1a\n") and len(payload) >= 24:
        return int.from_bytes(payload[16:20], "big"), int.from_bytes(payload[20:24], "big")
    return 0, 0


def _read_docx(path):
    try:
        return from_docx(path)
    except (ValueError, zipfile.BadZipFile, KeyError) as exc:
        raise ConvertError("无法读取 %s：%s" % (Path(path).name, exc))


def _read_doc(path):
    import docx_fmt
    converted = docx_fmt.convert_to_docx(path)
    if not converted:
        raise ConvertError(_unsupported(".doc"))
    return _read_docx(converted)


def _read_wenju(path):
    try:
        return load(path)
    except (ValueError, zipfile.BadZipFile, OSError) as exc:
        raise ConvertError("无法读取 %s：%s" % (Path(path).name, exc))


def _read_xlsx(path):
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise ConvertError("无法读取 %s：不是有效的 xlsx。" % Path(path).name)
    with archive:
        items = {info.filename: archive.read(info.filename) for info in archive.infolist()}
    if "xl/workbook.xml" not in items:
        raise ConvertError("无法读取 %s：缺少工作簿。" % Path(path).name)
    fonts = _xlsx_fonts(items.get("xl/styles.xml"))
    strings = _shared_strings(items.get("xl/sharedStrings.xml"))
    sheets = _sheet_targets(items)
    blocks = []
    for name, target in sheets:
        blocks.append({"type": "heading", "level": 1, "runs": [{"text": name}]})
        sheet = items.get(target)
        if sheet is None:
            continue
        blocks.append(_sheet_table(sheet, strings, fonts))
    if not blocks:
        raise ConvertError("这个工作簿没有可转换的工作表：%s" % Path(path).name)
    return _document_from_blocks(blocks, Path(path).name)


def _sheet_targets(items):
    root = ET.fromstring(items["xl/workbook.xml"])
    rels = {}
    rel_xml = items.get("xl/_rels/workbook.xml.rels")
    if rel_xml:
        for rel in ET.fromstring(rel_xml):
            rid = rel.attrib.get("Id")
            target = rel.attrib.get("Target")
            if rid and target:
                rels[rid] = target if target.startswith("xl/") else "xl/" + target.lstrip("/")
    found = []
    for sheet in root.findall(_q(SS, "sheets") + "/" + _q(SS, "sheet")):
        name = sheet.attrib.get("name") or "工作表"
        rid = sheet.attrib.get(_q(OFFICE_REL, "id"))
        target = rels.get(rid, "xl/worksheets/sheet1.xml")
        found.append((name, target))
    return found


def _q(ns, tag):
    return "{%s}%s" % (ns, tag)


def _shared_strings(payload):
    if not payload:
        return []
    root = ET.fromstring(payload)
    values = []
    for item in root.findall(_q(SS, "si")):
        values.append("".join(node.text or "" for node in item.iter(_q(SS, "t"))))
    return values


def _xlsx_fonts(payload):
    if not payload:
        return []
    root = ET.fromstring(payload)
    fonts = []
    for font in root.findall(_q(SS, "fonts") + "/" + _q(SS, "font")):
        name = font.find(_q(SS, "name"))
        size = font.find(_q(SS, "sz"))
        fonts.append({
            "bold": font.find(_q(SS, "b")) is not None,
            "font": name.attrib.get("val") if name is not None else None,
            "size": float(size.attrib["val"]) if size is not None and size.attrib.get("val") else None,
        })
    styles = []
    for xf in root.findall(_q(SS, "cellXfs") + "/" + _q(SS, "xf")):
        try:
            index = int(xf.attrib.get("fontId") or 0)
        except ValueError:
            index = 0
        styles.append(fonts[index] if 0 <= index < len(fonts) else {})
    return styles


def _sheet_table(payload, strings, fonts):
    root = ET.fromstring(payload)
    grid = {}
    max_col = 0
    for row in root.findall(".//" + _q(SS, "row")):
        try:
            r_index = int(row.attrib.get("r") or 0) - 1
        except ValueError:
            r_index = len(grid)
        if r_index < 0:
            r_index = len(grid)
        for cell in row.findall(_q(SS, "c")):
            ref = cell.attrib.get("r") or ""
            c_index = _col_index(ref)
            grid[(r_index, c_index)] = _xlsx_run(cell, strings, fonts)
            max_col = max(max_col, c_index)
    if not grid:
        return {"type": "table", "rows": [], "merges": []}
    max_row = max(key[0] for key in grid)
    rows = []
    for r_index in range(max_row + 1):
        rows.append([{"runs": [grid.get((r_index, c_index), {"text": ""})]} for c_index in range(max_col + 1)])
    return {"type": "table", "rows": rows, "merges": []}


def _col_index(ref):
    letters = "".join(char for char in ref if char.isalpha())
    if not letters:
        return 0
    number = 0
    for char in letters:
        number = number * 26 + (ord(char.upper()) - 64)
    return number - 1


def _xlsx_run(cell, strings, fonts):
    kind = cell.attrib.get("t")
    if kind == "inlineStr":
        text = "".join(node.text or "" for node in cell.iter(_q(SS, "t")))
    elif kind == "s":
        value = cell.find(_q(SS, "v"))
        try:
            text = strings[int(value.text)] if value is not None and value.text else ""
        except (ValueError, IndexError):
            text = value.text or "" if value is not None else ""
    else:
        value = cell.find(_q(SS, "v"))
        text = value.text or "" if value is not None and value.text else ""
    run = {"text": text}
    try:
        style = int(cell.attrib.get("s") or -1)
    except ValueError:
        style = -1
    if 0 <= style < len(fonts):
        font = fonts[style]
        if font.get("bold"):
            run["bold"] = True
        if font.get("font"):
            run["font"] = font["font"]
        if font.get("size"):
            run["size"] = font["size"]
    return run


def _absorb_image_bytes(doc):
    assets = dict(doc.assets)
    blocks = []
    for block in doc.blocks:
        if block.get("type") == "image" and block.get("_bytes") is not None:
            copied = dict(block)
            assets[copied["asset"]] = copied.pop("_bytes")
            blocks.append(copied)
        else:
            blocks.append(block)
    doc.blocks = blocks
    doc.assets = assets
    return doc


def _finish(doc, mode, template, report):
    _absorb_image_bytes(doc)
    if not doc.blocks:
        raise ConvertError("没有可转换的内容")
    if mode == "template":
        if report:
            report(60, "正在套用模板")
        try:
            brush(doc, template)
        except ValueError as exc:
            raise ConvertError(str(exc))
    if report:
        report(75, "正在整理文矩文件")
    return doc


_READERS.update({
    ".docx": _read_docx,
    ".doc": _read_doc,
    ".xlsx": _read_xlsx,
    ".txt": _read_txt,
    ".md": _read_md,
    ".markdown": _read_md,
    ".wenju": _read_wenju,
})
