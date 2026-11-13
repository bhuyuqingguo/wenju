import json
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
        _assert_fixture(again, png, alias="仿宋")
        wenju_again = tmp / "again.wenju"
        wf.convert_file(out, wenju_again)
        _assert_fixture(wf.load(wenju_again), png, alias="仿宋")
        docx_again = tmp / "again.docx"
        wf.convert_file(package, docx_again)
        _assert_fixture(wf.from_docx(docx_again), png, alias="仿宋")
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
        wf.to_docx(kept_font, tmp / "font.docx")
        assert kept_font.blocks[0]["runs"][0]["eastAsia"] == "仿宋_GB2312"
        assert kept_font.styles["正文"]["eastAsia"] == "仿宋_GB2312"
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


if __name__ == "__main__":
    main()
