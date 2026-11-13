"""Preview rows keep source font names and do not pretend missing pictures are drawn."""
import tempfile
import zipfile
from pathlib import Path

import preview_model

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
)


class Doc(object):
    def __init__(self, blocks, assets):
        self.blocks = blocks
        self.assets = assets


def display_font(name):
    if name == "仿宋_GB2312":
        return "仿宋"
    return name


def test_preview_keeps_font_and_marks_gaps():
    doc = Doc([
        {"type": "heading", "level": 1, "runs": [{"text": "通知标题", "eastAsia": "仿宋_GB2312", "size_pt": 22, "bold": True}]},
        {"type": "paragraph", "runs": [{"text": "正文第一段", "eastAsia": "仿宋_GB2312", "size_pt": 16}]},
        {"type": "table", "rows": [
            [{"runs": [{"text": "表头"}]}, {"covered": True}],
            [{"runs": [{"text": "左"}]}, {"runs": [{"text": "右"}]}],
        ], "merges": [{"row": 0, "col": 0, "rowspan": 1, "colspan": 2}]},
        {"type": "image", "asset": "shot.png", "w": 10, "h": 8},
        {"type": "image", "asset": "chart.emf", "w": 120, "h": 80},
        {"type": "toc"},
    ], {"shot.png": PNG, "chart.emf": b"\x01\x00\x00\x00not-a-bitmap"})
    with tempfile.TemporaryDirectory(prefix="wenju-preview-") as tmp:
        blocks, note = preview_model.present(doc, tmp, display_font, charts=2)
        assert doc.blocks[0]["runs"][0]["eastAsia"] == "仿宋_GB2312"
        heading = blocks[0]
        assert heading["kind"] == "heading" and heading["text"] == "通知标题"
        assert heading["runs"][0]["font"] == "仿宋_GB2312"
        assert "仿宋_GB2312" in note and "仿宋" in note and "不变" in note
        assert blocks[1]["kind"] == "paragraph" and "正文第一段" in blocks[1]["text"]
        table = next(block for block in blocks if block["kind"] == "table")
        assert "表头" in table["text"] and "横跨 2 列" in table["rows"][0][0]
        assert "（被合并）" in table["rows"][0][1]
        assert "不把格子画成跨行跨列" in table["note"]
        image = next(block for block in blocks if block["kind"] == "image")
        assert image["path"].startswith("file:")
        assert list(Path(tmp).glob("img*.png"))
        assert "不是纸面大小" in image["note"]
        holds = [block for block in blocks if block["kind"] == "placeholder"]
        assert any("图片占位" in block["title"] and "没有把它画出来" in block["note"] for block in holds)
        assert sum(1 for block in holds if block["title"] == "图表占位") == 2
        assert any("不能重绘图表" in block["note"] for block in holds)
        assert any(block["title"] == "目录" for block in holds)
    pasted = preview_model.paste_blocks("第一段\n\n第二段", display_font)
    assert [block["text"] for block in pasted] == ["第一段", "第二段"]
    assert preview_model.paste_blocks("  ", display_font) == []


def test_chart_count_reads_package_parts():
    with tempfile.TemporaryDirectory(prefix="wenju-chart-") as tmp:
        package = Path(tmp) / "book.xlsx"
        with zipfile.ZipFile(str(package), "w") as archive:
            archive.writestr("xl/charts/chart1.xml", "<c/>")
            archive.writestr("xl/worksheets/sheet1.xml", "<s/>")
        assert preview_model.chart_count(package) == 1
        assert preview_model.chart_count(Path(tmp) / "missing.docx") == 0
        blank = Path(tmp) / "note.txt"
        blank.write_text("x", encoding="utf-8")
        assert preview_model.chart_count(blank) == 0


if __name__ == "__main__":
    test_preview_keeps_font_and_marks_gaps()
    test_chart_count_reads_package_parts()
    print("PASS: preview keeps 仿宋_GB2312, shows table text, and placeholders for emf and charts")
