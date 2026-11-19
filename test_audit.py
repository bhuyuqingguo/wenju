"""Formatting audit verifies effective properties without rewriting the input."""

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from preset_store import PresetStore

sys.path.insert(0, str(Path(__file__).resolve().parent / "core"))
import audit
import docx_fmt as D


def xml(tag, parent=None, **attributes):
    element = ET.Element(D.q(tag)) if parent is None else ET.SubElement(parent, D.q(tag))
    for key, value in attributes.items():
        element.set(D.q(key), str(value))
    return element


class AuditTests(unittest.TestCase):
    def make_document(self, path, rules, incorrect=False):
        styles = xml("styles")
        formatter = D.Formatter(rules)
        formatter.do_styles(styles)
        inherited = xml("style", styles, styleId="BodyDerived", type="paragraph")
        xml("basedOn", inherited, val=formatter.sid["Normal"])
        character = xml("style", styles, styleId="OneWord", type="character")
        xml("sz", xml("rPr", character), val=20)

        document = xml("document")
        body = xml("body", document)
        heading = xml("p", body)
        xml("pStyle", xml("pPr", heading), val=formatter.sid["Heading1"])
        xml("t", xml("r", heading)).text = "项目背景"
        p = xml("p", body)
        ppr = xml("pPr", p)
        xml("pStyle", ppr, val="BodyDerived")
        xml("t", xml("r", p)).text = "合规正文"
        override = xml("r", p)
        xml("t", override).text = "单个词"
        if incorrect:
            xml("rStyle", xml("rPr", override), val="OneWord")
            xml("spacing", ppr, line=240, lineRule="auto")
            xml("jc", ppr, val="right")
            xml("ind", ppr, firstLineChars=100)
            heading_run = heading.find(".//" + D.q("r"))
            xml("sz", xml("rPr", heading_run), val=22)
        section = xml("sectPr", body)
        formatter.do_sections(body)
        if incorrect:
            section.find(D.q("pgMar")).set(D.q("top"), str(D.cm2twip(2)))
        rel = "http://schemas.openxmlformats.org/package/2006/relationships"
        relationships = ET.Element(f"{{{rel}}}Relationships")
        ET.SubElement(relationships, f"{{{rel}}}Relationship", Id="rId1", Target="footer1.xml",
                      Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer")
        xml("footerReference", section, type="default").set(audit.RID, "rId1")
        footer = xml("ftr")
        footer_para = xml("p", footer)
        if incorrect:
            xml("t", xml("r", footer_para)).text = "1"
            xml("fldSimple", footer_para, instr="NUMPAGES")
        else:
            xml("fldChar", xml("r", footer_para), fldCharType="begin")
            xml("instrText", xml("r", footer_para)).text = " PA"
            xml("instrText", xml("r", footer_para)).text = "GE "
            xml("fldChar", xml("r", footer_para), fldCharType="end")

        with zipfile.ZipFile(path, "w") as archive:
            for name, content in (("document.xml", document), ("styles.xml", styles), ("footer1.xml", footer),
                                  ("_rels/document.xml.rels", relationships)):
                archive.writestr("word/" + name, ET.tostring(content, encoding="utf-8"))

    def test_reports_overrides_and_keeps_source_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            rules = PresetStore(root).rules
            rules["页码"]["起始位置"] = "全文"
            # Avoid depending on which fonts the test machine has installed.
            for key in ("正文", "一级标题"):
                rules["字体"][key] = "宋体"
            clean, changed = root / "符合.docx", root / "不符合.docx"
            self.make_document(clean, rules)
            self.make_document(changed, rules, incorrect=True)
            before = hashlib.sha256(changed.read_bytes()).digest()
            good = audit.audit(clean, rules)
            bad = audit.audit(changed, rules)
            self.assertGreater(good["checked"], 10)
            self.assertEqual(good["issues"], [])
            problems = {issue["field"]: issue for issue in bad["issues"]}
            self.assertEqual(set(problems), {"上边距", "一级标题字号", "正文对齐", "正文行距",
                                             "正文首行缩进", "正文字号", "自动页码字段"})
            self.assertIn("第 1 节", problems["上边距"]["location"])
            self.assertIn("单个词", problems["正文字号"]["location"])
            self.assertEqual(problems["正文字号"]["actual"], "10 磅")
            self.assertEqual(problems["自动页码字段"]["actual"], "未找到 PAGE 域")
            self.assertEqual(before, hashlib.sha256(changed.read_bytes()).digest())


if __name__ == "__main__":
    unittest.main()
