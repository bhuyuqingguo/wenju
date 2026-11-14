"""Turn a loaded document into rows the window can draw.

This does not change the .wenju schema or the exporter. Font names stay as
they were read. display_font is only for painting.
"""
import re
import zipfile
from pathlib import Path


def chart_count(path):
    try:
        with zipfile.ZipFile(str(path)) as package:
            names = package.namelist()
    except (OSError, zipfile.BadZipFile):
        return 0
    found = 0
    for name in names:
        lowered = name.replace("\\", "/").lower()
        if lowered.endswith(".xml") and "/charts/chart" in lowered:
            found += 1
    return found


def present(doc, asset_dir, display_font, charts=0, limit=40):
    folder = Path(asset_dir)
    folder.mkdir(parents=True, exist_ok=True)
    assets = getattr(doc, "assets", None) or {}
    blocks = []
    fallbacks = []
    seen = set()
    image_seq = 0
    for block in list(getattr(doc, "blocks", None) or []):
        if len(blocks) >= limit:
            blocks.append(_placeholder("还有内容", "预览只列出前面一部分，后面的块没有画在这里。"))
            break
        kind = block.get("type") if isinstance(block, dict) else ""
        if kind in ("heading", "paragraph"):
            runs, used = _runs(block.get("runs") or [], display_font)
            fallbacks.extend(used)
            level = int(block.get("level") or (1 if kind == "heading" else 0) or 0)
            blocks.append({
                "kind": "heading" if kind == "heading" else "paragraph",
                "level": level,
                "align": _align(block),
                "text": "".join(run["text"] for run in runs),
                "html": _html(runs, _paint_size(runs, level if kind == "heading" else 0)),
                "path": "",
                "w": 0,
                "h": 0,
                "title": "",
                "note": "",
                "rows": [],
                "runs": runs,
            })
        elif kind == "table":
            blocks.append(_table(block))
        elif kind == "image":
            image_seq += 1
            blocks.append(_image(block, assets, folder, image_seq))
        elif kind == "chart":
            image_seq += 1
            blocks.append(_chart_block(block, assets, folder, image_seq))
        elif kind == "pagebreak":
            blocks.append(_placeholder("分页", "这里是分页，预览不按纸张切开。"))
        elif kind == "toc":
            blocks.append(_placeholder("目录", "目录域留在文件里。预览不展开目录条目。"))
    owned = any(isinstance(block, dict) and block.get("type") == "chart" for block in (getattr(doc, "blocks", None) or []))
    if not owned:
        for index in range(int(charts or 0)):
            blocks.append(_placeholder(
                "图表占位",
                "第 %d 个图表。界面不能重绘图表，转换也不会补画。" % (index + 1),
            ))
    for name in fallbacks:
        if name not in seen:
            seen.add(name)
    note = "预览展示已读出的标题、段落、表格和位图。画不出的图片和图表只用占位说明，不当作已经画好。"
    if seen:
        note += " 屏幕字体是显示回退，文件里的字体名不变：" + "、".join(seen) + "。"
    return blocks, note


def hold(title, note):
    return _placeholder(title, note)


def paste_blocks(text, display_font):
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        return []
    rows = []
    for part in re.split(r"\n{2,}", raw):
        part = part.strip()
        if not part:
            continue
        runs, _used = _runs([{"text": part}], display_font)
        rows.append({
            "kind": "paragraph",
            "level": 0,
            "align": "left",
            "text": part,
            "html": _html(runs, 14),
            "path": "",
            "w": 0,
            "h": 0,
            "title": "",
            "note": "",
            "rows": [],
        })
    return rows


def _runs(runs, display_font):
    view = []
    fallbacks = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        font = run.get("eastAsia") or run.get("ascii") or run.get("hAnsi") or ""
        font = str(font) if font else ""
        painted = display_font(font) if font else ""
        painted = str(painted or "")
        if font and painted and painted != font:
            fallbacks.append(font + " → " + painted)
        view.append({
            "text": run.get("text") or "",
            "font": font,
            "displayFont": painted,
            "size": run.get("size_pt") or 0,
            "bold": bool(run.get("bold")),
            "italic": bool(run.get("italic")),
        })
    if not view:
        view.append({"text": "", "font": "", "displayFont": "", "size": 0, "bold": False, "italic": False})
    return view, fallbacks


def _paint_size(runs, level):
    sizes = []
    for run in runs:
        try:
            size = float(run.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        if size > 0:
            sizes.append(size)
    base = sizes[0] if sizes else (18 if level else 14)
    if level == 1:
        base = max(base, 18)
    elif level == 2:
        base = max(base, 16)
    elif level >= 3:
        base = max(base, 15)
    return int(max(13, min(22, round(base))))


def _html(runs, size):
    parts = []
    for run in runs:
        style = ["font-size:%dpx" % size]
        family = (run.get("displayFont") or "").replace("'", "").replace('"', "")
        if family:
            style.append("font-family:'%s'" % family)
        if run.get("bold"):
            style.append("font-weight:700")
        if run.get("italic"):
            style.append("font-style:italic")
        parts.append('<span style="%s">%s</span>' % (";".join(style), _esc(run.get("text") or "")))
    return "".join(parts)


def _esc(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _align(block):
    style = block.get("style") if isinstance(block.get("style"), dict) else {}
    align = style.get("align") or block.get("align") or "left"
    if align in ("center", "right"):
        return align
    return "left"


def _table(block):
    rows = block.get("rows") or []
    merges = [item for item in (block.get("merges") or []) if isinstance(item, dict)]
    marks = {}
    for merge in merges:
        try:
            row, col = int(merge["row"]), int(merge["col"])
            rowspan, colspan = int(merge.get("rowspan") or 1), int(merge.get("colspan") or 1)
        except (KeyError, TypeError, ValueError):
            continue
        bits = []
        if colspan > 1:
            bits.append("横跨 %d 列" % colspan)
        if rowspan > 1:
            bits.append("纵跨 %d 行" % rowspan)
        if bits:
            marks[(row, col)] = "（" + "，".join(bits) + "）"
    view = []
    texts = []
    for row_index, row in enumerate(rows):
        cells = []
        for col_index, cell in enumerate(row):
            if isinstance(cell, dict) and cell.get("covered") is True:
                cells.append("（被合并）")
                continue
            pictures = [item for item in (cell.get("images") or []) if isinstance(item, dict)]
            marker = ""
            if pictures:
                marker = "［图片］" if len(pictures) == 1 else "［图片×%d］" % len(pictures)
            text = _cell_text(cell) + marker + marks.get((row_index, col_index), "")
            cells.append(text)
            if text:
                texts.append(text)
        view.append(cells)
    note = "合并单元格写在文字后面，预览不把格子画成跨行跨列。" if marks else ""
    return {
        "kind": "table",
        "level": 0,
        "align": "left",
        "text": " ".join(texts),
        "html": "",
        "path": "",
        "w": 0,
        "h": 0,
        "title": "表格",
        "note": note,
        "rows": view,
    }


def _cell_text(cell):
    if not isinstance(cell, dict):
        return ""
    return "".join((run.get("text") or "") for run in (cell.get("runs") or []) if isinstance(run, dict))


def _image(block, assets, folder, seq):
    name = str(block.get("asset") or "")
    blob = assets.get(name) or b""
    if not isinstance(blob, (bytes, bytearray)):
        blob = b""
    width = _num(block.get("w"))
    height = _num(block.get("h"))
    ext = _raster_ext(blob)
    if not ext:
        kind = _binary_kind(name, blob)
        return _placeholder(
            "图片占位",
            "界面不能绘制%s。原件仍留在文矩包里，这里没有把它画出来。" % kind,
        )
    dest = folder / ("img%d%s" % (seq, ext))
    dest.write_bytes(bytes(blob))
    return {
        "kind": "image",
        "level": 0,
        "align": "left",
        "text": "图片",
        "html": "",
        "path": dest.resolve().as_uri(),
        "w": width,
        "h": height,
        "title": "图片",
        "note": "文矩记录约 %s × %s 磅。屏幕为了能看见会放大，不是纸面大小。" % (_num_text(width), _num_text(height)),
        "rows": [],
    }


def _chart_block(block, assets, folder, seq):
    preview = str(block.get("preview") or "")
    blob = assets.get(preview) or b""
    if isinstance(blob, (bytes, bytearray)) and _raster_ext(bytes(blob)):
        shown = _image({"asset": preview, "w": block.get("w"), "h": block.get("h")}, assets, folder, seq)
        shown["title"] = "图表"
        shown["note"] = "这是图表自带的预览图。图表数据仍留在文矩包里，界面不重绘图表。"
        return shown
    return _placeholder("图表占位", "图表数据留在文矩包里。界面不能重绘图表，这里没有把它画出来。")


def _placeholder(title, note):
    return {
        "kind": "placeholder",
        "level": 0,
        "align": "left",
        "text": title + " " + note,
        "html": "",
        "path": "",
        "w": 0,
        "h": 0,
        "title": title,
        "note": note,
        "rows": [],
    }


def _num(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if number <= 0:
        return 0
    if number == int(number):
        return int(number)
    return round(number, 2)


def _num_text(value):
    if not value:
        return "未记录"
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value)


def _raster_ext(blob):
    if blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if blob.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if blob.startswith(b"GIF87a") or blob.startswith(b"GIF89a"):
        return ".gif"
    if blob.startswith(b"BM"):
        return ".bmp"
    return ""


def _binary_kind(name, blob):
    lowered = name.lower()
    if lowered.endswith(".emf") or blob.startswith(b"\x01\x00\x00\x00"):
        return " emf 图片"
    if lowered.endswith(".wmf") or blob.startswith(b"\xd7\xcd\xc6\x9a"):
        return " wmf 图片"
    if lowered.endswith(".svg"):
        return " svg 图片"
    return "这种图片"
