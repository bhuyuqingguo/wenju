"""Read-only comparison of DOCX layout and a normalized WenJu rule set."""

import copy
import posixpath
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from urllib.parse import unquote

import docx_fmt as D
from fontfallback import chain_for
from infer import Styles
from wenju_format import _read_theme, _theme_face


q, NS = D.q, D.NS
RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
ALIGN = {"left": "左对齐", "center": "居中", "right": "右对齐", "both": "两端对齐",
         "distribute": "分散对齐", "start": "起始端对齐", "end": "末端对齐"}
HEAD = re.compile(r"^(?:heading\s*|标题\s*|)([1-9])$", re.I)
CJK = re.compile(r"[\u2e80-\u9fff\uf900-\ufaff\uff01-\uff60\U00020000-\U000323af]")
BRACKETS = re.compile(r"[（(][^（）()]{1,80}[）)]")
PAGE = re.compile(r"^\s*PAGE(?:\s|\\|$)", re.I)


def _value(parent, tag, attr="val", default=None):
    node = parent.find(q(tag)) if parent is not None else None
    return default if node is None else node.get(q(attr), default)


def _number(value, default=None):
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _short(text, limit=32):
    return " ".join(text.split())[:limit]


def _font_key(value):
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _pt(value):
    return f"{value:g} 磅"


def _is_on(parent, tag):
    if parent is None:
        return False
    node = parent.find(q(tag))
    return node is not None and node.get(q("val"), "1") not in ("0", "false", "off")


def _merge_run(values, rpr, theme):
    if rpr is None:
        return
    fonts = rpr.find(q("rFonts"))
    if fonts is not None:
        for slot in ("eastAsia", "ascii", "hAnsi"):
            token = fonts.get(q(slot + "Theme"))
            name = _theme_face(theme, token) if token else fonts.get(q(slot))
            if token or name:
                values[slot] = name.split(";")[0].strip() if name else None
    size = _number(_value(rpr, "sz"))
    if size is not None:
        values["size"] = size / 2


def _merge_para(values, ppr):
    if ppr is None:
        return
    spacing = ppr.find(q("spacing"))
    if spacing is not None:
        for key in ("line", "lineRule", "before", "after", "beforeLines", "afterLines",
                    "beforeAutospacing", "afterAutospacing"):
            if q(key) in spacing.attrib:
                values[key] = spacing.get(q(key))
    ind = ppr.find(q("ind"))
    if ind is not None:
        for group in (("firstLine", "firstLineChars", "hanging", "hangingChars"),
                      ("left", "leftChars", "start", "startChars"),
                      ("right", "rightChars", "end", "endChars")):
            if any(q(key) in ind.attrib for key in group):
                for key in group:
                    values.pop(key, None)
                    if q(key) in ind.attrib:
                        values[key] = ind.get(q(key))
    for key in ("jc", "outlineLvl"):
        value = _value(ppr, key)
        if value is not None:
            values[key] = value


class Audit:
    def __init__(self, archive, rules):
        self.archive = archive
        self.rules = D.normalize_rules(copy.deepcopy(rules))
        self.body = self.read_xml("word/document.xml").find(q("body"))
        if self.body is None:
            raise ValueError("DOCX 缺少文档正文")
        styles_xml = self.read_xml("word/styles.xml", optional=True)
        self.styles = Styles(styles_xml if styles_xml is not None else ET.Element(q("styles")))
        names = archive.namelist()
        theme_files = {"word/theme/theme1.xml": archive.read("word/theme/theme1.xml")} if "word/theme/theme1.xml" in names else {}
        self.theme = _read_theme(theme_files)
        self.formatter = D.Formatter(self.rules)
        self.issues = []
        self.checked = 0
        self.review = dict.fromkeys([
            "实际分页、图题是否跨页、图形环绕、表格单元格和红头／版记位置需在 Word 或 WPS 复核。"
        ])

    def read_xml(self, name, optional=False):
        try:
            return ET.fromstring(self.archive.read(name))
        except KeyError:
            if not optional:
                raise ValueError(f"DOCX 缺少必要部件：{name}") from None
            return None

    def compare(self, location, field, expected, actual, matches):
        self.checked += 1
        if not matches:
            self.issues.append(dict(location=location, field=field, expected=expected, actual=actual))

    def near(self, location, field, expected, actual, unit, tolerance):
        display = lambda value: f"{value:g} {unit}" if value is not None else "未读取到"
        self.compare(location, field, display(expected), display(actual),
                     actual is not None and abs(actual - expected) <= tolerance)

    def run(self):
        nodes = list(self.body)
        sections = [(i, node.find("w:pPr/w:sectPr", NS))
                    for i, node in enumerate(nodes) if node.tag == q("p")]
        sections = [(i, section) for i, section in sections if section is not None]
        sections.append((len(nodes), self.body.find(q("sectPr"))))
        for number, (_, section) in enumerate(sections, 1):
            self.section(number, section)
        self.formatter.toc_range = self.formatter.find_toc(nodes)
        self.paragraphs(nodes, sections)
        self.page_numbers(nodes, sections)

    def section(self, number, section):
        location = f"第 {number} 节"
        if section is None:
            self.review[f"{location}没有明确的分节页面设置，页面尺寸和页边距需复核。"] = None
            return
        config = self.rules["页面"]
        dimensions = section.find(q("pgSz"))
        width = _number(dimensions.get(q("w"))) if dimensions is not None else None
        height = _number(dimensions.get(q("h"))) if dimensions is not None else None
        landscape = dimensions is not None and (
            dimensions.get(q("orient")) == "landscape"
            or (width is not None and height is not None and width > height))
        if config.get("纸张方向与分节") != "保留":
            a4 = width is not None and height is not None and abs(width - 11906) <= 4 and abs(height - 16838) <= 4
            paper = f"{width * 2.54 / 1440:.2f}×{height * 2.54 / 1440:.2f} cm" if width and height else "未读取到"
            self.compare(location, "纸张与方向", "A4 纵向", paper + ("（横向）" if landscape else ""), a4 and not landscape)
        elif landscape and config.get("横向页边距") == "不改":
            return
        swap = landscape and config.get("纸张方向与分节") == "保留" and config.get("横向页边距") == "互换"
        margins = section.find(q("pgMar"))
        for xml_key, label, expected_key in (
            ("top", "上边距", "左边距" if swap else "上边距"),
            ("bottom", "下边距", "右边距" if swap else "下边距"),
            ("left", "左边距", "上边距" if swap else "左边距"),
            ("right", "右边距", "下边距" if swap else "右边距"),
            ("header", "页眉距", "页眉距"), ("footer", "页脚距", "页脚距"),
        ):
            actual = _number(margins.get(q(xml_key))) if margins is not None else None
            if actual is None:
                self.review[f"{location}未明确写入{label}，请在 Word 或 WPS 复核。"] = None
                continue
            self.near(location, label, float(config[expected_key]), round(actual * 2.54 / 1440, 2), "cm", 0.011)

    def inherited(self, paragraph):
        run, props = {}, {}
        _merge_run(run, self.styles.def_rpr, self.theme)
        _merge_para(props, self.styles.def_ppr)
        sid = D.style_id(paragraph) or self.styles.default_p
        for style in self.styles.chain(sid):
            _merge_run(run, style["rPr"], self.theme)
            _merge_para(props, style["pPr"])
        ppr = paragraph.find(q("pPr"))
        _merge_para(props, ppr)
        return run, props, sid

    def paragraphs(self, nodes, sections):
        heading, front, section_index, paragraph_count = "", True, 0, 0
        fonts = self.rules["字体"]
        official = self.rules.get("公文", {})
        for i, node in enumerate(nodes):
            if i > sections[section_index][0]:
                section_index += 1
                heading = ""
            if node.tag != q("p"):
                if node.tag != q("sectPr"):
                    front = False
                continue
            paragraph_count += 1
            content = D.para_text(node).strip()
            if not content:
                continue
            run, props, sid = self.inherited(node)
            name = self.styles.by_id.get(sid, {}).get("name") or sid or ""
            if (id(node) in self.formatter.toc_ids or self.formatter.RE_TOC_TITLE.match(content)
                    or self.formatter.is_toc_para(node) or name.lower().startswith("toc")
                    or D.has_image(node) or sid in ("WenJuLetterhead", "CoverTitle", "CoverInfo", "SecurityMark")
                    or name.casefold() in ("caption", "题注", "封面标题", "封面落款", "文矩红头", "密级")
                    or self.formatter.RE_FIG.match(content) or self.formatter.RE_TAB.match(content)):
                continue
            if front and official.get("启用") and re.fullmatch(r"(?:秘密|机密|绝密)(?:[★☆·\s]*(?:\d+年|\d+个月|长期|永久))?", content):
                continue
            is_title = (name.casefold() in ("title", "标题", "公文题目", "officialtitle")
                        or sid in ("Title", "OfficialTitle"))
            heading_match = HEAD.fullmatch(name) or HEAD.fullmatch(sid or "")
            outline = _number(props.get("outlineLvl"))
            level = int(heading_match.group(1)) if heading_match else (
                int(outline) + 1 if outline is not None and 0 <= outline <= 8 else None)
            location = f"第 {section_index + 1} 节 · 第 {paragraph_count} 段「{_short(content)}」"
            if heading and not level:
                location += f"（{heading} 下）"
            body = False
            if official.get("启用") and (is_title or (
                    front and official.get("首个居中段作为题目", True)
                    and props.get("jc") == "center" and len(content) <= 100 and not level
                    and not self.formatter.label_level(content))):
                config = dict(D.PARA_DEFAULTS, 字号=official["题目字号"], 对齐="center",
                              行距类型="固定值", 行距值=official["题目行距"])
                font, role = official["题目字体"], "题目"
                if not is_title:
                    self.review[f"{location}按首个居中短段判定为题目，请确认。"] = None
            elif is_title:
                self.review[f"{location}为文档题目，当前模板未启用公文题目规则，请复核。"] = None
                front = False
                continue
            elif level:
                heading = f"「{_short(content)}」"
                if level > D.level_count(self.rules["标题"]):
                    self.review[f"{location}为 {level} 级标题，超出当前模板的标题级数。"] = None
                    front = False
                    continue
                key = D.LEVEL_KEYS[level - 1]
                role, config, font = key + "标题", self.rules["标题"][key], fonts[key + "标题"]
            elif (self.rules["标题"].get("识别") and len(content) < 60
                  and not content.endswith(("。", "；", "，", "：")) and self.formatter.label_level(content)):
                self.review[f"{location}只有编号文本，可能是标题或列表项，请核对段落样式。"] = None
                front = False
                continue
            else:
                role, config, font, body = "正文", self.rules["正文"], fonts["正文"], True
            front = False
            self.paragraph(location, role, config, props, run.get("size"))
            self.text_runs(location, role, config, font, node, run, body)

    def paragraph(self, location, role, config, props, paragraph_size):
        alignment = config.get("对齐") or "both"
        actual = props.get("jc") or "left"
        if actual not in ("start", "end"):
            self.compare(location, role + "对齐", ALIGN.get(alignment, alignment),
                         ALIGN.get(actual, actual), alignment == actual)
        else:
            self.review[f"{location}使用相对方向对齐，请结合文字方向复核。"] = None
        spacing_type = config["行距类型"]
        rule = {"固定值": "exact", "最小值": "atLeast"}.get(spacing_type, "auto")
        magnitude = float(config["行距值"]) if spacing_type != "单倍" else 1
        actual_rule = props.get("lineRule") or "auto"
        actual_line = _number(props.get("line"), 240) / (240 if actual_rule == "auto" else 20)
        def line_label(kind, value):
            return {"exact": "固定 " + _pt(value), "atLeast": "最小 " + _pt(value),
                    "auto": f"{value:g} 倍"}.get(kind, f"{value:g}（{kind}）")
        self.compare(location, role + "行距", line_label(rule, magnitude), line_label(actual_rule, actual_line),
                     rule == actual_rule and abs(actual_line - magnitude) <= (0.0042 if rule == "auto" else 0.026))
        for label, key in (("段前", "before"), ("段后", "after")):
            if props.get(key + "Autospacing") in ("1", "true", "on") or props.get(key + "Lines") is not None:
                self.review[f"{location}的{label}为自动或行单位间距，请复核。"] = None
            else:
                self.near(location, role + label, float(config[label]),
                          _number(props.get(key), 0) / 20, "磅", 0.026)
        size = paragraph_size or D.size_pt(config["字号"])
        def indent(chars, distance):
            char_value = _number(props.get(chars))
            if char_value is not None:
                return char_value / 100
            return _number(props.get(distance), 0) / 20 / size
        first = indent("firstLineChars", "firstLine")
        if "hanging" in props or "hangingChars" in props:
            first = -indent("hangingChars", "hanging")
        self.near(location, role + "首行缩进", float(config["首行缩进字符"]), round(first, 2), "字符", 0.06)

    def text_runs(self, location, role, config, font, paragraph, inherited, body):
        target_size = D.size_pt(config["字号"])
        fonts = self.rules["字体"]
        runs = [(r, "".join(t.text or "" for t in r.findall(q("t")))) for r in paragraph.iter(q("r"))]
        spans = [(m.start(), m.end()) for m in BRACKETS.finditer("".join(t for _, t in runs))] if body else []
        positions = iter(spans)
        span = next(positions, None)
        offset = 0
        checked = set()
        for run, content in runs:
            start, offset = offset, offset + len(content)
            if not content.strip():
                continue
            props = inherited.copy()
            rpr = run.find(q("rPr"))
            for style in self.styles.chain(_value(rpr, "rStyle")):
                _merge_run(props, style["rPr"], self.theme)
            _merge_run(props, rpr, self.theme)
            tag = location if len(runs) == 1 else location + f" · 文字片段「{_short(content, 16)}」"
            size = props.get("size")
            if size not in checked:
                checked.add(size)
                if size is None:
                    self.review[f"{tag}字号未明确写入，显示取决于阅读软件。"] = None
                else:
                    self.near(tag, role + "字号", target_size, size, "磅", 0.025)
            if fonts.get("模式", "模板") == "原文档":
                continue
            slots = set()
            for position, character in enumerate(content, start):
                while span and position >= span[1]:
                    span = next(positions, None)
                if CJK.match(character):
                    slots.add(("eastAsia", fonts["括号内"] if span and position >= span[0] else font))
                elif character.isascii() and character.isalnum():
                    slots.add(("ascii", fonts["西文"]))
                elif character.isalnum():
                    slots.add(("hAnsi", fonts["西文"]))
            for slot, expected in sorted(slots):
                value = props.get(slot)
                if (slot, expected, value) in checked:
                    continue
                checked.add((slot, expected, value))
                field = role + ("中文字体" if slot == "eastAsia" else "西文字体")
                if value is None:
                    self.review[f"{tag}{field}未明确写入，可能由主题或阅读软件决定。"] = None
                else:
                    exact = _font_key(expected) == _font_key(value)
                    alternative = slot == "eastAsia" and not exact and any(
                        _font_key(value) == _font_key(name) for name in chain_for(expected))
                    if alternative:
                        self.review[f"{tag}的{field}为「{value}」，是文矩可用的替代字体。模板指定「{expected}」，请确认是否接受。"] = None
                    else:
                        self.compare(tag, field, expected, value, exact)

    def page_numbers(self, nodes, sections):
        config = self.rules.get("页码", {})
        if not config.get("启用", True):
            return
        rel_root = self.read_xml("word/_rels/document.xml.rels", optional=True)
        rels = {r.get("Id"): r.get("Target") for r in (rel_root if rel_root is not None else ())
                if (r.get("Type") or "").endswith("/footer") and r.get("TargetMode") != "External"}
        settings = self.read_xml("word/settings.xml", optional=True)
        even = _is_on(settings, "evenAndOddHeaders")
        current = {}
        cache = {}
        mode = config.get("起始位置", "目录后")
        start = 0
        if mode == "目录后" and self.formatter.toc_range:
            start = self.formatter.toc_range[1] + 1
        elif mode != "全文" and len(sections) > 1:
            start = sections[0][0] + 1
        if mode != "全文":
            self.review[f"页码按「{mode}」规则检查正文各节的 PAGE 域，实际起始页和页码连续性需复核。"] = None
        while start < len(nodes) and nodes[start].tag == q("p") and not D.para_text(nodes[start]).strip():
            start += 1
        for i, (end, section) in enumerate(sections, 1):
            if section is not None:
                for r in section.findall(q("footerReference")):
                    current[r.get(q("type"), "default")] = rels.get(r.get(RID))
            if end < start:
                continue
            needed = {"default": "默认页脚"}
            if _is_on(section, "titlePg"):
                needed["first"] = "首页页脚"
            if even:
                needed["even"] = "偶数页页脚"
            for kind, label in needed.items():
                target = current.get(kind)
                if target not in cache:
                    name = ""
                    if target:
                        name = posixpath.normpath(unquote(
                            target.lstrip("/") if target.startswith("/") else "word/" + target))
                    footer = self.read_xml(name, optional=True) if name else None
                    cache[target] = footer is not None and self.has_page_field(footer)
                self.compare(f"第 {i} 节 · {label}", "自动页码字段", "包含 PAGE 域",
                             "包含 PAGE 域" if cache[target] else "未找到 PAGE 域", cache[target])

    @staticmethod
    def has_page_field(footer):
        for paragraph in footer.iter(q("p")):
            instructions = [f.get(q("instr"), "") for f in paragraph.iter(q("fldSimple"))]
            current = []
            for node in paragraph.iter():
                if node.tag == q("instrText"):
                    current.append(node.text or "")
                if node.tag == q("fldChar") and current:
                    instructions.append("".join(current))
                    current = []
            instructions.append("".join(current))
            if any(PAGE.match(text) for text in instructions):
                return True
        return False


def audit(path, rules):
    """Audit an existing DOCX without writing it or running the formatter."""
    path = Path(path)
    if path.suffix.lower() != ".docx":
        raise ValueError("格式校核首版支持 .docx，请先另存为 Word 文档。")
    with zipfile.ZipFile(path) as package:
        result = Audit(package, rules)
        result.run()
    lines = [f"文档：{path.name}", f"已检查 {result.checked} 项，发现 {len(result.issues)} 处问题。"]
    for issue in result.issues:
        lines.append(f"{issue['location']} · {issue['field']}\n  实际：{issue['actual']}    要求：{issue['expected']}")
    lines.extend(["", "需人工复核", *result.review])
    return dict(issues=result.issues, checked=result.checked, review=list(result.review), reportText="\n".join(lines))
