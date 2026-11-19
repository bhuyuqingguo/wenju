"""Translate Markdown-specific block and run metadata into Word structures."""
import re
import xml.etree.ElementTree as ET


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
STYLES = {
    "code": "WenjuMarkdownCode",
    "list": "WenjuMarkdownList",
    "quote": "WenjuMarkdownQuote",
    "image_notice": "WenjuMarkdownImageNotice",
}
INLINE_CODE = "WenjuMarkdownInlineCode"
MONOSPACE = "Consolas"


def q(name):
    return "{%s}%s" % (W, name)


def node(parent, name, **attributes):
    return ET.SubElement(parent, q(name), {q(key): str(value) for key, value in attributes.items()})


class Layout:
    def __init__(self):
        self.lists = {}
        self.paragraph_styles = set()
        self.inline_code = False

    def paragraph(self, props, block):
        kind = block.get("markdown_kind")
        if kind not in STYLES:
            return
        style = STYLES[kind]
        self.paragraph_styles.add(style)
        old = props.find(q("pStyle"))
        if old is not None:
            props.remove(old)
        entry = ET.Element(q("pStyle"), {q("val"): style})
        props.insert(0, entry)
        if kind == "list":
            info = block.get("markdown_list", {})
            values = (info.get("id"), info.get("level"), info.get("start"), info.get("ordered"))
            group, level, start, ordered = values
            if not all(isinstance(value, int) for value in (group, level, start)) or not (0 <= level <= 8 and 0 <= start <= 999999999):
                return
            num_id = self.lists.setdefault((group, level, start, ordered is True), len(self.lists) + 1)
            num = ET.Element(q("numPr"))
            node(num, "ilvl", val=level)
            node(num, "numId", val=num_id)
            props.insert(1, num)
        elif kind == "quote":
            depth = block.get("markdown_depth", 1)
            depth = min(8, max(1, depth)) if isinstance(depth, int) else 1
            indent = props.find(q("ind"))
            if indent is not None:
                props.remove(indent)
            # Insert indentation after spacing and before alignment.
            alignment = props.find(q("jc"))
            props.insert(list(props).index(alignment) if alignment is not None else len(props),
                         ET.Element(q("ind"), {q("left"): str(360 * depth), q("firstLine"): "0"}))

    def styles(self, root):
        for style in sorted(self.paragraph_styles):
            item = node(root, "style", type="paragraph", styleId=style)
            node(item, "name", val=style)
            node(item, "basedOn", val="Normal")
            if style in (STYLES["code"], STYLES["quote"], STYLES["list"]):
                props = node(item, "pPr")
                if style == STYLES["code"]:
                    node(props, "spacing", lineRule="auto", line=240)
                    node(props, "ind", left=240, firstLine=0)
                    node(props, "jc", val="left")
                else:
                    node(props, "ind", firstLine=0)
        if self.inline_code:
            style = node(root, "style", type="character", styleId=INLINE_CODE)
            node(style, "name", val=INLINE_CODE)
            node(node(style, "rPr"), "rFonts", ascii=MONOSPACE, hAnsi=MONOSPACE)

    def numbering(self):
        root = ET.Element(q("numbering"))
        for (_, level, start, ordered), key in self.lists.items():
            abstract = node(root, "abstractNum", abstractNumId=key)
            node(abstract, "multiLevelType", val="multilevel")
            # Each indentation branch gets a separate sequence; it still uses a real Word level.
            for index in range(level + 1):
                item = node(abstract, "lvl", ilvl=index)
                node(item, "start", val=start if index == level else 1)
                node(item, "numFmt", val="decimal" if ordered else "bullet")
                node(item, "lvlText", val="%%%d." % (index + 1) if ordered else "•")
                node(item, "lvlJc", val="left")
                props = node(item, "pPr")
                node(node(props, "tabs"), "tab", val="num", pos=720 + 360 * index)
                node(props, "ind", left=720 + 360 * index, hanging=360, firstLineChars=0)
        for key in self.lists.values():
            node(node(root, "num", numId=key), "abstractNumId", val=key)
        return root

    def link(self, paragraph, target, relationships, first_id):
        if not isinstance(target, str) or not re.match(r"^(https?://[^\s]+|mailto:[^\s@]+@\S+)$", target, re.I):
            return paragraph
        numbered = "rId%d" % (first_id + len(relationships))
        relationships.append((numbered, target, R + "/hyperlink"))
        return ET.SubElement(paragraph, q("hyperlink"), {"{%s}id" % R: numbered})
