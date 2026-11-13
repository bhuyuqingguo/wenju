# -*- coding: utf-8 -*-
import base64
import json
import os
import sys
import tempfile
import zipfile
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
                    found.append("".join(run["text"] for run in cell["runs"]))
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
    assert run["text"] == "正文" and run["bold"] is True and run["font"] == "楷体" and run["size"] == 12
    assert doc.blocks[2]["rows"][0][0]["runs"][0]["text"] == "合"
    assert doc.blocks[2]["merges"] == [{"row": 0, "col": 0, "rowspan": 1, "colspan": 2}]
    assert doc.blocks[2]["rows"][1][1]["runs"][0]["text"] == "乙"
    assert doc.blocks[5]["w"] == 96 and doc.blocks[5]["h"] == 96
    assert doc.assets["pixel.png"] == PNG
    saved = tmp / "sample.wenju"
    save(doc, str(saved))
    with zipfile.ZipFile(saved) as archive:
        assert json.loads(archive.read("document.json"))[0]["type"] == "heading"
        assert "assets/pixel.png" in archive.namelist()
        assert "assets/" in archive.namelist()
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
    assert kept.blocks[1]["runs"][0]["font"] == "楷体"
    brushed = convert.convert_path(str(source), "template", TEMPLATE)
    heading = brushed.blocks[0]["runs"][0]
    body = brushed.blocks[1]["runs"][0]
    assert heading["font"] == "黑体" and heading["bold"] is True and heading["size"] == 16
    assert body["font"] == "仿宋_GB2312" and body["size"] == 16 and body["bold"] is True
    plain = convert.convert_text("一段正文", "template", TEMPLATE)
    assert plain.blocks[0]["runs"][0]["font"] == "仿宋_GB2312"
    assert "bold" not in plain.blocks[0]["runs"][0]
    cleared = dict(TEMPLATE)
    cleared["正文"] = dict(TEMPLATE["正文"], 保留加粗斜体下划线=False)
    stripped = convert.convert_path(str(source), "template", cleared)
    assert "bold" not in stripped.blocks[1]["runs"][0]
    exported = tmp / "brushed.docx"
    to_docx(kept, str(exported), TEMPLATE)
    xml = zipfile.ZipFile(exported).read("word/document.xml").decode("utf-8")
    assert "仿宋_GB2312" in xml
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
    assert table["rows"][0][0]["runs"][0]["font"] == "黑体"
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
    broken = WenjuDoc([{"type": "image", "asset": "missing.png", "w": 1, "h": 1}])
    errors = validate(broken)
    assert any("assets" in error for error in errors)
    bad_level = WenjuDoc([{"type": "heading", "level": 0, "runs": [{"text": "x"}]}])
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
    doc = WenjuDoc([{
        "type": "table",
        "rows": [
            [{"runs": [{"text": "竖"}]}, {"runs": [{"text": "右"}]}],
            [{"runs": [{"text": ""}]}, {"runs": [{"text": "下"}]}],
        ],
        "merges": [{"row": 0, "col": 0, "rowspan": 2, "colspan": 1}],
    }])
    path = tmp / "merge.docx"
    to_docx(doc, str(path))
    restored = from_docx(str(path))
    merge = restored.blocks[0]["merges"][0]
    assert merge["rowspan"] == 2 and merge["colspan"] == 1
    assert restored.blocks[0]["rows"][1][1]["runs"][0]["text"] == "下"


def test_qt_switch():
    import qt_compat

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
    test_qt_switch()
    print("PASS: docx, xlsx, txt, md, paste, doc, wenju export, template brush, batch progress, qt switch")


if __name__ == "__main__":
    main()
