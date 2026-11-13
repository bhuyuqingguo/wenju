import json
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "core"))

from fontfallback import choose, reset_index
from wenju_format import WenjuDoc, from_docx, validate
from compose import load, merge, merge_export, save, to_docx

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}


def text_of(node):
    return "".join(el.text or "" for el in node.iter("{%s}t" % W))


def heading(level, text, font=None):
    run = {"text": text}
    if font:
        run["eastAsia"] = font
    return {"type": "heading", "level": level, "runs": [run]}


def paragraph(text, font=None):
    run = {"text": text}
    if font:
        run["eastAsia"] = font
    return {"type": "paragraph", "style": "Normal", "runs": [run]}


def document(blocks, header, assets=None, footer=""):
    doc = WenjuDoc(blocks=blocks, styles={}, assets=assets or {}, source={"kind": "new", "name": ""})
    doc.sections = [{"at": 0, "header": header, "footer": footer}]
    return doc


def blank(blocks):
    return WenjuDoc(blocks=blocks, styles={}, assets={}, source={"kind": "new", "name": ""})


def toc_entries(package):
    root = ET.fromstring(package["word/document.xml"])
    entries = []
    for paragraph in root.iter("{%s}p" % W):
        style = paragraph.find("w:pPr/w:pStyle", NS)
        if style is None:
            continue
        sid = style.get("{%s}val" % W) or ""
        if not sid.startswith("TOC") or sid == "TOCHeading":
            continue
        texts = [el.text or "" for el in paragraph.findall(".//w:t", NS)]
        entries.append((sid, texts))
    return entries


def header_order(package):
    rels = ET.fromstring(package["word/_rels/document.xml.rels"])
    targets = {rel.get("Id"): rel.get("Target") for rel in rels}
    root = ET.fromstring(package["word/document.xml"])
    ordered = []
    for ref in root.iter("{%s}headerReference" % W):
        target = targets[ref.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")]
        header = ET.fromstring(package["word/" + target])
        ordered.append(text_of(header).strip())
    return ordered


def main():
    import fontfallback
    fontfallback._INDEX = {"仿宋": "仿宋", "fangsong": "仿宋"}
    face, found = choose("仿宋_GB2312")
    assert found and face == "仿宋"
    reset_index()
    fontfallback._INDEX = {}
    face, found = choose("仿宋_GB2312")
    assert not found and face == "仿宋_GB2312"
    reset_index()

    picture_b = b"\x89PNG-b"
    picture_c = b"\x89PNG-c"
    first = document([
        heading(1, "一、总则"),
        paragraph("正文一段", "仿宋_GB2312"),
        heading(2, "（一）范围"),
    ], "甲")
    second = document([
        heading(1, "一、附则"),
        {"type": "table", "rows": [
            [{"runs": [{"text": "左"}, {"text": "右"}]}, {"covered": True}],
            [{"runs": [{"text": "下"}]}, {"runs": [{"text": ""}]}],
        ], "merges": [{"row": 0, "col": 0, "rowspan": 1, "colspan": 2}]},
        {"type": "image", "asset": "a.png", "w": 20, "h": 20},
    ], "乙", {"a.png": picture_b})
    third = document([
        heading(1, "二、附图"),
        {"type": "image", "asset": "a.png", "w": 20, "h": 20},
    ], "丙", {"a.png": picture_c})

    with tempfile.TemporaryDirectory(prefix="wenju-merge-") as tmp:
        folder = Path(tmp)
        save(first, str(folder / "03-甲.wenju"))
        save(second, str(folder / "01-乙.wenju"))
        save(third, str(folder / "02-丙.wenju"))
        user_order = [folder / "03-甲.wenju", folder / "01-乙.wenju", folder / "02-丙.wenju"]
        merged = merge([load(str(path)) for path in user_order])
        headings = [block for block in merged.blocks if block["type"] == "heading"]
        assert ["".join(run["text"] for run in block["runs"]) for block in headings] == ["一、总则", "（一）范围", "一、附则", "二、附图"]
        assert [block["level"] for block in headings] == [1, 2, 1, 1]
        assert list(merged.assets.values()) == [picture_b, picture_c]
        assert [section["header"] for section in merged.sections] == ["甲", "乙", "丙"]

        seen = []

        def progress(percents, overall):
            seen.append((percents, overall))

        exported = merge_export(
            [str(path) for path in user_order],
            str(folder / "合稿.wenju"),
            str(folder / "合稿.docx"),
            template={"font": "仿宋_GB2312", "number": "多级数字"},
            progress=progress,
        )
        assert seen[-1] == ([100, 100, 100], 100)
        assert [item[1] for item in seen] == sorted(item[1] for item in seen)
        assert all(item[1] <= 100 for item in seen)

        with zipfile.ZipFile(exported["wenju"]) as archive:
            packed = json.loads(archive.read("document.json").decode("utf-8"))
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            assert isinstance(packed["blocks"], list) and isinstance(packed["sections"], list)
            assert manifest["format"] == "wenju" and manifest["version"] == 1
            assert all(not name.startswith("assets/assets/") for name in archive.namelist())
            assert any(name.startswith("assets/") and name.count("/") == 1 for name in archive.namelist())
        stored = load(exported["wenju"])
        body_run = next(block["runs"][0] for block in stored.blocks if block["type"] == "paragraph")
        assert body_run["eastAsia"] == "仿宋_GB2312" and body_run["size_pt"] == 12 and "font" not in body_run
        stored_headings = [block for block in stored.blocks if block["type"] == "heading"]
        assert ["".join(run["text"] for run in block["runs"]) for block in stored_headings] == ["1. 总则", "1.1 范围", "2. 附则", "3. 附图"]
        assert [block["level"] for block in stored_headings] == [1, 2, 1, 1]

        with zipfile.ZipFile(exported["docx"]) as archive:
            assert archive.testzip() is None
            package = {name: archive.read(name) for name in archive.namelist()}
        blob = b"\n".join(package.values())
        assert b"ns0" not in package["[Content_Types].xml"]
        assert b'xmlns="http://schemas.openxmlformats.org/package/2006/content-types"' in package["[Content_Types].xml"]
        assert b"ns0" not in package["word/_rels/document.xml.rels"]
        assert b"TOC \\o \"1-3\"" in blob
        assert b"updateFields" in blob
        assert "仿宋_GB2312".encode("utf-8") in blob
        entries = toc_entries(package)
        assert [(sid, texts[0], texts[-1]) for sid, texts in entries] == [
            ("TOC1", "1. 总则", "1"),
            ("TOC2", "1.1 范围", "1"),
            ("TOC1", "2. 附则", "2"),
            ("TOC1", "3. 附图", "3"),
        ]
        assert header_order(package) == ["甲", "乙", "丙"]
        body = ET.fromstring(package["word/document.xml"])
        for block in body.iter("{%s}p" % W):
            boundary = block.find("w:pPr/w:sectPr", NS)
            page_break = [el for el in block.iter("{%s}br" % W) if el.get("{%s}type" % W) == "page"]
            assert boundary is None or not page_break
        footers = [ET.fromstring(package[name]) for name in sorted(package) if name.startswith("word/footer")]
        assert footers
        for footer in footers:
            fields = [el.text.strip() for el in footer.iter("{%s}instrText" % W) if el.text]
            assert "PAGE" in fields
        assert body.find(".//w:pgNumType", NS).get("{%s}start" % W) == "1"
        styles = [el.get("{%s}val" % W) for el in body.findall(".//w:pStyle", NS)]
        assert styles.count("Heading1") == 3
        assert styles.count("Heading2") == 1
        assert b"gridSpan" in package["word/document.xml"]
        assert text_of(body).find("左") < text_of(body).find("下")
        assert picture_b in package.values()
        assert picture_c in package.values()
        reread = from_docx(exported["docx"])
        reread_headings = [block for block in reread.blocks if block["type"] == "heading"]
        assert [block["level"] for block in reread_headings] == [1, 2, 1, 1]
        assert [block["runs"][0]["text"] for block in reread_headings] == ["1. 总则", "1.1 范围", "2. 附则", "3. 附图"]

        plain = folder / "plain.docx"
        to_docx(merge([load(str(user_order[0]))]), str(plain), template=None)
        with zipfile.ZipFile(plain) as archive:
            raw = archive.read("word/document.xml")
            footer = archive.read("word/footer1.xml")
        assert "一、总则".encode("utf-8") in raw
        assert b"TOC \\o \"1-3\"" in raw
        assert b" PAGE " in footer

        sys.path.insert(0, str(ROOT))
        from worker import execute
        progress_path = folder / "progress.json"
        result = execute({
            "action": "merge",
            "sources": [str(path) for path in user_order],
            "indexes": [2, 0, 1],
            "wenju": str(folder / "job.wenju"),
            "docx": str(folder / "job.docx"),
            "template": {"font": "仿宋_GB2312", "number": "多级数字"},
            "progress": str(progress_path),
        })
        assert result["ok"] and Path(result["output"]).is_file()
        reported = json.loads(progress_path.read_text("utf-8"))
        assert reported["overall"] == 100
        assert reported["rows"] == {"2": 100, "0": 100, "1": 100}

    many = []
    for n in range(12):
        many.append(document([heading(1, "一、第%d篇" % (n + 1))], "页眉%d" % n))
    combined = merge(many)
    combined_heads = [block for block in combined.blocks if block["type"] == "heading"]
    assert [block["runs"][0]["text"] for block in combined_heads] == ["一、第%d篇" % (n + 1) for n in range(12)]
    assert [section["header"] for section in combined.sections] == ["页眉%d" % n for n in range(12)]

    ended = document([heading(1, "一、甲"), {"type": "pagebreak"}], "页眉甲")
    followed = document([heading(1, "一、乙")], "页眉乙")
    leading = document([{"type": "pagebreak"}, heading(1, "一、乙")], "页眉乙")
    joined = merge([ended, followed])
    assert [block["type"] for block in joined.blocks].count("pagebreak") == 1
    assert [block["type"] for block in merge([followed, leading]).blocks].count("pagebreak") == 1
    with tempfile.TemporaryDirectory(prefix="wenju-once-") as tmp:
        path = Path(tmp) / "once.docx"
        to_docx(merge([
            document([heading(1, "甲标题"), paragraph("甲正文")], "甲"),
            document([{"type": "pagebreak"}, heading(1, "乙标题")], "乙"),
        ]), str(path))
        with zipfile.ZipFile(path) as archive:
            body = ET.fromstring(archive.read("word/document.xml")).find("{%s}body" % W)
        kinds = []
        for block in body.findall("{%s}p" % W):
            if any(el.get("{%s}type" % W) == "page" for el in block.iter("{%s}br" % W)):
                kinds.append("page")
            if block.find("w:pPr/w:sectPr", NS) is not None:
                kinds.append("section")
        assert kinds == ["section"]
        again = Path(tmp) / "again.docx"
        to_docx(from_docx(str(path)), str(again))
        with zipfile.ZipFile(again) as archive:
            titles = archive.read("word/document.xml").decode("utf-8").count("目录")
        assert titles == 1
    with tempfile.TemporaryDirectory(prefix="wenju-break-") as tmp:
        folder = Path(tmp)
        save(document([heading(1, "一、甲"), paragraph("甲正文")], "页眉甲", footer="页脚甲"), str(folder / "甲.wenju"))
        save(document([heading(1, "一、乙"), paragraph("乙正文")], "页眉乙", footer="页脚乙"), str(folder / "乙.wenju"))
        save(document([heading(1, "一、丙"), paragraph("丙正文")], "页眉丙", footer="页脚丙"), str(folder / "丙.wenju"))
        once = merge_export([str(folder / "甲.wenju"), str(folder / "乙.wenju")], str(folder / "一次.wenju"), str(folder / "一次.docx"))
        twice = merge_export([once["wenju"], str(folder / "丙.wenju")], str(folder / "二次.wenju"), str(folder / "二次.docx"))
        stored = load(twice["wenju"])
        active = []
        for index, block in enumerate(stored.blocks):
            section = stored.sections[0]
            for item in stored.sections:
                if item["at"] <= index:
                    section = item
            if block["type"] == "heading":
                active.append((block["runs"][0]["text"], section["header"]))
        assert active == [("一、甲", "页眉甲"), ("一、乙", "页眉乙"), ("一、丙", "页眉丙")]

    numbered = blank([
        heading(1, "2024年度工作总结"),
        heading(2, "3名成员"),
        heading(2, "（一）范围"),
    ])
    nested = blank([heading(2, "（一）直接从第二级开始")])
    with tempfile.TemporaryDirectory(prefix="wenju-number-") as tmp:
        path = Path(tmp) / "out.docx"
        to_docx(numbered, str(path), template={"font": "仿宋_GB2312", "number": "多级数字"})
        with zipfile.ZipFile(path) as archive:
            raw = archive.read("word/document.xml")
        assert "2024年度工作总结".encode("utf-8") in raw
        assert "3名成员".encode("utf-8") in raw
        assert "1.2 范围".encode("utf-8") in raw
        nested_path = Path(tmp) / "nested.docx"
        to_docx(nested, str(nested_path), template={"number": "多级数字"})
        with zipfile.ZipFile(nested_path) as archive:
            nested_raw = archive.read("word/document.xml")
        assert "1.1 直接从第二级开始".encode("utf-8") in nested_raw

    square = blank([{
        "type": "table",
        "rows": [
            [{"runs": [{"text": "甲"}, {"text": "\n"}, {"text": "乙"}, {"text": "\n"}, {"text": "丙"}, {"text": "\n"}, {"text": "丁"}]}, {"covered": True}],
            [{"covered": True}, {"covered": True}],
        ],
        "merges": [{"row": 0, "col": 0, "rowspan": 2, "colspan": 2}],
    }])
    with tempfile.TemporaryDirectory(prefix="wenju-cell-") as tmp:
        path = Path(tmp) / "out.docx"
        to_docx(square, str(path))
        with zipfile.ZipFile(path) as archive:
            raw = archive.read("word/document.xml")
        assert "丁".encode("utf-8") in raw
        root = ET.fromstring(raw)
        cell = root.find(".//{%s}tc" % W)
        assert [text_of(paragraph) for paragraph in cell.findall("{%s}p" % W)] == ["甲", "乙", "丙", "丁"]

    def table_doc(count):
        return blank([
            heading(1, "一、前"),
            {"type": "table", "rows": [[{"runs": [{"text": "r%d" % i}]}] for i in range(count)]},
            heading(1, "一、后"),
        ])

    with tempfile.TemporaryDirectory(prefix="wenju-pages-") as tmp:
        folder = Path(tmp)
        for count, last in ((30, "1"), (100, "2")):
            path = folder / ("%d.docx" % count)
            to_docx(table_doc(count), str(path), template={"number": "多级数字"})
            with zipfile.ZipFile(path) as archive:
                entries = toc_entries({name: archive.read(name) for name in archive.namelist()})
            pages = [texts[-1] for _sid, texts in entries]
            assert pages == ["1", last], pages

    png = b"\x89PNG\r\n\x1a\ncell-image"
    cell = {"runs": [{"text": "格"}], "images": [{"type": "image", "asset": "a.png", "w": 12, "h": 8}]}
    table = {"type": "table", "rows": [[cell]], "merges": []}
    merged = merge([
        document([table], "页眉甲", {"a.png": png}),
        document([table], "页眉乙", {"a.png": png}),
    ])
    assert validate(merged) == []
    names = []
    for block in merged.blocks:
        if block.get("type") != "table":
            continue
        for image in block["rows"][0][0].get("images") or []:
            names.append(image["asset"])
            assert merged.assets[image["asset"]] == png
    assert names == ["0_a.png", "1_a.png"], names
    with tempfile.TemporaryDirectory(prefix="wenju-cell-") as tmp:
        save(merged, str(Path(tmp) / "cell.wenju"))

    broken = blank([{"type": "heading", "level": 0, "runs": [{"text": "x"}]}])
    assert validate(broken)
    try:
        save(broken, str(Path(tempfile.gettempdir()) / "wenju-invalid.wenju"))
    except ValueError:
        pass
    else:
        raise AssertionError("invalid heading was saved")
    print("PASS: merge order, heading levels, TOC entries, PAGE fields, font fallback, section headers")


if __name__ == "__main__":
    main()
