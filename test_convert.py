import base64
import datetime
import json
import os
import struct
import sys
import tempfile
import zipfile
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))

import convert
import wenju_format
from wenju_format import WenjuDoc, from_docx, load, save, to_docx, validate

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
TEMPLATE = {
    "字体": {"正文": "仿宋_GB2312", "一级标题": "黑体", "表格": "仿宋_GB2312"},
    "正文": {"字号": "三号", "加粗": False, "保留加粗斜体下划线": True},
    "标题": {"一级": {"字号": "三号", "加粗": True}},
}


def text_of(doc):
    found = []
    for block in doc.blocks:
        if block["type"] in ("heading", "paragraph"):
            found.append("".join(run["text"] for run in block["runs"]))
        elif block["type"] == "table":
            for row in block["rows"]:
                for cell in row:
                    if not isinstance(cell, dict) or cell.get("covered") is True:
                        continue
                    found.append("".join(run.get("text", "") for run in cell.get("runs") or []))
    return found


def write_docx(path):
    document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>题目</w:t></w:r></w:p>
    <w:p><w:r><w:rPr><w:b/><w:rFonts w:eastAsia="楷体" w:ascii="楷体"/><w:sz w:val="24"/></w:rPr><w:t>正文</w:t></w:r></w:p>
    <w:tbl>
      <w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr><w:p><w:r><w:t>合</w:t></w:r></w:p></w:tc></w:tr>
      <w:tr><w:tc><w:p><w:r><w:t>甲</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>乙</w:t></w:r></w:p></w:tc></w:tr>
    </w:tbl>
    <w:p><w:r><w:br w:type="page"/></w:r></w:p>
    <w:p><w:r><w:instrText xml:space="preserve"> TOC \\o "1-3" </w:instrText></w:r></w:p>
    <w:p><w:r><w:drawing><wp:inline><wp:extent cx="914400" cy="914400"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:blipFill><a:blip r:embed="rId5"/></pic:blipFill></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>
  </w:body>
</w:document>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/pixel.png"/>
</Relationships>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document.encode("utf-8"))
        archive.writestr("word/_rels/document.xml.rels", rels.encode("utf-8"))
        archive.writestr("word/media/pixel.png", PNG)


def write_xlsx(path):
    workbook = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="成绩" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""
    styles = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="14"/><name val="黑体"/></font></fonts>
  <cellXfs count="2"><xf fontId="0"/><xf fontId="1"/></cellXfs>
</styleSheet>"""
    strings = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>甲</t></si></sst>"""
    sheet = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" s="1" t="inlineStr"><is><t>姓名</t></is></c><c r="B1" t="inlineStr"><is><t>分数</t></is></c></row>
    <row r="2"><c r="A2" t="s"><v>0</v></c><c r="B2"><v>10</v></c></row>
  </sheetData>
</worksheet>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook.encode("utf-8"))
        archive.writestr("xl/_rels/workbook.xml.rels", rels.encode("utf-8"))
        archive.writestr("xl/styles.xml", styles.encode("utf-8"))
        archive.writestr("xl/sharedStrings.xml", strings.encode("utf-8"))
        archive.writestr("xl/worksheets/sheet1.xml", sheet.encode("utf-8"))


def docx_texts(path):
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    return "".join(node.text or "" for node in root.iter("{%s}t" % W))


def test_docx_roundtrip(tmp):
    source = tmp / "sample.docx"
    write_docx(source)
    doc = from_docx(str(source))
    assert [block["type"] for block in doc.blocks] == ["heading", "paragraph", "table", "pagebreak", "toc", "image"]
    assert doc.blocks[0]["level"] == 1
    assert text_of(doc)[0] == "题目"
    run = doc.blocks[1]["runs"][0]
    assert run["text"] == "正文" and run["bold"] is True and run["eastAsia"] == "楷体" and run["size_pt"] == 12
    assert doc.blocks[2]["rows"][0][0]["runs"][0]["text"] == "合"
    assert doc.blocks[2]["merges"] == [{"row": 0, "col": 0, "rowspan": 1, "colspan": 2}]
    assert doc.blocks[2]["rows"][1][1]["runs"][0]["text"] == "乙"
    assert doc.blocks[5]["w"] == 72 and doc.blocks[5]["h"] == 72
    assert doc.assets["pixel.png"] == PNG
    saved = tmp / "sample.wenju"
    save(doc, str(saved))
    with zipfile.ZipFile(saved) as archive:
        assert json.loads(archive.read("document.json"))["blocks"][0]["type"] == "heading"
        assert "assets/pixel.png" in archive.namelist()
    again = load(str(saved))
    assert text_of(again) == text_of(doc)
    exported = tmp / "out.docx"
    to_docx(again, str(exported))
    assert "题目" in docx_texts(exported) and "正文" in docx_texts(exported) and "合" in docx_texts(exported)
    restored = from_docx(str(exported))
    assert restored.assets["pixel.png"] == PNG
    assert any(block["type"] == "toc" for block in restored.blocks)
    assert any(block["type"] == "pagebreak" for block in restored.blocks)


def test_template_brush(tmp):
    source = tmp / "brush.docx"
    write_docx(source)
    kept = convert.convert_path(str(source), "preserve")
    assert kept.blocks[1]["runs"][0]["eastAsia"] == "楷体"
    brushed = convert.convert_path(str(source), "template", TEMPLATE)
    heading = brushed.blocks[0]["runs"][0]
    body = brushed.blocks[1]["runs"][0]
    assert heading["eastAsia"] == "黑体" and heading["bold"] is True and heading["size_pt"] == 16
    assert body["eastAsia"] == "仿宋_GB2312" and body["size_pt"] == 16 and body["bold"] is True
    plain = convert.convert_text("一段正文", "template", TEMPLATE)
    assert plain.blocks[0]["runs"][0]["eastAsia"] == "仿宋_GB2312"
    assert "bold" not in plain.blocks[0]["runs"][0]
    cleared = dict(TEMPLATE)
    cleared["正文"] = dict(TEMPLATE["正文"], 保留加粗斜体下划线=False)
    stripped = convert.convert_path(str(source), "template", cleared)
    assert "bold" not in stripped.blocks[1]["runs"][0]
    exported = tmp / "brushed.docx"
    convert.brush(kept, TEMPLATE)
    to_docx(kept, str(exported))
    xml = zipfile.ZipFile(exported).read("word/document.xml").decode("utf-8")
    assert 'w:eastAsia="仿宋_GB2312"' in xml
    try:
        convert.convert_text("正文", "template", None)
    except convert.ConvertError as exc:
        assert "模板" in str(exc)
    else:
        raise AssertionError("template mode without rules should fail")


def test_txt_md_paste(tmp):
    txt = tmp / "note.txt"
    txt.write_text("# 不是标题\n\n第一段\n\n第二段\f第三段\n", encoding="utf-8")
    doc = convert.convert_path(str(txt))
    assert [block["type"] for block in doc.blocks] == ["paragraph", "paragraph", "paragraph", "pagebreak", "paragraph"]
    assert doc.blocks[0]["runs"][0]["text"].startswith("# 不是标题")
    md = tmp / "note.md"
    image = tmp / "pixel.png"
    image.write_bytes(PNG)
    md.write_text("# 标题\n\n正文一段。\n\n| 甲 | 乙 |\n| --- | --- |\n| 1 | 2 |\n\n<!-- pagebreak -->\n\n[TOC]\n\n![点](pixel.png)\n", encoding="utf-8")
    doc = convert.convert_path(str(md))
    kinds = [block["type"] for block in doc.blocks]
    assert kinds == ["heading", "paragraph", "table", "pagebreak", "toc", "image"]
    assert doc.blocks[0]["level"] == 1 and doc.blocks[0]["runs"][0]["text"] == "标题"
    assert doc.blocks[2]["rows"][1][1]["runs"][0]["text"] == "2"
    assert doc.assets["pixel.png"] == PNG
    pasted = convert.convert_text("你好\n\n世界")
    assert ["".join(run["text"] for run in block["runs"]) for block in pasted.blocks] == ["你好", "世界"]
    try:
        convert.convert_text("  \n")
    except convert.ConvertError as exc:
        assert "没有可转换的内容" in str(exc)
    else:
        raise AssertionError("blank paste should fail")


def test_xlsx(tmp):
    path = tmp / "book.xlsx"
    write_xlsx(path)
    doc = convert.convert_path(str(path))
    assert doc.blocks[0]["type"] == "heading" and doc.blocks[0]["runs"][0]["text"] == "成绩"
    table = doc.blocks[1]
    assert table["rows"][0][0]["runs"][0]["text"] == "姓名"
    assert table["rows"][0][0]["runs"][0]["bold"] is True
    assert table["rows"][0][0]["runs"][0]["eastAsia"] == "黑体"
    assert table["rows"][1][0]["runs"][0]["text"] == "甲"
    assert table["rows"][1][1]["runs"][0]["text"] == "10"


def test_doc_messages(tmp):
    source = tmp / "old.doc"
    source.write_bytes(b"not a word file")
    import docx_fmt
    original = docx_fmt.convert_to_docx
    docx_fmt.convert_to_docx = lambda _src: None
    try:
        try:
            convert.convert_path(str(source))
        except convert.ConvertError as exc:
            assert "另存为" in str(exc) and ".docx" in str(exc)
        else:
            raise AssertionError("missing converter should explain the next step")
        docx = tmp / "made.docx"
        write_docx(docx)
        docx_fmt.convert_to_docx = lambda _src: str(docx)
        doc = convert.convert_path(str(source))
        assert "题目" in text_of(doc)
    finally:
        docx_fmt.convert_to_docx = original
    xls = tmp / "old.xls"
    xls.write_bytes(b"spreadsheet")
    try:
        convert.convert_path(str(xls))
    except convert.ConvertError as exc:
        assert ".xlsx" in str(exc)
    else:
        raise AssertionError("xls should ask for xlsx")


def test_validate_and_batch(tmp):
    broken = WenjuDoc(blocks=[{"type": "image", "asset": "missing.png", "w": 1, "h": 1}], styles={}, assets={})
    errors = validate(broken)
    assert any("找不到图片" in error for error in errors)
    bad_level = WenjuDoc(blocks=[{"type": "heading", "level": 0, "runs": [{"text": "x"}]}], styles={}, assets={})
    assert validate(bad_level)
    good = tmp / "ok.txt"
    bad = tmp / "nope.rtf"
    good.write_text("可以转换\n", encoding="utf-8")
    bad.write_bytes(b"rtf")
    seen = []
    snap = convert.run_batch(
        [{"name": "ok.txt", "path": str(good)}, {"name": "nope.rtf", "path": str(bad)}],
        tmp / "out",
        on_progress=seen.append,
    )
    assert snap["finished"] is True and snap["overall"] == 100
    assert snap["files"][0]["percent"] == 100 and snap["files"][0]["state"] == "成功"
    assert snap["files"][1]["state"] == "失败"
    assert any(0 < item["overall"] < 100 and item["finished"] is False for item in seen)
    assert any(item["files"][0]["percent"] not in (0, 100) for item in seen)
    assert Path(snap["files"][0]["output"]).suffix == ".wenju"
    loaded = load(snap["files"][0]["output"])
    assert text_of(loaded) == ["可以转换"]
    message = convert.summary(snap, "转换完成")
    assert message.startswith("转换完成")
    assert "成功 1 个" in message and "ok.wenju" in message
    assert "失败 1 个" in message and "nope.rtf" in message
    exported = convert.run_export(
        [{"name": "ok.txt", "path": snap["files"][0]["output"]}],
        tmp / "docx",
    )
    assert exported["files"][0]["state"] == "成功"
    assert "可以转换" in docx_texts(exported["files"][0]["docx"])
    import worker
    job = {
        "action": "convert",
        "mode": "preserve",
        "items": [{"name": "ok.txt", "path": str(good)}],
        "outdir": str(tmp / "worker"),
        "progress": str(tmp / "progress.json"),
    }
    result = worker.execute(job)
    assert result["ok"] and result["snapshot"]["finished"]
    assert json.loads((tmp / "progress.json").read_text("utf-8"))["overall"] == 100


def test_vertical_merge(tmp):
    doc = WenjuDoc(blocks=[{
        "type": "table",
        "rows": [
            [{"runs": [{"text": "竖"}]}, {"runs": [{"text": "右"}]}],
            [{"covered": True}, {"runs": [{"text": "下"}]}],
        ],
        "merges": [{"row": 0, "col": 0, "rowspan": 2, "colspan": 1}],
    }], styles={}, assets={})
    path = tmp / "merge.docx"
    to_docx(doc, str(path))
    restored = from_docx(str(path))
    merge = restored.blocks[0]["merges"][0]
    assert merge["rowspan"] == 2 and merge["colspan"] == 1
    assert restored.blocks[0]["rows"][1][1]["runs"][0]["text"] == "下"


def pack_docx(path, body, styles=None):
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="%s" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<w:body>%s</w:body></w:document>"
    ) % (W, body)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document.encode("utf-8"))
        if styles:
            archive.writestr("word/styles.xml", styles.encode("utf-8"))


def test_kept_content(tmp):
    link = tmp / "link.docx"
    pack_docx(link, (
        "<w:p><w:r><w:t>前</w:t></w:r>"
        '<w:hyperlink r:id="rId9"><w:r><w:rPr><w:u w:val="single"/><w:color w:val="0000FF"/></w:rPr><w:t>链接</w:t></w:r></w:hyperlink>'
        "<w:r><w:t>后</w:t></w:r></w:p>"
    ))
    linked = from_docx(str(link))
    assert text_of(linked) == ["前链接后"]
    assert [run["text"] for run in linked.blocks[0]["runs"]] == ["前", "链接", "后"]

    mixed = tmp / "mixed.docx"
    pack_docx(mixed, (
        "<w:p><w:r><w:t>甲</w:t></w:r><w:ins><w:r><w:t>插入</w:t></w:r></w:ins>"
        "<w:sdt><w:sdtContent><w:r><w:t>控件</w:t></w:r></w:sdtContent></w:sdt>"
        '<w:fldSimple w:instr="DATE"><w:r><w:t>2026年11月13日</w:t></w:r></w:fldSimple>'
        "<w:r><w:t>乙</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>姓名</w:t><w:tab/><w:t>张三</w:t></w:r></w:p>"
    ))
    assert text_of(from_docx(str(mixed))) == ["甲插入控件乙", "姓名张三"]

    table = tmp / "runs.docx"
    pack_docx(table, (
        "<w:tbl><w:tr><w:tc><w:p>"
        "<w:r><w:rPr><w:b/></w:rPr><w:t>粗</w:t></w:r>"
        "<w:r><w:t>常</w:t></w:r>"
        '<w:r><w:rPr><w:i/><w:rFonts w:eastAsia="楷体"/><w:sz w:val="32"/></w:rPr><w:t>斜</w:t></w:r>'
        "</w:p></w:tc></w:tr></w:tbl>"
    ))
    runs = from_docx(str(table)).blocks[0]["rows"][0][0]["runs"]
    assert runs[0]["text"] == "粗" and runs[0].get("bold") is True
    assert runs[1]["text"] == "常" and "bold" not in runs[1]
    assert runs[2]["text"] == "斜" and runs[2].get("italic") is True
    assert runs[2]["eastAsia"] == "楷体" and runs[2]["size_pt"] == 16

    styles = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:styles xmlns:w="%s"><w:style w:styleId="Heading1"><w:name w:val="heading 1"/>'
        '<w:rPr><w:b/><w:rFonts w:eastAsia="黑体"/><w:sz w:val="32"/><w:color w:val="FF0000"/></w:rPr>'
        "</w:style></w:styles>"
    ) % W
    styled = tmp / "styled.docx"
    pack_docx(styled, (
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>题目</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
        '<w:r><w:rPr><w:b w:val="false"/></w:rPr><w:t>不加粗</w:t></w:r></w:p>'
    ), styles)
    styled_doc = from_docx(str(styled))
    heading = styled_doc.blocks[0]["runs"][0]
    named = styled_doc.styles["heading 1"]
    assert heading["text"] == "题目" and heading.get("bold") is True
    assert named["bold"] is True and named["eastAsia"] == "黑体"
    assert named["size_pt"] == 16
    assert styled_doc.blocks[1]["runs"][0].get("bold") is False

    wrapped = tmp / "sdt.docx"
    pack_docx(wrapped, (
        "<w:sdt><w:sdtContent>"
        "<w:p><w:r><w:t>标题</w:t></w:r></w:p>"
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>单元格</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
        "</w:sdtContent></w:sdt>"
    ))
    assert text_of(from_docx(str(wrapped))) == ["标题", "单元格"]

    nested = tmp / "nested.docx"
    pack_docx(nested, (
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>外</w:t></w:r></w:p>"
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>内层</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
        "</w:tc></w:tr></w:tbl>"
    ))
    assert text_of(from_docx(str(nested))) == ["外"]

    box = tmp / "box.docx"
    pack_docx(box, (
        "<w:p><w:r><w:t>正文</w:t></w:r></w:p>"
        "<w:p><w:r><w:drawing><w:txbxContent><w:p><w:r><w:t>红头标题</w:t></w:r></w:p></w:txbxContent></w:drawing></w:r></w:p>"
    ))
    assert text_of(from_docx(str(box))) == ["正文", ""]
    only = tmp / "only-box.docx"
    pack_docx(only, "<w:p><w:r><w:drawing><w:txbxContent><w:p><w:r><w:t>红头标题</w:t></w:r></w:p></w:txbxContent></w:drawing></w:r></w:p>")
    assert text_of(convert.convert_path(str(only), "preserve")) == [""]

    fonts = tmp / "fonts.docx"
    pack_docx(fonts, '<w:p><w:r><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="宋体"/><w:sz w:val="21"/></w:rPr><w:t>A中</w:t></w:r></w:p>')
    font_run = from_docx(str(fonts)).blocks[0]["runs"][0]
    assert font_run["eastAsia"] == "宋体" and font_run["ascii"] == "Times New Roman" and font_run["hAnsi"] == "Times New Roman"
    exported = tmp / "fonts-out.docx"
    to_docx(from_docx(str(fonts)), str(exported))
    root = ET.fromstring(zipfile.ZipFile(exported).read("word/document.xml"))
    rfonts = root.find(".//{%s}rFonts" % W)
    assert rfonts.attrib["{%s}eastAsia" % W] == "宋体"
    assert rfonts.attrib["{%s}ascii" % W] == "Times New Roman"

    spaced = WenjuDoc(blocks=[{"type": "paragraph", "style": "Normal", "runs": [{"text": "你好  世界"}]}], styles={}, assets={})
    spaced_path = tmp / "space.docx"
    to_docx(spaced, str(spaced_path))
    space_root = ET.fromstring(zipfile.ZipFile(spaced_path).read("word/document.xml"))
    text_node = space_root.find(".//{%s}t" % W)
    assert text_node.text == "你好  世界"
    assert text_node.attrib["{http://www.w3.org/XML/1998/namespace}space"] == "preserve"

    note = tmp / "note.txt"
    note.write_bytes("第一段\n\n第二段".encode("utf-16"))
    assert text_of(convert.convert_path(str(note), "preserve")) == ["第一段", "第二段"]

    one = tmp / "a" / "pixel.png"
    two = tmp / "b" / "pixel.png"
    one.parent.mkdir()
    two.parent.mkdir()
    one.write_bytes(b"AAA")
    two.write_bytes(b"BBB")
    md = tmp / "pics.md"
    md.write_text("![](a/pixel.png)\n\n![](b/pixel.png)\n", encoding="utf-8")
    pictures = convert.convert_path(str(md), "preserve")
    assert pictures.assets["pixel.png"] == b"AAA"
    assert pictures.assets["pixel-2.png"] == b"BBB"
    assert [block["asset"] for block in pictures.blocks] == ["pixel.png", "pixel-2.png"]

    sheet = tmp / "abs.xlsx"
    write_abs_xlsx(sheet)
    assert "姓名" in text_of(convert.convert_path(str(sheet), "preserve"))
    bare = tmp / "bare.xlsx"
    write_bare_xlsx(bare)
    assert text_of(convert.convert_path(str(bare), "preserve"))[1:] == ["甲", "乙"]

    ok = tmp / "ok-later.txt"
    bad = tmp / "bad.docx"
    later = tmp / "later.txt"
    ok.write_text("好\n", encoding="utf-8")
    later.write_text("后\n", encoding="utf-8")
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("word/document.xml", b"<w:document><unbound")
    snap = convert.run_batch(
        [
            {"name": "ok-later.txt", "path": str(ok)},
            {"name": "bad.docx", "path": str(bad)},
            {"name": "later.txt", "path": str(later)},
        ],
        tmp / "kept-out",
    )
    assert snap["finished"] is True
    assert snap["files"][1]["state"] == "失败"
    assert snap["files"][1]["message"].startswith("无法读取 bad.docx")
    assert "ParseError" not in snap["files"][1]["message"]
    assert snap["files"][2]["state"] == "成功"


def write_abs_xlsx(path):
    workbook = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="成绩" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="/xl/worksheets/sheet1.xml"/>
</Relationships>"""
    sheet = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
  <row r="1"><c r="A1" t="inlineStr"><is><t>姓名</t></is></c></row>
</sheetData></worksheet>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook.encode("utf-8"))
        archive.writestr("xl/_rels/workbook.xml.rels", rels.encode("utf-8"))
        archive.writestr("xl/worksheets/sheet1.xml", sheet.encode("utf-8"))


def write_bare_xlsx(path):
    workbook = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="表" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""
    sheet = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
  <row r="1"><c t="inlineStr"><is><t>甲</t></is></c><c t="inlineStr"><is><t>乙</t></is></c></row>
</sheetData></worksheet>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook.encode("utf-8"))
        archive.writestr("xl/_rels/workbook.xml.rels", rels.encode("utf-8"))
        archive.writestr("xl/worksheets/sheet1.xml", sheet.encode("utf-8"))


def test_edges(tmp):
    broken = tmp / "break.docx"
    pack_docx(broken, (
        '<w:p><w:r><w:rPr><w:b/><w:rFonts w:eastAsia="楷体"/><w:sz w:val="32"/></w:rPr>'
        '<w:t>粗</w:t><w:br w:type="page"/><w:t>体</w:t></w:r></w:p>'
    ))
    blocks = from_docx(str(broken)).blocks
    assert blocks[0]["runs"][0]["text"] == "粗" and blocks[0]["runs"][0]["bold"] is True
    assert blocks[1]["type"] == "pagebreak"
    later = blocks[2]["runs"][0]
    assert later["text"] == "体" and later["bold"] is True and later["eastAsia"] == "楷体" and later["size_pt"] == 16

    link = tmp / "cell-link.docx"
    pack_docx(link, (
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>见</w:t></w:r>"
        '<w:hyperlink r:id="rId2"><w:r><w:t>链接</w:t></w:r></w:hyperlink>'
        "</w:p></w:tc></w:tr></w:tbl>"
    ))
    assert text_of(from_docx(str(link))) == ["见链接"]

    merged = tmp / "rect.docx"
    pack_docx(merged, (
        "<w:tbl><w:tr>"
        '<w:tc><w:tcPr><w:gridSpan w:val="2"/><w:vMerge w:val="restart"/></w:tcPr><w:p><w:r><w:t>合</w:t></w:r></w:p></w:tc>'
        "<w:tc><w:p><w:r><w:t>右</w:t></w:r></w:p></w:tc>"
        "</w:tr><w:tr>"
        '<w:tc><w:tcPr><w:gridSpan w:val="2"/><w:vMerge/></w:tcPr><w:p><w:r><w:t></w:t></w:r></w:p></w:tc>'
        "<w:tc><w:p><w:r><w:t>下</w:t></w:r></w:p></w:tc>"
        "</w:tr></w:tbl>"
    ))
    once = from_docx(str(merged))
    assert once.blocks[0]["merges"][0]["colspan"] == 2 and once.blocks[0]["merges"][0]["rowspan"] == 2
    first = tmp / "rect-out.docx"
    to_docx(once, str(first))
    twice = from_docx(str(first))
    assert "下" in text_of(twice)
    second = tmp / "rect-out-2.docx"
    to_docx(twice, str(second))
    assert "下" in text_of(from_docx(str(second)))

    rich = tmp / "rich.xlsx"
    write_rich_xlsx(rich)
    cell = convert.convert_path(str(rich)).blocks[1]["rows"][0][0]["runs"]
    assert cell[0]["text"] == "甲" and cell[0].get("bold") is True
    assert cell[1]["text"] == "乙" and "bold" not in cell[1]
    joined = tmp / "join.xlsx"
    write_merged_xlsx(joined)
    table = convert.convert_path(str(joined)).blocks[1]
    assert table["merges"] == [{"row": 0, "col": 0, "rowspan": 1, "colspan": 2}]

    image = tmp / "pixel.png"
    image.write_bytes(PNG)
    md = tmp / "edge.md"
    md.write_text(
        "## 标题 ##\n\n # 另一题\n\n![点](pixel.png \"标题\")\n\n| 甲 \\| 乙 | 丙 |\n| --- | --- |\n| 1 | 2 |\n",
        encoding="utf-8",
    )
    doc = convert.convert_path(str(md))
    assert [block["type"] for block in doc.blocks] == ["heading", "heading", "image", "table"]
    assert doc.blocks[0]["runs"][0]["text"] == "标题"
    assert doc.blocks[1]["level"] == 1 and doc.blocks[1]["runs"][0]["text"] == "另一题"
    assert doc.blocks[2]["asset"] == "pixel.png"
    assert doc.blocks[3]["rows"][0][0]["runs"][0]["text"] == "甲 | 乙"
    assert doc.blocks[3]["rows"][0][1]["runs"][0]["text"] == "丙"


def write_rich_xlsx(path):
    sheet = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
  <row r="1"><c r="A1" t="inlineStr"><is><r><rPr><b/></rPr><t>甲</t></r><r><t>乙</t></r></is></c></row>
</sheetData></worksheet>"""
    _book(path, sheet)


def write_merged_xlsx(path):
    sheet = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
  <row r="1"><c r="A1" t="inlineStr"><is><t>合</t></is></c><c r="B1" t="inlineStr"><is><t></t></is></c></row>
</sheetData><mergeCells count="1"><mergeCell ref="A1:B1"/></mergeCells></worksheet>"""
    _book(path, sheet)


def _book(path, sheet):
    workbook = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="表" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook.encode("utf-8"))
        archive.writestr("xl/_rels/workbook.xml.rels", rels.encode("utf-8"))
        archive.writestr("xl/worksheets/sheet1.xml", sheet.encode("utf-8"))


def test_qt_switch():
    try:
        import qt_compat
    except ImportError:
        return

    class Legacy(object):
        FailedToStart = 0

    class Modern(object):
        class ProcessError:
            FailedToStart = 1

    assert qt_compat.failed_to_start(Legacy) == 0
    assert qt_compat.failed_to_start(Modern) == 1

    class BareHints(object):
        pass

    class BareApp(object):
        def styleHints(self):
            return BareHints()

    qt_compat.set_color_scheme(BareApp(), True)


def test_contract(tmp):
    styles = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:styles xmlns:w="%s"><w:style w:styleId="Heading1"><w:name w:val="heading 1"/>'
        '<w:rPr><w:b/><w:rFonts w:eastAsia="黑体" w:ascii="Times New Roman" w:hAnsi="Calibri"/>'
        '<w:sz w:val="32"/></w:rPr></w:style></w:styles>'
    ) % W
    body = (
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/><w:jc w:val="center"/>'
        '<w:spacing w:line="560" w:lineRule="exact"/>'
        '<w:ind w:firstLineChars="200"/></w:pPr>'
        '<w:r><w:rPr><w:b/><w:i/><w:u w:val="single"/><w:color w:val="FF0000"/>'
        '<w:rFonts w:eastAsia="仿宋_GB2312" w:ascii="Times New Roman" w:hAnsi="Calibri"/>'
        '<w:sz w:val="21"/></w:rPr><w:t>标题甲</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:jc w:val="both"/><w:spacing w:line="360" w:lineRule="auto"/></w:pPr>'
        '<w:r><w:rPr><w:i/><w:rFonts w:eastAsia="楷体" w:ascii="Times New Roman" w:hAnsi="Calibri"/>'
        '<w:sz w:val="24"/></w:rPr><w:t>正文乙</w:t></w:r></w:p>'
    )
    source = tmp / "contract.docx"
    pack_docx(source, body, styles)
    doc = convert.convert_path(str(source), "preserve")
    run = doc.blocks[0]["runs"][0]
    assert run["eastAsia"] == "仿宋_GB2312" and run["ascii"] == "Times New Roman"
    assert run["hAnsi"] == "Calibri" and run["size_pt"] == 10.5
    assert "font" not in run and "size" not in run
    assert doc.blocks[0]["align"] == "center"
    assert doc.blocks[0]["line"] == {"rule": "exact", "pt": 28}
    assert doc.blocks[0]["indent"]["first_chars"] == 2
    assert doc.blocks[1]["align"] == "both"
    assert doc.blocks[1]["line"] == {"rule": "auto", "multiple": 1.5}
    assert doc.styles["heading 1"]["eastAsia"] == "黑体"
    assert doc.styles["heading 1"]["hAnsi"] == "Calibri"
    assert doc.styles["heading 1"]["size_pt"] == 16
    covered = WenjuDoc(blocks=[{
        "type": "table",
        "rows": [
            [{"runs": [{"text": "合", "eastAsia": "仿宋_GB2312", "size_pt": 10.5}]}, {"runs": [{"text": "右"}]}],
            [{"covered": True}, {"runs": [{"text": "下"}]}],
        ],
        "merges": [{"row": 0, "col": 0, "rowspan": 2, "colspan": 1}],
    }], styles={}, assets={})
    assert validate(covered) == []
    save(covered, str(tmp / "covered.wenju"))
    shaped = WenjuDoc(blocks=[
        {"type": "heading", "level": 1, "align": "居中",
         "line": {"rule": "exact", "pt": 28},
         "indent": {"first_chars": 2},
         "runs": [{"text": "标题甲", "eastAsia": "仿宋_GB2312", "ascii": "Times New Roman",
                   "hAnsi": "Calibri", "size_pt": 10.5}]},
        {"type": "paragraph", "align": "两端对齐", "runs": [{"text": "散"}]},
        {"type": "paragraph", "align": "分散对齐", "runs": [{"text": "开"}]},
    ], styles={}, assets={})
    out = tmp / "shaped.docx"
    to_docx(shaped, str(out))
    root = ET.fromstring(zipfile.ZipFile(out).read("word/document.xml"))
    fonts = root.find(".//{%s}rFonts" % W)
    assert fonts.attrib["{%s}eastAsia" % W] == "仿宋_GB2312"
    assert fonts.attrib["{%s}ascii" % W] == "Times New Roman"
    assert fonts.attrib["{%s}hAnsi" % W] == "Calibri"
    assert [node.attrib.get("{%s}val" % W) for node in root.iter("{%s}jc" % W)] == ["center", "both", "distribute"]
    rules = dict(TEMPLATE)
    rules["字体"] = dict(TEMPLATE["字体"], 西文="Times New Roman")
    brushed = convert.convert_path(str(source), "template", rules)
    kept = brushed.blocks[1]["runs"][0]
    assert kept["eastAsia"] == "仿宋_GB2312" and kept["ascii"] == "Times New Roman"
    assert kept["hAnsi"] == "Calibri" and kept["italic"] is True
    wenju = tmp / "as-template.wenju"
    save(doc, str(wenju))
    to_docx(shaped, str(tmp / "from-wenju.docx"), str(wenju))


def write_titled_docx(path, title, payload, asset="pixel.png"):
    document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:rPr><w:rFonts w:eastAsia="仿宋_GB2312"/><w:sz w:val="32"/></w:rPr><w:t>%s</w:t></w:r></w:p>
    <w:p><w:r><w:rPr><w:rFonts w:eastAsia="楷体" w:ascii="Times New Roman" w:hAnsi="Calibri"/><w:sz w:val="21"/></w:rPr><w:t>正文</w:t></w:r></w:p>
    <w:p><w:r><w:drawing><wp:inline><wp:extent cx="914400" cy="914400"/>
      <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:blipFill><a:blip r:embed="rId5"/></pic:blipFill></pic:pic></a:graphicData></a:graphic>
    </wp:inline></w:drawing></w:r></w:p>
    <w:sectPr><w:headerReference w:type="default" r:id="rId8"/><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>
  </w:body>
</w:document>""" % title
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/%s"/>
  <Relationship Id="rId8" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
</Relationships>""" % asset
    header = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>%s</w:t></w:r></w:p></w:hdr>""" % title
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document.encode("utf-8"))
        archive.writestr("word/_rels/document.xml.rels", rels.encode("utf-8"))
        archive.writestr("word/media/" + asset, payload)
        archive.writestr("word/header1.xml", header.encode("utf-8"))


def write_image_xlsx(path):
    workbook = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="参数" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""
    book_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""
    sheet = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheetData>
    <row r="1"><c r="A1" t="inlineStr"><is><t>合</t></is></c><c r="B1" t="inlineStr"><is><t></t></is></c></row>
  </sheetData>
  <mergeCells count="1"><mergeCell ref="A1:B1"/></mergeCells>
  <drawing r:id="rId1"/>
</worksheet>"""
    sheet_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing1.xml"/>
</Relationships>"""
    drawing = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <xdr:oneCellAnchor>
    <xdr:from><xdr:col>0</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>0</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>
    <xdr:ext cx="914400" cy="457200"/>
    <xdr:pic><xdr:blipFill><a:blip r:embed="rId1"/></xdr:blipFill></xdr:pic>
  </xdr:oneCellAnchor>
</xdr:wsDr>"""
    drawing_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/pixel.png"/>
</Relationships>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook.encode("utf-8"))
        archive.writestr("xl/_rels/workbook.xml.rels", book_rels.encode("utf-8"))
        archive.writestr("xl/worksheets/sheet1.xml", sheet.encode("utf-8"))
        archive.writestr("xl/worksheets/_rels/sheet1.xml.rels", sheet_rels.encode("utf-8"))
        archive.writestr("xl/drawings/drawing1.xml", drawing.encode("utf-8"))
        archive.writestr("xl/drawings/_rels/drawing1.xml.rels", drawing_rels.encode("utf-8"))
        archive.writestr("xl/media/pixel.png", PNG)


def test_xlsx_image_and_merge(tmp):
    path = tmp / "sheet.xlsx"
    write_image_xlsx(path)
    doc = convert.convert_path(str(path), "preserve")
    table = next(block for block in doc.blocks if block["type"] == "table")
    assert table["merges"] == [{"row": 0, "col": 0, "rowspan": 1, "colspan": 2}]
    assert table["rows"][0][1]["covered"] is True
    image = next(block for block in doc.blocks if block["type"] == "image")
    assert image["w"] == 72 and image["h"] == 36
    assert doc.assets[image["asset"]] == PNG
    saved = tmp / "sheet.wenju"
    save(doc, str(saved))
    exported = tmp / "sheet.docx"
    to_docx(load(str(saved)), str(exported))
    restored = from_docx(str(exported))
    images = [block for block in restored.blocks if block["type"] == "image"]
    assert len(images) == 1 and images[0]["w"] == 72 and images[0]["h"] == 36
    assert restored.assets[images[0]["asset"]] == PNG


def test_batch_merge_and_single_export(tmp):
    first = tmp / "乙.docx"
    second = tmp / "甲.docx"
    write_titled_docx(first, "附则", PNG, "one.png")
    write_titled_docx(second, "总则", PNG + b"B", "two.png")
    seen = []
    snap = convert.run_batch(
        [{"name": "乙.docx", "path": str(first)}, {"name": "甲.docx", "path": str(second)}],
        tmp / "batch",
        mode="template",
        template=TEMPLATE,
        on_progress=seen.append,
    )
    assert snap["finished"] is True and snap["overall"] == 100
    assert [item["state"] for item in snap["files"]] == ["成功", "成功"]
    assert any(item["overall"] < 100 and item["finished"] is False for item in seen)
    assert [item["overall"] for item in seen] == sorted(item["overall"] for item in seen)
    message = convert.summary(snap, "转换完成")
    assert message.startswith("转换完成") and "成功 2 个" in message
    loaded = [load(item["output"]) for item in snap["files"]]
    assert ["".join(block["runs"][0]["text"] for block in doc.blocks if block["type"] == "heading") for doc in loaded] == ["附则", "总则"]
    for doc in loaded:
        image = next(block for block in doc.blocks if block["type"] == "image")
        assert doc.assets[image["asset"]] in (PNG, PNG + b"B")
        assert image["w"] == 72 and image["h"] == 72
        body = next(block for block in doc.blocks if block["type"] == "paragraph")
        assert body["runs"][0]["eastAsia"] == "仿宋_GB2312"
        assert body["runs"][0]["size_pt"] == 16
    import compose
    progress = []
    merged = compose.merge_export(
        [item["output"] for item in snap["files"]],
        str(tmp / "合稿.wenju"),
        str(tmp / "合稿.docx"),
        template={"font": "仿宋_GB2312", "number": "多级数字"},
        progress=lambda percents, overall: progress.append((list(percents), overall)),
    )
    assert progress[-1] == ([100, 100], 100)
    with zipfile.ZipFile(merged["docx"]) as archive:
        package = {name: archive.read(name) for name in archive.namelist()}
    blob = b"\n".join(package.values())
    assert PNG in package.values() and PNG + b"B" in package.values()
    assert "仿宋_GB2312".encode("utf-8") in blob
    assert b"PAGE" in blob and b"TOC" in blob
    texts = docx_texts(merged["docx"])
    assert texts.find("1. 附则") < texts.find("2. 总则")
    single = convert.run_export(
        [{"name": "乙.docx", "path": snap["files"][0]["output"]}],
        tmp / "single",
    )
    assert single["finished"] is True and single["files"][0]["state"] == "成功"
    single_doc = from_docx(single["files"][0]["docx"])
    assert any(block["type"] == "image" and single_doc.assets[block["asset"]] == PNG for block in single_doc.blocks)
    assert any(run.get("eastAsia") == "仿宋_GB2312" for block in single_doc.blocks if block["type"] == "paragraph" for run in block["runs"])


def test_keep_fangsong_name(tmp):
    import fontfallback
    fontfallback.reset_index()
    saved = fontfallback._INDEX
    try:
        assert fontfallback.chain_for("仿宋_GB2312")[:3] == ["仿宋_GB2312", "FangSong_GB2312", "仿宋"]
        fontfallback._INDEX = {"fangsong_gb2312": "FangSong_GB2312"}
        chosen, found = fontfallback.choose("仿宋_GB2312")
        assert found and chosen == "FangSong_GB2312"
        fontfallback._INDEX = {"仿宋": "仿宋", "fangsong": "仿宋"}
        chosen, found = fontfallback.choose("仿宋_GB2312")
        assert found and chosen == "仿宋"
        doc = WenjuDoc(blocks=[{
            "type": "paragraph",
            "runs": [{"text": "正文", "eastAsia": "仿宋_GB2312", "ascii": "Times New Roman", "size_pt": 16}],
        }], styles={}, assets={})
        path = tmp / "fangsong.docx"
        to_docx(doc, str(path), TEMPLATE)
        root = ET.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
        east = [node.attrib.get("{%s}eastAsia" % W) for node in root.iter("{%s}rFonts" % W)]
        assert east == ["仿宋_GB2312"]
    finally:
        fontfallback._INDEX = saved
        fontfallback.reset_index()


def _png_pixels(width, height):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _extent_docx(path, payload, name, cx, cy, cell_twip=None):
    if cell_twip:
        document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
  <w:body>
    <w:tbl>
      <w:tblGrid><w:gridCol w:w="%d"/></w:tblGrid>
      <w:tr><w:tc><w:tcPr><w:tcW w:w="%d" w:type="dxa"/></w:tcPr>
        <w:p><w:r><w:drawing><wp:inline><wp:extent cx="%d" cy="%d"/>
          <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
            <pic:pic><pic:blipFill><a:blip r:embed="rId5"/></pic:blipFill></pic:pic>
          </a:graphicData></a:graphic>
        </wp:inline></w:drawing></w:r></w:p>
      </w:tc></w:tr>
    </w:tbl>
  </w:body>
</w:document>""" % (cell_twip, cell_twip, cx, cy)
    elif cx:
        document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
  <w:body>
    <w:p><w:r><w:drawing><wp:inline><wp:extent cx="%d" cy="%d"/>
      <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
        <pic:pic><pic:blipFill><a:blip r:embed="rId5"/></pic:blipFill></pic:pic>
      </a:graphicData></a:graphic>
    </wp:inline></w:drawing></w:r></w:p>
  </w:body>
</w:document>""" % (cx, cy)
    else:
        document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
  <w:body>
    <w:p><w:r><w:drawing><wp:inline>
      <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
        <pic:pic><pic:blipFill><a:blip r:embed="rId5"/></pic:blipFill></pic:pic>
      </a:graphicData></a:graphic>
    </wp:inline></w:drawing></w:r></w:p>
  </w:body>
</w:document>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/%s"/>
</Relationships>""" % name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document.encode("utf-8"))
        archive.writestr("word/_rels/document.xml.rels", rels.encode("utf-8"))
        archive.writestr("word/media/" + name, payload)


def _docx_extent(path):
    xml = zipfile.ZipFile(path).read("word/document.xml")
    root = ET.fromstring(xml)
    extent = root.find(".//{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}extent")
    return int(extent.get("cx")), int(extent.get("cy"))


def test_image_keeps_native_size(tmp):
    import image_size
    payload = _png_pixels(32, 16)
    source = tmp / "small.docx"
    _extent_docx(source, payload, "small.png", 24 * 12700, 12 * 12700)
    doc = from_docx(str(source))
    image = next(block for block in doc.blocks if block["type"] == "image")
    assert (image["w"], image["h"]) == (24, 12)
    saved = tmp / "small.wenju"
    save(doc, str(saved))
    loaded = load(str(saved))
    kept = next(block for block in loaded.blocks if block["type"] == "image")
    assert (kept["w"], kept["h"]) == (24, 12)
    exported = tmp / "small-out.docx"
    to_docx(loaded, str(exported))
    assert _docx_extent(exported) == (24 * 12700, 12 * 12700)
    again = from_docx(str(exported))
    back = next(block for block in again.blocks if block["type"] == "image")
    assert (back["w"], back["h"]) == (24, 12)
    wide = _png_pixels(800, 200)
    wide_path = tmp / "wide.docx"
    _extent_docx(wide_path, wide, "wide.png", 800 * 12700, 200 * 12700)
    fitted = from_docx(str(wide_path))
    fitted_image = next(block for block in fitted.blocks if block["type"] == "image")
    limit = image_size.content_width_pt()
    assert fitted_image["w"] == image_size.num(limit)
    assert fitted_image["h"] == image_size.num(200 * limit / 800)
    bare = tmp / "pixels.docx"
    _extent_docx(bare, payload, "pixels.png", 0, 0)
    pixels = from_docx(str(bare))
    pixel_image = next(block for block in pixels.blocks if block["type"] == "image")
    assert (pixel_image["w"], pixel_image["h"]) == (24, 12)
    cell = tmp / "cell.docx"
    _extent_docx(cell, wide, "cell.png", 800 * 12700, 200 * 12700, cell_twip=2400)
    cell_doc = from_docx(str(cell))
    cell_table = next(block for block in cell_doc.blocks if block["type"] == "table")
    cell_image = cell_table["rows"][0][0]["images"][0]
    assert cell_image["w"] == 120
    assert cell_image["h"] == 30


def test_output_locations(tmp):
    folder = tmp / "inbox"
    folder.mkdir()
    source = folder / "报告.txt"
    source.write_text("甲\n", encoding="utf-8")
    (folder / "报告.wenju").write_text("occupied", encoding="utf-8")
    snap = convert.run_batch([{"name": "报告.txt", "path": str(source)}], None)
    placed = Path(snap["files"][0]["output"])
    assert placed == folder / "报告 (1).wenju"
    assert snap["files"][0]["target"] == str(placed)
    again = convert.run_batch([{"name": "报告.txt", "path": str(source)}], None)
    assert Path(again["files"][0]["output"]) == folder / "报告 (2).wenju"
    exported = convert.run_export([{"name": "报告.wenju", "path": str(placed)}], None)
    assert Path(exported["files"][0]["docx"]) == folder / "报告 (1).docx"
    home = tmp / "home"
    (home / "文档").mkdir(parents=True)
    (home / "Documents").mkdir()
    when = datetime.datetime(2026, 11, 13, 6, 38)
    pasted = convert.run_batch([{"name": "粘贴的内容", "text": "剪贴板正文"}], None, when=when, home=home)
    clip = Path(pasted["files"][0]["output"])
    assert clip == home / "文档" / "文矩输出" / "剪贴板-20261113-0638.wenju"
    pasted_again = convert.run_batch([{"name": "粘贴的内容", "text": "再一份"}], None, when=when, home=home)
    assert Path(pasted_again["files"][0]["output"]).name == "剪贴板-20261113-0638 (1).wenju"
    english = tmp / "english"
    (english / "Documents").mkdir(parents=True)
    assert convert.clipboard_dir(english) == english / "Documents" / "文矩输出"
    chosen = tmp / "chosen"
    forced = convert.run_batch(
        [{"name": "报告.txt", "path": str(source), "outdir": str(chosen)}],
        None,
    )
    assert Path(forced["files"][0]["output"]).parent == chosen
    assert "报告" in Path(forced["files"][0]["output"]).name
    for part in placed.parts:
        assert len(part) != 10 or not all(char in "0123456789abcdef" for char in part)
    wenju, docx = convert.merge_targets(source)
    assert wenju.parent == folder and wenju.name == "合稿.wenju"
    assert docx.parent == folder and docx.name == "合稿.docx"


def main():
    with tempfile.TemporaryDirectory(prefix="wenju-convert-") as directory:
        tmp = Path(directory)
        test_docx_roundtrip(tmp)
        test_template_brush(tmp)
        test_txt_md_paste(tmp)
        test_xlsx(tmp)
        test_doc_messages(tmp)
        test_validate_and_batch(tmp)
        test_vertical_merge(tmp)
        test_kept_content(tmp)
        test_edges(tmp)
        test_contract(tmp)
        test_keep_fangsong_name(tmp)
        test_xlsx_image_and_merge(tmp)
        test_batch_merge_and_single_export(tmp)
        test_image_keeps_native_size(tmp)
        test_output_locations(tmp)
    test_qt_switch()
    print("PASS: docx, xlsx, txt, md, paste, doc, wenju export, template brush, batch progress, qt switch")


if __name__ == "__main__":
    main()
