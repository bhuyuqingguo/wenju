import json
import struct
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "core"))
import wenju_format as wf

W = wf.W
R = wf.R
A = wf.A
WP = wf.WP
PIC = wf.PIC
SAMPLE = ROOT / "core" / "样例" / "样例_整理前.docx"


def q(ns, tag):
    return "{%s}%s" % (ns, tag)


def main():
    png = _sample_png()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / "fixture.docx"
        _build_fixture(src, png)
        doc = wf.from_docx(src)
        _assert_fixture(doc, png, alias="仿宋_GB2312")
        package = tmp / "fixture.wenju"
        wf.save(doc, package)
        loaded = wf.load(package)
        _assert_fixture(loaded, png, alias="仿宋_GB2312")
        assert loaded.created == doc.created
        assert json.loads((zipfile.ZipFile(package).read("manifest.json")))["format"] == "wenju"
        out = tmp / "round.docx"
        wf.to_docx(loaded, out)
        again = wf.from_docx(out)
        _assert_fixture(again, png, alias="仿宋_GB2312")
        wenju_again = tmp / "again.wenju"
        wf.convert_file(out, wenju_again)
        _assert_fixture(wf.load(wenju_again), png, alias="仿宋_GB2312")
        docx_again = tmp / "again.docx"
        wf.convert_file(package, docx_again)
        _assert_fixture(wf.from_docx(docx_again), png, alias="仿宋_GB2312")
        brushed = tmp / "brushed.docx"
        wf.to_docx(doc, brushed, template={"正文": {"eastAsia": "黑体", "ascii": "Arial", "size_pt": 18, "bold": True, "align": "center"}})
        brushed_doc = wf.from_docx(brushed)
        body = next(block for block in brushed_doc.blocks if block.get("type") == "paragraph" and "正文甲" in "".join(run["text"] for run in block["runs"]))
        assert body["runs"][0]["eastAsia"] == "黑体"
        assert body["runs"][0]["size_pt"] == 18
        assert body["runs"][0]["bold"] is True
        assert body["runs"][1]["ascii"] == "Arial"
        assert body["runs"][1]["size_pt"] == 18
        kept = wf.WenjuDoc(blocks=[{"type": "paragraph", "style": "正文", "runs": [{"text": "甲", "eastAsia": "仿宋_GB2312", "mark": "keep"}]}], styles={"正文": {"eastAsia": "仿宋"}}, assets={}, title="甲")
        slot = tmp / "extra.wenju"
        wf.save(kept, slot)
        assert wf.load(slot).blocks[0]["runs"][0]["mark"] == "keep"
        bad = wf.WenjuDoc(blocks=[{"type": "heading", "level": 0, "runs": [{"text": "x"}]}], styles={}, assets={})
        assert wf.validate(bad)
        overlap = wf.WenjuDoc(blocks=[{
            "type": "table",
            "rows": [[{"runs": [{"text": "a"}]}, {"runs": [{"text": "b"}]}], [{"runs": [{"text": "c"}]}, {"runs": [{"text": "d"}]}]],
            "merges": [
                {"row": 0, "col": 0, "rowspan": 2, "colspan": 1},
                {"row": 0, "col": 0, "rowspan": 1, "colspan": 2},
            ],
        }], styles={}, assets={})
        assert any("重叠" in item for item in wf.validate(overlap))
        hidden = wf.WenjuDoc(blocks=[{
            "type": "table",
            "rows": [
                [{"runs": [{"text": "甲"}]}, {"runs": [{"text": "右"}]}],
                [{"covered": True, "runs": [{"text": "藏"}]}, {"runs": [{"text": "下"}]}],
            ],
            "merges": [{"row": 0, "col": 0, "rowspan": 2, "colspan": 1}],
        }], styles={}, assets={})
        assert wf.validate(hidden)
        try:
            wf.to_docx(hidden, tmp / "hidden.docx")
            raise AssertionError("covered text was exported")
        except ValueError:
            pass
        kept_font = wf.WenjuDoc(
            blocks=[{"type": "paragraph", "runs": [{"text": "甲", "eastAsia": "仿宋_GB2312", "ascii": "仿宋_GB2312", "hAnsi": "仿宋_GB2312"}]}],
            styles={"正文": {"eastAsia": "仿宋_GB2312"}},
            assets={},
        )
        font_docx = tmp / "font.docx"
        wf.to_docx(kept_font, font_docx)
        assert kept_font.blocks[0]["runs"][0]["eastAsia"] == "仿宋_GB2312"
        assert kept_font.blocks[0]["runs"][0]["ascii"] == "仿宋_GB2312"
        assert kept_font.styles["正文"]["eastAsia"] == "仿宋_GB2312"
        with zipfile.ZipFile(font_docx) as written:
            document_xml = written.read("word/document.xml").decode("utf-8")
            styles_xml = written.read("word/styles.xml").decode("utf-8")
        assert "仿宋_GB2312" in document_xml and "仿宋_GB2312" in styles_xml
        class Huge(bytes):
            def __len__(self):
                return wf.MAX_ASSET_BYTES + 1
        oversized = wf.WenjuDoc(
            blocks=[{"type": "paragraph", "runs": [{"text": "甲"}]}],
            styles={},
            assets={"a.bin": Huge(b"x")},
        )
        assert any("64MB" in item for item in wf.validate(oversized))
        for member in ("assets/../evil.txt", "assets\\..\\..\\evil.txt", "../evil.txt", "/tmp/interrogate-pwned.txt"):
            bad_zip = tmp / "bad-member.wenju"
            with zipfile.ZipFile(bad_zip, "w") as archive:
                archive.writestr("manifest.json", b'{"format":"wenju","version":1,"title":"t","source":{"kind":"new","name":""}}')
                archive.writestr("document.json", b'{"blocks":[{"type":"paragraph","runs":[{"text":"a"}]}]}')
                archive.writestr("styles.json", b"{}")
                archive.writestr(member, b"PWNED")
            try:
                wf.load(bad_zip)
                raise AssertionError("unsafe member loaded: %s" % member)
            except ValueError as exc:
                assert "不安全" in str(exc), exc
        missing = tmp / "missing.wenju"
        with zipfile.ZipFile(missing, "w") as archive:
            archive.writestr("document.json", b'{"blocks":[]}')
            archive.writestr("styles.json", b"{}")
        try:
            wf.load(missing)
            raise AssertionError("package without manifest loaded")
        except ValueError as exc:
            assert "manifest.json" in str(exc)
        unknown = wf.WenjuDoc(blocks=[{"type": "footnote"}], styles={}, assets={})
        assert any("无法识别" in item for item in wf.validate(unknown))
        try:
            wf.save(bad, tmp / "bad.wenju")
            raise AssertionError("invalid document was saved")
        except ValueError:
            pass
        sample = wf.from_docx(SAMPLE)
        images = [block for block in sample.blocks if block["type"] == "image"]
        tables = [block for block in sample.blocks if block["type"] == "table"]
        assert len(images) == 2, len(images)
        assert images[0]["w"] == 283.46 and images[0]["h"] == 141.73
        assert len(tables) == 1 and len(tables[0]["rows"]) == 3 and len(tables[0]["rows"][0]) == 4
        title = next(block for block in sample.blocks if "某某无人体系集成方案" in "".join(run.get("text", "") for run in block.get("runs", [])))
        assert title["runs"][0]["ascii"] == "宋体"
        assert title["runs"][0]["size_pt"] == 30
        sample_out = tmp / "sample.docx"
        wf.to_docx(sample, sample_out)
        sample_back = wf.from_docx(sample_out)
        title_back = next(block for block in sample_back.blocks if "某某无人体系集成方案" in "".join(run.get("text", "") for run in block.get("runs", [])))
        assert title_back["runs"][0]["ascii"] == "宋体" and title_back["runs"][0]["size_pt"] == 30
        assert [block["asset"] for block in sample_back.blocks if block["type"] == "image"] == [block["asset"] for block in images]
        assert sample_back.assets[images[0]["asset"]] == sample.assets[images[0]["asset"]]
        from worker import execute
        rules = json.loads((ROOT / "core" / "rules.json").read_text("utf-8-sig"))
        result = execute({"source": str(package), "rules": rules})
        assert result["ok"] and result["output"].lower().endswith(".docx"), result
        assert Path(result["output"]).is_file()
        _test_fidelity(tmp)
        _test_exported_images_do_not_overlap(tmp, png)
    screen = (ROOT / "Main.qml").read_text(encoding="utf-8")
    bridge = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "saveWenju" in screen and "exportDocx" in screen and "文矩" in screen
    assert "*.wenju" in bridge and "def saveWenju" in bridge and "def exportDocx" in bridge
    print("PASS: docx/wenju roundtrip keeps headings, merged cells, images, fonts and sizes")


def _assert_fixture(doc, png, alias):
    kinds = [block["type"] for block in doc.blocks]
    assert kinds == ["toc", "heading", "heading", "heading", "paragraph", "pagebreak", "image", "table", "table"], kinds
    levels = [block["level"] for block in doc.blocks if block["type"] == "heading"]
    assert levels == [1, 2, 3]
    headings = [block for block in doc.blocks if block["type"] == "heading"]
    assert "".join(run["text"] for run in headings[0]["runs"]) == "总标题"
    assert headings[0]["runs"][0]["eastAsia"] == "黑体"
    assert headings[0]["runs"][0]["size_pt"] == 22
    assert headings[0]["runs"][0]["bold"] is True
    assert headings[1]["runs"][0]["eastAsia"] == "楷体" and headings[1]["runs"][0]["size_pt"] == 16
    assert headings[2]["runs"][0]["eastAsia"] == "宋体" and headings[2]["runs"][0]["size_pt"] == 14
    body = doc.blocks[4]
    assert body["runs"][0]["text"] == "正文甲"
    assert body["runs"][0]["eastAsia"] == alias
    assert body["runs"][0]["size_pt"] == 16
    assert body["runs"][1]["text"] == " body"
    assert body["runs"][1]["ascii"] == "Times New Roman"
    assert body["runs"][1]["size_pt"] == 10.5
    assert body["runs"][1]["italic"] is True
    assert body["runs"][1]["color"] == "C00000"
    assert body["align"] == "both"
    assert body["indent"]["first_chars"] == 2
    assert body["line"] == {"rule": "exact", "pt": 28.95}
    assert doc.styles["正文"]["eastAsia"] == "仿宋" and doc.styles["正文"]["size_pt"] == 16
    assert doc.styles["标题 1"]["eastAsia"] == "黑体" and doc.styles["标题 1"]["size_pt"] == 22
    assert doc.styles["标题 1"]["bold"] is True
    assert doc.styles["标题 2"]["eastAsia"] == "楷体" and doc.styles["标题 3"]["size_pt"] == 14
    image = doc.blocks[6]
    assert image["w"] == 120 and image["h"] == 90
    assert doc.assets[image["asset"]] == png
    merged = doc.blocks[7]
    assert _cell(merged, 0, 0) == "合"
    assert _cell(merged, 0, 2) == "角"
    assert _cell(merged, 1, 2) == "边"
    assert _cell(merged, 2, 0) == "底" and _cell(merged, 2, 1) == "中" and _cell(merged, 2, 2) == "右"
    assert merged["rows"][0][0]["runs"][0]["eastAsia"] == "仿宋"
    assert merged["rows"][0][0]["runs"][0]["size_pt"] == 10.5
    assert {"row": 0, "col": 0, "rowspan": 2, "colspan": 2} in merged["merges"]
    assert merged["rows"][0][1]["covered"] is True and merged["rows"][1][0]["covered"] is True
    banner = doc.blocks[8]
    assert _cell(banner, 0, 0) == "通栏"
    assert {"row": 0, "col": 0, "rowspan": 1, "colspan": 3} in banner["merges"]
    assert wf.validate(doc) == []


def _cell(table, row, col):
    cell = table["rows"][row][col]
    return "".join(run.get("text", "") for run in cell.get("runs") or [])


def _sample_png():
    with zipfile.ZipFile(SAMPLE) as package:
        return package.read("word/media/image1.png")


def _build_fixture(path, png):
    files = {
        "word/document.xml": _fixture_document(),
        "word/styles.xml": _fixture_styles(),
        "word/_rels/document.xml.rels": _fixture_rels(),
        "word/media/picture.png": png,
        "[Content_Types].xml": b'<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        "_rels/.rels": b'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for name, data in files.items():
            package.writestr(name, data)


def _fixture_document():
    body = ET.Element(q(W, "body"))
    toc = ET.SubElement(body, q(W, "p"))
    instr = ET.SubElement(ET.SubElement(toc, q(W, "r")), q(W, "instrText"))
    instr.text = ' TOC \\o "1-3" '
    _paragraph(body, "总标题", style="Heading1", east="黑体", size=44, bold=True)
    _paragraph(body, "第一节", style="Heading2", east="楷体", size=32)
    _paragraph(body, "1.1 细节", style="Heading3", east="宋体", size=28)
    paragraph = ET.SubElement(body, q(W, "p"))
    ppr = ET.SubElement(paragraph, q(W, "pPr"))
    ET.SubElement(ppr, q(W, "pStyle")).set(q(W, "val"), "Normal")
    ET.SubElement(ppr, q(W, "jc")).set(q(W, "val"), "both")
    spacing = ET.SubElement(ppr, q(W, "spacing"))
    spacing.set(q(W, "line"), "579")
    spacing.set(q(W, "lineRule"), "exact")
    indent = ET.SubElement(ppr, q(W, "ind"))
    indent.set(q(W, "firstLineChars"), "200")
    _run(paragraph, "正文甲", east="仿宋_GB2312", size=32)
    _run(paragraph, " body", ascii_font="Times New Roman", size=21, italic=True, color="C00000")
    broken = ET.SubElement(body, q(W, "p"))
    ET.SubElement(ET.SubElement(broken, q(W, "r")), q(W, "br")).set(q(W, "type"), "page")
    image = ET.SubElement(body, q(W, "p"))
    run = ET.SubElement(image, q(W, "r"))
    drawing = ET.SubElement(run, q(W, "drawing"))
    inline = ET.SubElement(drawing, q(WP, "inline"))
    extent = ET.SubElement(inline, q(WP, "extent"))
    extent.set("cx", str(120 * 12700))
    extent.set("cy", str(90 * 12700))
    graphic = ET.SubElement(inline, q(A, "graphic"))
    data = ET.SubElement(graphic, q(A, "graphicData"))
    pic = ET.SubElement(data, q(PIC, "pic"))
    fill = ET.SubElement(pic, q(PIC, "blipFill"))
    ET.SubElement(fill, q(A, "blip")).set(q(R, "embed"), "rId9")
    _merged_table(body)
    _banner_table(body)
    root = ET.Element(q(W, "document"))
    root.append(body)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _paragraph(body, text, style, east, size, bold=False):
    paragraph = ET.SubElement(body, q(W, "p"))
    ppr = ET.SubElement(paragraph, q(W, "pPr"))
    ET.SubElement(ppr, q(W, "pStyle")).set(q(W, "val"), style)
    _run(paragraph, text, east=east, size=size, bold=bold)


def _run(parent, text, east=None, ascii_font=None, size=None, bold=False, italic=False, color=None):
    run = ET.SubElement(parent, q(W, "r"))
    rpr = ET.SubElement(run, q(W, "rPr"))
    fonts = ET.SubElement(rpr, q(W, "rFonts"))
    if east:
        fonts.set(q(W, "eastAsia"), east)
    if ascii_font:
        fonts.set(q(W, "ascii"), ascii_font)
        fonts.set(q(W, "hAnsi"), ascii_font)
    if size:
        ET.SubElement(rpr, q(W, "sz")).set(q(W, "val"), str(size))
    if bold:
        ET.SubElement(rpr, q(W, "b"))
    if italic:
        ET.SubElement(rpr, q(W, "i"))
    if color:
        ET.SubElement(rpr, q(W, "color")).set(q(W, "val"), color)
    node = ET.SubElement(run, q(W, "t"))
    node.text = text


def _merged_table(body):
    table = ET.SubElement(body, q(W, "tbl"))
    _row(table, [("合", 2, "restart"), ("角", 1, None)])
    _row(table, [("", 2, "continue"), ("边", 1, None)])
    _row(table, [("底", 1, None), ("中", 1, None), ("右", 1, None)])


def _banner_table(body):
    table = ET.SubElement(body, q(W, "tbl"))
    _row(table, [("通栏", 3, None)])


def _row(table, cells):
    tr = ET.SubElement(table, q(W, "tr"))
    for text, span, merge in cells:
        tc = ET.SubElement(tr, q(W, "tc"))
        tcpr = ET.SubElement(tc, q(W, "tcPr"))
        if span > 1:
            ET.SubElement(tcpr, q(W, "gridSpan")).set(q(W, "val"), str(span))
        if merge:
            node = ET.SubElement(tcpr, q(W, "vMerge"))
            if merge == "restart":
                node.set(q(W, "val"), "restart")
        paragraph = ET.SubElement(tc, q(W, "p"))
        if text:
            _run(paragraph, text, east="仿宋", size=21)


def _fixture_styles():
    root = ET.Element(q(W, "styles"))
    _style(root, "Normal", "正文", east="仿宋", size=32)
    _style(root, "Heading1", "标题 1", east="黑体", size=44, bold=True)
    _style(root, "Heading2", "标题 2", east="楷体", size=32)
    _style(root, "Heading3", "标题 3", east="宋体", size=28)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _style(root, sid, name, east, size, bold=False):
    node = ET.SubElement(root, q(W, "style"))
    node.set(q(W, "styleId"), sid)
    ET.SubElement(node, q(W, "name")).set(q(W, "val"), name)
    rpr = ET.SubElement(node, q(W, "rPr"))
    fonts = ET.SubElement(rpr, q(W, "rFonts"))
    fonts.set(q(W, "eastAsia"), east)
    ET.SubElement(rpr, q(W, "sz")).set(q(W, "val"), str(size))
    if bold:
        ET.SubElement(rpr, q(W, "b"))


def _fixture_rels():
    root = ET.Element("{http://schemas.openxmlformats.org/package/2006/relationships}Relationships")
    rel = ET.SubElement(root, "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship")
    rel.set("Id", "rId1")
    rel.set("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles")
    rel.set("Target", "styles.xml")
    image = ET.SubElement(root, "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship")
    image.set("Id", "rId9")
    image.set("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image")
    image.set("Target", "media/picture.png")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _test_fidelity(tmp):
    png = _sample_png()
    src = tmp / "fidelity.docx"
    _build_fidelity(src, png)
    doc = wf.from_docx(src)
    _assert_fidelity(doc, png)
    package = tmp / "fidelity.wenju"
    wf.save(doc, package)
    packed = json.loads(zipfile.ZipFile(package).read("document.json"))
    assert isinstance(packed["blocks"], list) and isinstance(packed["sections"], list)
    assert packed["sections"][0]["header"] == "页眉甲"
    assert packed["sections"][0]["footer"] == "页脚甲"
    loaded = wf.load(package)
    _assert_fidelity(loaded, png)
    out = tmp / "fidelity-out.docx"
    wf.to_docx(loaded, out)
    with zipfile.ZipFile(out) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
        header_xml = archive.read("word/header1.xml").decode("utf-8")
        footer_xml = archive.read("word/footer1.xml").decode("utf-8")
        media = [name for name in archive.namelist() if name.startswith("word/media/")]
    assert len(media) == 1
    assert 'w:eastAsia="仿宋_GB2312"' in document_xml
    assert 'w:eastAsia="仿宋"' not in document_xml
    assert "页眉甲" in header_xml
    assert "页脚甲" in footer_xml and "PAGE" in footer_xml
    again = wf.from_docx(out)
    _assert_fidelity(again, png)
    wrapped = tmp / "wrapped.docx"
    _build_wrapped_image(wrapped, png)
    wrapped_doc = wf.from_docx(wrapped)
    images = [block for block in wrapped_doc.blocks if block["type"] == "image"]
    assert len(images) == 1, len(images)
    assert images[0]["w"] == 120 and images[0]["h"] == 90
    assert wrapped_doc.assets[images[0]["asset"]] == png
    outside = tmp / "wrapped-outside.docx"
    _build_wrapped_image(outside, png, outside_run=True)
    outside_doc = wf.from_docx(outside)
    outside_images = [block for block in outside_doc.blocks if block["type"] == "image"]
    assert len(outside_images) == 1 and outside_images[0]["w"] == 120 and outside_images[0]["h"] == 90
    anchor = tmp / "anchor.docx"
    _build_anchor_image(anchor, png)
    anchor_doc = wf.from_docx(anchor)
    anchor_images = [block for block in anchor_doc.blocks if block["type"] == "image"]
    assert len(anchor_images) == 1 and anchor_images[0]["w"] == 80 and anchor_images[0]["h"] == 40
    _test_vector_and_chart(tmp)


def _assert_fidelity(doc, png):
    assert wf.validate(doc) == []
    headings = [block for block in doc.blocks if block["type"] == "heading"]
    assert len(headings) == 1 and headings[0]["level"] == 1
    assert "".join(run["text"] for run in headings[0]["runs"]) == "总标题"
    body = next(block for block in doc.blocks if block["type"] == "paragraph" and "正文甲" in "".join(run.get("text", "") for run in block.get("runs") or []))
    assert body["runs"][0]["eastAsia"] == "仿宋_GB2312"
    assert body["runs"][0]["ascii"] == "仿宋_GB2312"
    assert body["runs"][0]["hAnsi"] == "仿宋_GB2312"
    assert body["runs"][0]["size_pt"] == 16
    images = [block for block in doc.blocks if block["type"] == "image"]
    assert len(images) == 1
    assert images[0]["w"] == 120 and images[0]["h"] == 90
    assert doc.assets[images[0]["asset"]] == png
    table = next(block for block in doc.blocks if block["type"] == "table")
    assert {"row": 0, "col": 0, "rowspan": 1, "colspan": 2} in table["merges"]
    assert {"row": 1, "col": 0, "rowspan": 2, "colspan": 1} in table["merges"]
    assert table["rows"][0][1]["covered"] is True
    assert table["rows"][2][0]["covered"] is True
    assert _cell(table, 0, 0) == "合" and _cell(table, 1, 0) == "左" and _cell(table, 1, 1) == "右" and _cell(table, 2, 1) == "下"
    assert any(block["type"] == "pagebreak" for block in doc.blocks)
    assert any("第二页" in "".join(run.get("text", "") for run in block.get("runs") or []) for block in doc.blocks)
    assert doc.sections and doc.sections[0]["header"] == "页眉甲"
    assert doc.sections[0]["footer"] == "页脚甲"
    assert doc.sections[0]["footer_page"] is True
    assert doc.sections[0]["pgSz"]["w"] == 11906 and doc.sections[0]["pgSz"]["h"] == 16838


def _build_fidelity(path, png):
    document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="%s" xmlns:r="%s" xmlns:wp="%s" xmlns:a="%s" xmlns:pic="%s">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
      <w:r><w:rPr><w:rFonts w:eastAsia="仿宋_GB2312" w:ascii="Times New Roman" w:hAnsi="Times New Roman"/><w:sz w:val="44"/></w:rPr><w:t>总标题</w:t></w:r></w:p>
    <w:p><w:r><w:rPr><w:rFonts w:ascii="仿宋_GB2312" w:hAnsi="仿宋_GB2312"/><w:sz w:val="32"/></w:rPr><w:t>正文甲</w:t></w:r></w:p>
    <w:p><w:r><w:drawing><wp:inline><wp:extent cx="%d" cy="%d"/>
      <a:graphic><a:graphicData uri="%s"><pic:pic><pic:blipFill><a:blip r:embed="rId9"/></pic:blipFill></pic:pic></a:graphicData></a:graphic>
    </wp:inline></w:drawing></w:r></w:p>
    <w:tbl>
      <w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr><w:p><w:r><w:t>合</w:t></w:r></w:p></w:tc></w:tr>
      <w:tr>
        <w:tc><w:tcPr><w:vMerge w:val="restart"/></w:tcPr><w:p><w:r><w:t>左</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>右</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:tcPr><w:vMerge/></w:tcPr><w:p><w:r><w:t></w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>下</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
    <w:p><w:r><w:br w:type="page"/></w:r></w:p>
    <w:p><w:r><w:t>第二页</w:t></w:r></w:p>
    <w:sectPr>
      <w:headerReference w:type="default" r:id="rId20"/>
      <w:footerReference w:type="default" r:id="rId21"/>
      <w:pgSz w:w="11906" w:h="16838"/>
      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>
    </w:sectPr>
  </w:body>
</w:document>""" % (W, R, WP, A, PIC, 120 * 12700, 90 * 12700, PIC)
    styles = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="%s">
  <w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="宋体"/><w:sz w:val="21"/></w:rPr></w:rPrDefault></w:docDefaults>
  <w:style w:styleId="Heading1"><w:name w:val="heading 1"/>
    <w:pPr><w:outlineLvl w:val="0"/></w:pPr>
    <w:rPr><w:rFonts w:eastAsia="黑体"/><w:sz w:val="32"/></w:rPr>
  </w:style>
</w:styles>""" % W
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
  <Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/picture.png"/>
  <Relationship Id="rId20" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
  <Relationship Id="rId21" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
</Relationships>"""
    header = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:hdr xmlns:w="%s"><w:p><w:r><w:t>页眉甲</w:t></w:r></w:p></w:hdr>""" % W
    footer = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr xmlns:w="%s"><w:p><w:r><w:t>页脚甲</w:t></w:r>
<w:r><w:fldChar w:fldCharType="begin"/></w:r>
<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>
<w:r><w:fldChar w:fldCharType="separate"/></w:r>
<w:r><w:t>1</w:t></w:r>
<w:r><w:fldChar w:fldCharType="end"/></w:r>
</w:p></w:ftr>""" % W
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document.encode("utf-8"))
        archive.writestr("word/styles.xml", styles.encode("utf-8"))
        archive.writestr("word/_rels/document.xml.rels", rels.encode("utf-8"))
        archive.writestr("word/header1.xml", header.encode("utf-8"))
        archive.writestr("word/footer1.xml", footer.encode("utf-8"))
        archive.writestr("word/media/picture.png", png)


def _build_wrapped_image(path, png, outside_run=False):
    run_close = "</w:r>" if outside_run else ""
    run_tail = "" if outside_run else "</w:r>"
    document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="%s" xmlns:r="%s" xmlns:wp="%s" xmlns:a="%s" xmlns:pic="%s" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" xmlns:v="urn:schemas-microsoft-com:vml">
  <w:body>
    <w:p><w:r><w:t>图前</w:t>%s
      <mc:AlternateContent>
        <mc:Choice Requires="wps">
          <w:drawing><wp:inline><wp:extent cx="%d" cy="%d"/>
            <a:graphic><a:graphicData uri="%s"><pic:pic><pic:blipFill><a:blip r:embed="rId9"/></pic:blipFill></pic:pic></a:graphicData></a:graphic>
          </wp:inline></w:drawing>
        </mc:Choice>
        <mc:Fallback>
          <w:pict><v:shape style="width:120pt;height:90pt"><v:imagedata r:id="rId9"/></v:shape></w:pict>
        </mc:Fallback>
      </mc:AlternateContent>
    %s</w:p>
  </w:body>
</w:document>""" % (W, R, WP, A, PIC, run_close, 120 * 12700, 90 * 12700, PIC, run_tail)
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/picture.png"/>
</Relationships>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document.encode("utf-8"))
        archive.writestr("word/_rels/document.xml.rels", rels.encode("utf-8"))
        archive.writestr("word/media/picture.png", png)


def _build_anchor_image(path, png):
    document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="%s" xmlns:r="%s" xmlns:wp="%s" xmlns:a="%s" xmlns:pic="%s">
  <w:body>
    <w:p><w:r><w:drawing><wp:anchor>
      <wp:extent cx="%d" cy="%d"/>
      <a:graphic><a:graphicData uri="%s"><pic:pic><pic:blipFill><a:blip r:embed="rId4"/></pic:blipFill></pic:pic></a:graphicData></a:graphic>
    </wp:anchor></w:drawing></w:r></w:p>
  </w:body>
</w:document>""" % (W, R, WP, A, PIC, 80 * 12700, 40 * 12700, PIC)
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/anchor.png"/>
</Relationships>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document.encode("utf-8"))
        archive.writestr("word/_rels/document.xml.rels", rels.encode("utf-8"))
        archive.writestr("word/media/anchor.png", png)


def _emf(marker):
    data = bytearray(88)
    struct.pack_into("<I", data, 0, 1)
    struct.pack_into("<I", data, 4, 88)
    struct.pack_into("<I", data, 40, 0x464D4520)
    struct.pack_into("<I", data, 44, 0x00010000)
    struct.pack_into("<I", data, 48, 88)
    struct.pack_into("<I", data, 52, 1)
    data[80:84] = marker
    return bytes(data)


def _wmf():
    placeable = struct.pack("<IH", 0x9AC6CDD7, 0) + struct.pack("<hhhhH", 0, 0, 100, 80, 1440) + struct.pack("<IH", 0, 0)
    meta = struct.pack("<HHHIHIH", 1, 9, 0x0300, 9, 0, 0, 0)
    return placeable + meta


def _cfb(payload):
    sector = 512
    fat = bytearray(sector)
    for index in range(sector // 4):
        struct.pack_into("<I", fat, index * 4, 0xFFFFFFFF)
    struct.pack_into("<I", fat, 0, 0xFFFFFFFD)
    struct.pack_into("<I", fat, 4, 0xFFFFFFFE)
    struct.pack_into("<I", fat, 8, 0xFFFFFFFE)
    struct.pack_into("<I", fat, 12, 0xFFFFFFFE)
    mini = bytearray(sector)
    for index in range(sector // 4):
        struct.pack_into("<I", mini, index * 4, 0xFFFFFFFF)
    struct.pack_into("<I", mini, 0, 1)
    struct.pack_into("<I", mini, 4, 0xFFFFFFFE)
    directory = bytearray(sector)

    def entry(index, name, kind, start, size, child=0xFFFFFFFF):
        off = index * 128
        encoded = name.encode("utf-16le")
        directory[off:off + len(encoded)] = encoded
        struct.pack_into("<H", directory, off + 64, len(encoded) + 2)
        directory[off + 66] = kind
        struct.pack_into("<I", directory, off + 68, 0xFFFFFFFF)
        struct.pack_into("<I", directory, off + 72, 0xFFFFFFFF)
        struct.pack_into("<I", directory, off + 76, child)
        struct.pack_into("<I", directory, off + 116, start)
        struct.pack_into("<I", directory, off + 120, size)

    entry(0, "Root Entry", 5, 3, 128, child=1)
    entry(1, "CONTENTS", 2, 0, len(payload))
    stream = payload + b"\x00" * (128 - len(payload))
    stream = stream + b"\x00" * (sector - len(stream))
    header = bytearray(sector)
    header[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<H", header, 0x18, 0x003E)
    struct.pack_into("<H", header, 0x1A, 3)
    struct.pack_into("<H", header, 0x1C, 0xFFFE)
    struct.pack_into("<H", header, 0x1E, 9)
    struct.pack_into("<H", header, 0x20, 6)
    struct.pack_into("<I", header, 0x2C, 1)
    struct.pack_into("<I", header, 0x30, 1)
    struct.pack_into("<I", header, 0x38, 4096)
    struct.pack_into("<I", header, 0x3C, 2)
    struct.pack_into("<I", header, 0x40, 1)
    struct.pack_into("<I", header, 0x44, 0xFFFFFFFE)
    for index in range(109):
        struct.pack_into("<I", header, 0x4C + 4 * index, 0xFFFFFFFF)
    struct.pack_into("<I", header, 0x4C, 0)
    return bytes(header) + bytes(fat) + bytes(directory) + bytes(mini) + stream


def _zip_docx(path, document, rels, parts):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document.encode("utf-8"))
        archive.writestr("word/_rels/document.xml.rels", rels.encode("utf-8"))
        for name, data in parts.items():
            archive.writestr(name, data)


def _media_bytes(package, suffix):
    with zipfile.ZipFile(package) as archive:
        found = [archive.read(name) for name in archive.namelist() if name.replace("\\", "/").lower().endswith(suffix)]
    return found


def _content_type_map(package):
    with zipfile.ZipFile(package) as archive:
        root = ET.fromstring(archive.read("[Content_Types].xml"))
    ns = "{http://schemas.openxmlformats.org/package/2006/content-types}"
    defaults = {}
    overrides = {}
    for node in root:
        if node.tag == ns + "Default":
            defaults[node.get("Extension")] = node.get("ContentType")
        elif node.tag == ns + "Override":
            overrides[node.get("PartName")] = node.get("ContentType")
    return defaults, overrides


def _test_vector_and_chart(tmp):
    emf = _emf(b"EMF1")
    wmf = _wmf()
    pasted = _emf(b"PPT1")
    packed = _emf(b"OLE1")
    src = tmp / "vectors.docx"
    document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="%s" xmlns:r="%s" xmlns:wp="%s" xmlns:a="%s" xmlns:pic="%s" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
  <w:body>
    <w:p><w:r><w:rPr><w:rFonts w:ascii="仿宋_GB2312" w:hAnsi="仿宋_GB2312"/><w:sz w:val="32"/></w:rPr><w:t>正文甲</w:t></w:r></w:p>
    <w:p><w:r><w:drawing><wp:inline><wp:extent cx="%d" cy="%d"/>
      <a:graphic><a:graphicData uri="%s"><pic:pic><pic:blipFill><a:blip r:embed="rId2"/></pic:blipFill></pic:pic></a:graphicData></a:graphic>
    </wp:inline></w:drawing></w:r></w:p>
    <w:p><w:r><w:pict>
      <v:shape style="width:90pt;height:40pt"><v:imagedata o:relid="rId3"/></v:shape>
      <o:OLEObject ProgID="PowerPoint.Slide.12" r:id="rId8"/>
    </w:pict></w:r></w:p>
    <w:p><w:r><w:object w:dxaOrig="2880" w:dyaOrig="1440">
      <o:OLEObject ProgID="PowerPoint.Slide.8" r:id="rId5"/>
    </w:object></w:r></w:p>
    <w:p><w:r><w:object w:dxaOrig="2160" w:dyaOrig="1080">
      <o:OLEObject ProgID="Package" r:id="rId6"/>
    </w:object></w:r></w:p>
    <w:p><w:r><w:object><o:OLEObject ProgID="Package" r:id="rId7"/></w:object></w:r></w:p>
  </w:body>
</w:document>""" % (W, R, WP, A, PIC, 200 * 12700, 80 * 12700, PIC)
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/slide.emf"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/slide.wmf"/>
  <Relationship Id="rId8" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject" Target="embeddings/junk.bin"/>
  <Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject" Target="embeddings/raw.emf"/>
  <Relationship Id="rId6" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject" Target="embeddings/packed.bin"/>
  <Relationship Id="rId7" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject" Target="embeddings/note.bin"/>
</Relationships>"""
    _zip_docx(src, document, rels, {
        "word/media/slide.emf": emf,
        "word/media/slide.wmf": wmf,
        "word/embeddings/junk.bin": b"this-is-not-a-picture",
        "word/embeddings/raw.emf": pasted,
        "word/embeddings/packed.bin": _cfb(packed),
        "word/embeddings/note.bin": b"hello-not-a-picture",
    })
    doc = wf.from_docx(src)
    assert wf.validate(doc) == [], wf.validate(doc)
    run = doc.blocks[0]["runs"][0]
    assert run["text"] == "正文甲" and run["ascii"] == "仿宋_GB2312" and run["eastAsia"] == "仿宋_GB2312"
    images = [block for block in doc.blocks if block["type"] == "image"]
    assert len(images) == 4, [block.get("asset") for block in images]
    blobs = [doc.assets[block["asset"]] for block in images]
    assert emf in blobs and wmf in blobs and pasted in blobs and packed in blobs
    assert images[0]["w"] == 200 and images[0]["h"] == 80
    assert images[1]["w"] == 90 and images[1]["h"] == 40
    assert images[2]["w"] == 144 and images[2]["h"] == 72
    assert images[3]["w"] == 108 and images[3]["h"] == 54
    assert all(not blob.startswith(b"\x89PNG") for blob in blobs)
    package = tmp / "vectors.wenju"
    wf.save(doc, package)
    loaded = wf.load(package)
    out = tmp / "vectors-out.docx"
    wf.to_docx(loaded, out)
    defaults, _overrides = _content_type_map(out)
    assert defaults.get("emf") == "image/x-emf"
    assert defaults.get("wmf") == "image/x-wmf"
    assert _media_bytes(out, ".emf") 
    assert emf in _media_bytes(out, ".emf")
    assert wmf in _media_bytes(out, ".wmf")
    again = wf.from_docx(out)
    again_blobs = [again.assets[block["asset"]] for block in again.blocks if block["type"] == "image"]
    for blob in (emf, wmf, pasted, packed):
        assert blob in again_blobs
    assert again.blocks[0]["runs"][0]["ascii"] == "仿宋_GB2312"
    chart_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<c:chart><c:title><c:tx><c:v>销量</c:v></c:tx></c:title></c:chart>'
        '<c:externalData r:id="rId1"/></c:chartSpace>'
    ).encode("utf-8")
    book = b"PK\x03\x04wenju-chart-book"
    preview = _emf(b"PREV")
    chart_src = tmp / "chart.docx"
    chart_doc = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="%s" xmlns:r="%s" xmlns:wp="%s" xmlns:a="%s" xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" xmlns:v="urn:schemas-microsoft-com:vml">
  <w:body>
    <w:p><w:r><mc:AlternateContent>
      <mc:Choice Requires="c">
        <w:drawing><wp:inline><wp:extent cx="%d" cy="%d"/>
          <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart">
            <c:chart r:id="rId4"/>
          </a:graphicData></a:graphic>
        </wp:inline></w:drawing>
      </mc:Choice>
      <mc:Fallback>
        <w:pict><v:shape style="width:360pt;height:180pt"><v:imagedata r:id="rId5"/></v:shape></w:pict>
      </mc:Fallback>
    </mc:AlternateContent></w:r></w:p>
  </w:body>
</w:document>""" % (W, R, WP, A, 360 * 12700, 180 * 12700)
    chart_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" Target="charts/chart1.xml"/>
  <Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/chart-preview.emf"/>
</Relationships>"""
    chart_part_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/package" Target="../embeddings/book.xlsx"/>
</Relationships>"""
    _zip_docx(chart_src, chart_doc, chart_rels, {
        "word/charts/chart1.xml": chart_xml,
        "word/charts/_rels/chart1.xml.rels": chart_part_rels.encode("utf-8"),
        "word/embeddings/book.xlsx": book,
        "word/media/chart-preview.emf": preview,
    })
    charted = wf.from_docx(chart_src)
    assert wf.validate(charted) == [], wf.validate(charted)
    charts = [block for block in charted.blocks if block["type"] == "chart"]
    assert len(charts) == 1, [block["type"] for block in charted.blocks]
    assert not any(block["type"] == "image" for block in charted.blocks)
    assert charts[0]["w"] == 360 and charts[0]["h"] == 180
    assert charted.assets[charts[0]["asset"]] == chart_xml
    assert charted.assets[charts[0]["preview"]] == preview
    assert book in charted.assets.values()
    saved = tmp / "chart.wenju"
    wf.save(charted, saved)
    wf.to_docx(wf.load(saved), tmp / "chart-out.docx")
    _defaults, overrides = _content_type_map(tmp / "chart-out.docx")
    assert overrides.get("/word/charts/chart1.xml") == "application/vnd.openxmlformats-officedocument.drawingml.chart+xml"
    assert _defaults.get("xlsx") == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert chart_xml in _media_bytes(tmp / "chart-out.docx", ".xml")
    assert book in _media_bytes(tmp / "chart-out.docx", ".xlsx")
    assert preview in _media_bytes(tmp / "chart-out.docx", ".emf")
    document_xml = zipfile.ZipFile(tmp / "chart-out.docx").read("word/document.xml").decode("utf-8")
    requires = document_xml.find('Requires="c"')
    assert requires > 0
    tag = document_xml[document_xml.rfind("<", 0, requires):document_xml.find(">", requires)]
    assert "xmlns:c=" in tag or "xmlns:c=" in document_xml[:requires]
    restored = wf.from_docx(tmp / "chart-out.docx")
    restored_chart = next(block for block in restored.blocks if block["type"] == "chart")
    assert restored.assets[restored_chart["asset"]] == chart_xml
    assert preview in restored.assets.values()
    assert book in restored.assets.values()
    assert restored_chart["w"] == 360 and restored_chart["h"] == 180
    import compose
    compose.to_docx(charted, str(tmp / "chart-compose.docx"))
    assert chart_xml in _media_bytes(tmp / "chart-compose.docx", ".xml")
    assert book in _media_bytes(tmp / "chart-compose.docx", ".xlsx")
    print("PASS: emf/wmf/ole and chart parts round-trip without becoming bitmaps")


def _anchor(rid, name, cx, cy):
    return """<w:r><w:drawing><wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" relativeHeight="251659264" behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1">
      <wp:simplePos x="0" y="0"/>
      <wp:positionH relativeFrom="column"><wp:posOffset>0</wp:posOffset></wp:positionH>
      <wp:positionV relativeFrom="paragraph"><wp:posOffset>0</wp:posOffset></wp:positionV>
      <wp:extent cx="%d" cy="%d"/>
      <wp:docPr id="1" name="%s"/>
      <a:graphic><a:graphicData uri="%s"><pic:pic><pic:blipFill><a:blip r:embed="%s"/></pic:blipFill>
        <pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="1" cy="1"/></a:xfrm></pic:spPr>
      </pic:pic></a:graphicData></a:graphic>
    </wp:anchor></w:drawing></w:r>""" % (cx, cy, name, PIC, rid)


def _test_exported_images_do_not_overlap(tmp, png):
    """Anchored pictures that share a position and a docPr id must export inline, one after another."""
    import base64
    import clipboard_import
    import compose

    cx, cy = 80 * 12700, 40 * 12700
    document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="%s" xmlns:r="%s" xmlns:wp="%s" xmlns:a="%s" xmlns:pic="%s">
  <w:body>
    <w:p>%s%s</w:p>
    <w:tbl><w:tr><w:tc><w:p>%s%s</w:p></w:tc></w:tr></w:tbl>
  </w:body>
</w:document>""" % (W, R, WP, A, PIC, _anchor("rId4", "Picture 1", cx, cy), _anchor("rId5", "Picture 1", cx, cy), _anchor("rId6", "Picture 1", 60 * 12700, 30 * 12700), _anchor("rId7", "Picture 1", 50 * 12700, 25 * 12700))
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/a.png"/>
  <Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/b.png"/>
  <Relationship Id="rId6" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/c.png"/>
  <Relationship Id="rId7" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/d.png"/>
</Relationships>"""
    src = tmp / "stacked-anchors.docx"
    with zipfile.ZipFile(src, "w") as archive:
        archive.writestr("word/document.xml", document.encode("utf-8"))
        archive.writestr("word/_rels/document.xml.rels", rels.encode("utf-8"))
        archive.writestr("word/media/a.png", png)
        archive.writestr("word/media/b.png", png)
        archive.writestr("word/media/c.png", png)
        archive.writestr("word/media/d.png", png)
    doc = wf.from_docx(src)
    images = [block for block in doc.blocks if block["type"] == "image"]
    cell_images = []
    for block in doc.blocks:
        if block["type"] != "table":
            continue
        for row in block["rows"]:
            for cell in row:
                cell_images.extend(cell.get("images") or [])
    assert len(images) >= 2, [block["type"] for block in doc.blocks]
    assert len(cell_images) >= 2, cell_images
    wenju = tmp / "stacked.wenju"
    wf.save(doc, wenju)
    exported = tmp / "stacked-wenju.docx"
    wf.to_docx(doc, exported)
    composed = tmp / "stacked-compose.docx"
    compose.to_docx(doc, str(composed))
    merged = tmp / "stacked-merge.docx"
    compose.merge_export([str(wenju)], str(tmp / "stacked-merge.wenju"), str(merged))
    for path in (exported, composed, merged):
        _assert_drawings_do_not_overlap(path, 4)
    encoded = base64.b64encode(png).decode("ascii")
    html = '<p><img src="data:image/png;base64,%s" width="80" height="40"><img src="data:image/png;base64,%s" width="100" height="50"></p>' % (encoded, encoded)
    clip = clipboard_import.document_from_parts(html=html)
    clip_out = tmp / "clipboard-images.docx"
    wf.to_docx(clip, clip_out)
    _assert_drawings_do_not_overlap(clip_out, 2)
    print("PASS: exported images stay inline, with unique ids, and do not share a position")


def _assert_drawings_do_not_overlap(path, minimum):
    root = ET.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
    drawings = [node for node in root.iter(q(W, "drawing"))]
    assert len(drawings) >= minimum, (path.name, len(drawings))
    parents = {child: parent for parent in root.iter() for child in list(parent)}
    ids = []
    positions = []
    paragraphs = []
    for drawing in drawings:
        anchor = next(drawing.iter(q(WP, "anchor")), None)
        inline = next(drawing.iter(q(WP, "inline")), None)
        if anchor is not None:
            names = [local_name(child.tag) for child in list(anchor)]
            assert any(name.startswith("wrap") for name in names), names
            horizontal = next(anchor.iter(q(WP, "positionH")), None)
            vertical = next(anchor.iter(q(WP, "positionV")), None)
            assert horizontal is not None and vertical is not None
            positions.append((ET.tostring(horizontal), ET.tostring(vertical)))
        else:
            assert inline is not None, path.name
        doc_pr = next(drawing.iter(q(WP, "docPr")))
        ids.append(doc_pr.get("id"))
        extent = next(drawing.iter(q(WP, "extent")), None)
        shape = next(drawing.iter(q(A, "ext")), None)
        if extent is not None and shape is not None:
            assert extent.get("cx") == shape.get("cx") and extent.get("cy") == shape.get("cy")
            assert int(extent.get("cx") or 0) > 0 and int(extent.get("cy") or 0) > 0
        node = drawing
        paragraph = None
        while node is not None:
            if node.tag == q(W, "p"):
                paragraph = node
                break
            node = parents.get(node)
        assert paragraph is not None
        paragraphs.append(paragraph)
    assert len(ids) == len(set(ids)), (path.name, ids)
    assert len(positions) == len(set(positions))
    assert len(paragraphs) == len({id(item) for item in paragraphs}), path.name


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


if __name__ == "__main__":
    main()
