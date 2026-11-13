import json
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "core"))

from fontfallback import resolve
from wenju_format import WenjuDoc, from_docx, load, save, to_docx, validate
from compose import merge, merge_export

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
    return WenjuDoc(blocks, {"sections": [{"at": 0, "header": header, "footer": footer}]}, assets or {}, {"wenju": 1})


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
    assert resolve("仿宋_GB2312") == "仿宋"
    assert resolve("仿宋") == "仿宋"
    assert resolve("黑体") == "黑体"

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
            assert isinstance(packed["blocks"], list) and packed["sections"]
            assert manifest["format"] == "wenju" and manifest["version"] == 1
            assert all(not name.startswith("assets/assets/") for name in archive.namelist())
            assert any(name.startswith("assets/") and name.count("/") == 1 for name in archive.namelist())
        stored = load(exported["wenju"])
        body_run = next(block["runs"][0] for block in stored.blocks if block["type"] == "paragraph")
        assert body_run["eastAsia"] == "仿宋" and body_run["size_pt"] == 12 and "font" not in body_run
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
        assert b"\xe4\xbb\xbf\xe5\xae\x8b_GB2312" not in blob
        assert "仿宋".encode("utf-8") in blob
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
        assert [section["header"] for section in reread.sections] == ["甲", "乙", "丙"]

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

    numbered = WenjuDoc([
        heading(1, "2024年度工作总结"),
        heading(2, "3名成员"),
        heading(2, "（一）范围"),
    ], {}, {}, {"wenju": 1})
    nested = WenjuDoc([heading(2, "（一）直接从第二级开始")], {}, {}, {"wenju": 1})
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

    square = WenjuDoc([{
        "type": "table",
        "rows": [
            [{"runs": [{"text": "甲"}, {"text": "\n"}, {"text": "乙"}, {"text": "\n"}, {"text": "丙"}, {"text": "\n"}, {"text": "丁"}]}, {"covered": True}],
            [{"covered": True}, {"covered": True}],
        ],
        "merges": [{"row": 0, "col": 0, "rowspan": 2, "colspan": 2}],
    }], {}, {}, {"wenju": 1})
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
        return WenjuDoc([
            heading(1, "一、前"),
            {"type": "table", "rows": [[{"runs": [{"text": "r%d" % i}]}] for i in range(count)]},
            heading(1, "一、后"),
        ], {}, {}, {"wenju": 1})

    with tempfile.TemporaryDirectory(prefix="wenju-pages-") as tmp:
        folder = Path(tmp)
        for count, last in ((30, "1"), (100, "2")):
            path = folder / ("%d.docx" % count)
            to_docx(table_doc(count), str(path), template={"number": "多级数字"})
            with zipfile.ZipFile(path) as archive:
                entries = toc_entries({name: archive.read(name) for name in archive.namelist()})
            pages = [texts[-1] for _sid, texts in entries]
            assert pages == ["1", last], pages

    check_docx_roundtrip()

    broken = WenjuDoc([{"type": "heading", "level": 0, "runs": [{"text": "x"}]}], {}, {}, {"wenju": 1})
    assert validate(broken)
    try:
        save(broken, str(Path(tempfile.gettempdir()) / "wenju-invalid.wenju"))
    except ValueError:
        pass
    else:
        raise AssertionError("invalid heading was saved")
    print("PASS: merge order, heading levels, TOC entries, PAGE fields, font fallback, section headers")


def write_docx(path, document_xml, extras=None, rels=None):
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
    root_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
    if rels is None:
        rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>"""
    with zipfile.ZipFile(str(path), "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("word/_rels/document.xml.rels", rels)
        for name, data in (extras or {}).items():
            archive.writestr(name, data)


def check_docx_roundtrip():
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with tempfile.TemporaryDirectory(prefix="wenju-docx-") as tmp:
        folder = Path(tmp)
        cells = folder / "cells.docx"
        write_docx(cells, """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="%s"><w:body>
  <w:tbl><w:tr><w:tc>
    <w:p><w:r><w:t>10</w:t></w:r></w:p>
    <w:p><w:r><w:t>20</w:t></w:r></w:p>
  </w:tc></w:tr></w:tbl>
  <w:sectPr/>
</w:body></w:document>""" % ns)
        loaded = from_docx(str(cells))
        assert "".join(run["text"] for run in loaded.blocks[0]["rows"][0][0]["runs"]) == "10\n20"
        cell_out = folder / "cells-out.docx"
        to_docx(loaded, str(cell_out))
        with zipfile.ZipFile(cell_out) as archive:
            cell_root = ET.fromstring(archive.read("word/document.xml"))
        cell = cell_root.find(".//{%s}tc" % W)
        assert [text_of(paragraph) for paragraph in cell.findall("{%s}p" % W)] == ["10", "20"]

        before = folder / "before.docx"
        write_docx(before, """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="%s"><w:body>
  <w:p><w:r><w:t>甲</w:t></w:r></w:p>
  <w:p><w:pPr><w:pageBreakBefore/></w:pPr><w:r><w:t>乙</w:t></w:r></w:p>
  <w:sectPr/>
</w:body></w:document>""" % ns)
        loaded = from_docx(str(before))
        assert [block["type"] for block in loaded.blocks] == ["paragraph", "pagebreak", "paragraph"]

        split = folder / "split.docx"
        write_docx(split, """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="%s"><w:body>
  <w:p><w:r><w:t>甲</w:t></w:r></w:p>
  <w:p><w:r><w:br w:type="page"/></w:r><w:r><w:t>乙</w:t></w:r></w:p>
  <w:sectPr/>
</w:body></w:document>""" % ns)
        loaded = from_docx(str(split))
        assert [(block["type"], "".join(run.get("text", "") for run in block.get("runs") or [])) for block in loaded.blocks] == [
            ("paragraph", "甲"), ("pagebreak", ""), ("paragraph", "乙"),
        ]

        continuous = folder / "continuous.docx"
        header = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:hdr xmlns:w="%s"><w:p><w:r><w:t>%%s</w:t></w:r></w:p></w:hdr>""" % ns
        rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header2.xml"/>
</Relationships>"""
        write_docx(continuous, """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="%s" xmlns:r="%s"><w:body>
  <w:p><w:pPr><w:sectPr><w:type w:val="continuous"/><w:headerReference w:type="default" r:id="rId2"/></w:sectPr></w:pPr><w:r><w:t>甲</w:t></w:r></w:p>
  <w:p><w:r><w:t>乙</w:t></w:r></w:p>
  <w:sectPr><w:headerReference w:type="default" r:id="rId3"/></w:sectPr>
</w:body></w:document>""" % (ns, rel), {
            "word/header1.xml": header % "连续甲",
            "word/header2.xml": header % "连续乙",
        }, rels)
        loaded = from_docx(str(continuous))
        assert loaded.sections[1]["break"] == "continuous"
        out = folder / "continuous-out.docx"
        to_docx(loaded, str(out))
        with zipfile.ZipFile(out) as archive:
            body = archive.read("word/document.xml")
        assert b'w:val="continuous"' in body
        assert b'w:val="nextPage"' not in body

        even = folder / "even.docx"
        write_docx(even, """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="%s" xmlns:r="%s"><w:body>
  <w:p><w:r><w:t>正文</w:t></w:r></w:p>
  <w:sectPr>
    <w:headerReference w:type="even" r:id="rId2"/>
    <w:headerReference w:type="default" r:id="rId3"/>
  </w:sectPr>
</w:body></w:document>""" % (ns, rel), {
            "word/header1.xml": header % "偶数页眉",
            "word/header2.xml": header % "默认页眉",
        }, rels)
        loaded = from_docx(str(even))
        assert loaded.sections[0]["header"] == "默认页眉"

        caption = folder / "caption.docx"
        write_docx(caption, """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="%s" xmlns:r="%s" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><w:body>
  <w:p><w:r><w:t>图注文字</w:t></w:r><w:r><w:drawing><wp:inline><wp:extent cx="190500" cy="190500"/><wp:docPr id="1" name="Picture1"/>
  <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:blipFill><a:blip r:embed="rId2"/></pic:blipFill></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>
  <w:sectPr/>
</w:body></w:document>""" % (ns, rel), {"word/media/a.png": b"\x89PNG-caption"}, """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/a.png"/>
</Relationships>""")
        loaded = from_docx(str(caption))
        assert [block["type"] for block in loaded.blocks] == ["paragraph", "image"]
        assert loaded.blocks[0]["runs"][0]["text"] == "图注文字"
        assert loaded.assets["image1.png"] == b"\x89PNG-caption"
        assert loaded.blocks[1]["w"] > 0 and loaded.blocks[1]["h"] > 0

        sections = folder / "sections.docx"
        write_docx(sections, """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="%s"><w:body>
  <w:p><w:pPr><w:pStyle w:val="Heading1"/><w:sectPr><w:type w:val="nextPage"/></w:sectPr></w:pPr><w:r><w:t>甲</w:t></w:r></w:p>
  <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>乙</w:t></w:r></w:p>
  <w:sectPr/>
</w:body></w:document>""" % ns)
        loaded = from_docx(str(sections))
        out = folder / "sections-out.docx"
        to_docx(loaded, str(out))
        with zipfile.ZipFile(out) as archive:
            body = ET.fromstring(archive.read("word/document.xml"))
        pages = []
        for paragraph in body.iter("{%s}p" % W):
            style = paragraph.find("w:pPr/w:pStyle", NS)
            if style is None or not (style.get("{%s}val" % W) or "").startswith("TOC") or style.get("{%s}val" % W) == "TOCHeading":
                continue
            texts = [el.text or "" for el in paragraph.findall(".//w:t", NS)]
            pages.append((texts[0], texts[-1]))
        assert pages == [("甲", "1"), ("乙", "2")]


if __name__ == "__main__":
    main()
