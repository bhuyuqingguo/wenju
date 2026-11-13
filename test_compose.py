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
        run["font"] = font
    return {"type": "heading", "level": level, "runs": [run]}


def paragraph(text, font=None):
    run = {"text": text}
    if font:
        run["font"] = font
    return {"type": "paragraph", "style": "Normal", "runs": [run]}


def document(blocks, header, assets=None):
    return WenjuDoc(blocks, {"sections": [{"at": 0, "header": header, "footer": ""}]}, assets or {}, {"wenju": 1})


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
            [{"runs": [{"text": "左"}]}, {"runs": [{"text": "右"}]}],
            [{"runs": [{"text": "下"}]}, {"runs": [{"text": ""}]}],
        ], "merges": [{"row": 0, "col": 0, "rows": 1, "cols": 2}]},
        {"type": "image", "asset": "assets/a.png", "w": 20, "h": 20},
    ], "乙", {"assets/a.png": picture_b})
    third = document([
        heading(1, "二、附图"),
        {"type": "image", "asset": "assets/a.png", "w": 20, "h": 20},
    ], "丙", {"assets/a.png": picture_c})

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
        assert [section["header"] for section in merged.styles["sections"]] == ["甲", "乙", "丙"]

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

        stored = load(exported["wenju"])
        stored_headings = [block for block in stored.blocks if block["type"] == "heading"]
        assert ["".join(run["text"] for run in block["runs"]) for block in stored_headings] == ["1. 总则", "1.1 范围", "2. 附则", "3. 附图"]
        assert [block["level"] for block in stored_headings] == [1, 2, 1, 1]

        with zipfile.ZipFile(exported["docx"]) as archive:
            assert archive.testzip() is None
            package = {name: archive.read(name) for name in archive.namelist()}
        blob = b"\n".join(package.values())
        assert b"TOC \\o \"1-3\"" in blob
        assert b"updateFields" in blob
        assert b"\xe4\xbb\xbf\xe5\xae\x8b_GB2312" not in blob
        assert "仿宋".encode("utf-8") in blob
        entries = toc_entries(package)
        assert [(sid, texts[0], texts[-1]) for sid, texts in entries] == [
            ("TOC1", "1. 总则", "2"),
            ("TOC2", "1.1 范围", "2"),
            ("TOC1", "2. 附则", "3"),
            ("TOC1", "3. 附图", "4"),
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
        assert [section["header"] for section in reread.styles["sections"]] == ["甲", "乙", "丙"]

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
    assert [section["header"] for section in combined.styles["sections"]] == ["页眉%d" % n for n in range(12)]

    broken = WenjuDoc([{"type": "heading", "level": 0, "runs": [{"text": "x"}]}], {}, {}, {"wenju": 1})
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
