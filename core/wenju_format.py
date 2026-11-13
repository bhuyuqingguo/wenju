"""Minimal .wenju container. Same API the format line owns: WenjuDoc, load, save, from_docx, to_docx, validate."""
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

FORMAT = 'wenju'
VERSION = 1
BLOCK_TYPES = ('heading', 'paragraph', 'table', 'image', 'pagebreak', 'toc')
SIZES = {
    '初号': 42, '小初': 36, '一号': 26, '小一': 24, '二号': 22, '小二': 18,
    '三号': 16, '小三': 15, '四号': 14, '小四': 12, '五号': 10.5, '小五': 9,
    '六号': 7.5, '小六': 6.5, '七号': 5.5, '八号': 5,
}
_CN = ('', '一级', '二级', '三级', '四级', '五级', '六级', '七级', '八级', '九级')
_W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
_R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
_A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
_REL = '{http://schemas.openxmlformats.org/package/2006/relationships}'


class WenjuDoc(object):
    def __init__(self, blocks=None, styles=None, assets=None):
        self.blocks = list(blocks or [])
        self.styles = dict(styles or {})
        self.assets = dict(assets or {})


def pack_grid(cells):
    if not cells:
        return [], []
    max_r = max(pos[0] for pos in cells)
    max_c = max(pos[1] for pos in cells)
    rows = []
    merges = []
    for r in range(max_r + 1):
        row = []
        for c in range(max_c + 1):
            cell = cells.get((r, c)) or {'covered': True, 'runs': []}
            row.append(cell)
            if not cell.get('covered'):
                cs = int(cell.get('colspan') or 1)
                rs = int(cell.get('rowspan') or 1)
                if cs > 1 or rs > 1:
                    merges.append({'row': r, 'col': c, 'rowspan': rs, 'colspan': cs})
        rows.append(row)
    return rows, merges


def _pt(value, default=None):
    if value is None or value == '':
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace('磅', '').replace('pt', '')
    if text in SIZES:
        return float(SIZES[text])
    try:
        return float(text)
    except ValueError:
        return default


def _paint(runs, font, size, bold):
    painted = []
    for run in runs or []:
        item = {'text': run.get('text') or ''}
        if item['text'] == '\n':
            painted.append(item)
            continue
        if font:
            item['font'] = font
        if size:
            item['size'] = size
        if bold:
            item['bold'] = True
        painted.append(item)
    return painted


def brush(doc, rules):
    rules = rules or {}
    fonts = rules.get('字体') or {}
    body = rules.get('正文') or {}
    heads = rules.get('标题') or {}
    table = rules.get('表格') or {}
    blocks = []
    for block in doc.blocks:
        kind = block.get('type')
        if kind == 'heading':
            level = max(1, min(9, int(block.get('level') or 1)))
            key = _CN[level]
            cfg = heads.get(key) or {}
            blocks.append({
                'type': 'heading',
                'level': level,
                'runs': _paint(block.get('runs'), fonts.get(key + '标题') or fonts.get('正文'), _pt(cfg.get('字号')), bool(cfg.get('加粗'))),
            })
        elif kind == 'paragraph':
            blocks.append({
                'type': 'paragraph',
                'style': block.get('style') or 'body',
                'runs': _paint(block.get('runs'), fonts.get('正文'), _pt(body.get('字号')), bool(body.get('加粗'))),
            })
        elif kind == 'table':
            font = fonts.get('表格') or fonts.get('正文')
            size = _pt(table.get('字号'))
            bold = bool(table.get('加粗'))
            rows = []
            for row in block.get('rows') or []:
                cells = []
                for cell in row:
                    if cell.get('covered'):
                        cells.append({'covered': True, 'runs': []})
                        continue
                    item = {'runs': _paint(cell.get('runs'), font, size, bold)}
                    if int(cell.get('colspan') or 1) != 1:
                        item['colspan'] = int(cell['colspan'])
                    if int(cell.get('rowspan') or 1) != 1:
                        item['rowspan'] = int(cell['rowspan'])
                    cells.append(item)
                rows.append(cells)
            blocks.append({'type': 'table', 'rows': rows, 'merges': list(block.get('merges') or [])})
        else:
            blocks.append(json.loads(json.dumps(block)))
    styles = dict(doc.styles)
    styles['mode'] = 'template'
    return WenjuDoc(blocks, styles, doc.assets)


def save(doc, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {'format': FORMAT, 'version': VERSION, 'assets': sorted(doc.assets)}
    with zipfile.ZipFile(str(path), 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False))
        archive.writestr('document.json', json.dumps(doc.blocks, ensure_ascii=False))
        archive.writestr('styles.json', json.dumps(doc.styles, ensure_ascii=False))
        for name, data in doc.assets.items():
            arc = name if str(name).startswith('assets/') else 'assets/' + str(name)
            archive.writestr(arc, data)


def load(path):
    with zipfile.ZipFile(str(path)) as archive:
        blocks = json.loads(archive.read('document.json').decode('utf-8'))
        styles = json.loads(archive.read('styles.json').decode('utf-8'))
        assets = {}
        for info in archive.infolist():
            if info.filename.startswith('assets/') and not info.is_dir():
                assets[info.filename] = archive.read(info.filename)
    return WenjuDoc(blocks, styles, assets)


def validate(doc):
    errors = []
    if not isinstance(getattr(doc, 'blocks', None), list):
        return ['document.json 必须是块列表']
    for index, block in enumerate(doc.blocks):
        if not isinstance(block, dict) or block.get('type') not in BLOCK_TYPES:
            errors.append('第 %d 块类型无法识别' % (index + 1))
            continue
        kind = block['type']
        if kind == 'heading':
            level = block.get('level')
            if not isinstance(level, int) or not 1 <= level <= 9:
                errors.append('第 %d 块标题级别必须是 1 到 9' % (index + 1))
            if not isinstance(block.get('runs'), list):
                errors.append('第 %d 块缺少 runs' % (index + 1))
        elif kind == 'paragraph':
            if not isinstance(block.get('runs'), list):
                errors.append('第 %d 块缺少 runs' % (index + 1))
        elif kind == 'table':
            rows = block.get('rows')
            if not isinstance(rows, list) or not rows:
                errors.append('第 %d 块表格没有行' % (index + 1))
                continue
            width = len(rows[0])
            for row in rows:
                if len(row) != width:
                    errors.append('第 %d 块表格各行格数不一致' % (index + 1))
                    break
            for merge in block.get('merges') or []:
                try:
                    cell = rows[merge['row']][merge['col']]
                except (KeyError, IndexError, TypeError):
                    errors.append('第 %d 块合并单元格越界' % (index + 1))
                    continue
                if cell.get('covered'):
                    errors.append('第 %d 块合并起点是被覆盖的格子' % (index + 1))
        elif kind == 'image':
            asset = block.get('asset')
            if not asset or asset not in doc.assets:
                errors.append('第 %d 块图片缺少素材' % (index + 1))
    return errors


def _esc(text):
    return (text or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def _run_xml(run):
    text = run.get('text') or ''
    if text == '':
        return ''
    props = []
    if run.get('bold'):
        props.append('<w:b/>')
    if run.get('italic'):
        props.append('<w:i/>')
    if run.get('font'):
        font = _esc(run['font'])
        props.append('<w:rFonts w:ascii="%s" w:hAnsi="%s" w:eastAsia="%s" w:cs="%s"/>' % (font, font, font, font))
    if run.get('size'):
        half = int(round(float(run['size']) * 2))
        props.append('<w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (half, half))
    rpr = ('<w:rPr>%s</w:rPr>' % ''.join(props)) if props else ''
    parts = []
    chunks = text.split('\n')
    for index, chunk in enumerate(chunks):
        if chunk:
            preserve = ' xml:space="preserve"' if chunk[:1].isspace() or chunk[-1:].isspace() else ''
            parts.append('<w:r>%s<w:t%s>%s</w:t></w:r>' % (rpr, preserve, _esc(chunk)))
        if index != len(chunks) - 1:
            parts.append('<w:r>%s<w:br/></w:r>' % rpr)
    return ''.join(parts)


def _paragraph_xml(block):
    style = ''
    if block.get('type') == 'heading':
        style = '<w:pPr><w:pStyle w:val="Heading%d"/></w:pPr>' % int(block.get('level') or 1)
    elif block.get('style') == 'toc':
        style = '<w:pPr><w:pStyle w:val="TOC1"/></w:pPr>'
    body = ''.join(_run_xml(run) for run in block.get('runs') or []) or '<w:r><w:t></w:t></w:r>'
    return '<w:p>%s%s</w:p>' % (style, body)


def _image_xml(block, rel_id):
    width = int(block.get('w') or 0) or 96
    height = int(block.get('h') or 0) or 96
    cx = int(width * 914400 / 96)
    cy = int(height * 914400 / 96)
    name = _esc(Path(block.get('asset') or 'image').name)
    return (
        '<w:p><w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
        '<wp:extent cx="%d" cy="%d"/><wp:docPr id="%s" name="%s"/>'
        '<wp:cNvGraphicFramePr><a:graphicFrameLocks xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" noChangeAspect="1"/></wp:cNvGraphicFramePr>'
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:nvPicPr><pic:cNvPr id="0" name="%s"/><pic:cNvPicPr/></pic:nvPicPr>'
        '<pic:blipFill><a:blip r:embed="rId%s"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
    ) % (cx, cy, rel_id, name, name, rel_id, cx, cy)


def _cell_xml(cell, span, restart):
    props = []
    if span > 1:
        props.append('<w:gridSpan w:val="%d"/>' % span)
    if restart:
        props.append('<w:vMerge w:val="restart"/>')
    elif restart is False:
        props.append('<w:vMerge/>')
    pr = ('<w:tcPr>%s</w:tcPr>' % ''.join(props)) if props else ''
    if cell.get('covered'):
        body = '<w:p/>'
    else:
        body = _paragraph_xml({'type': 'paragraph', 'runs': cell.get('runs') or []})
    return '<w:tc>%s%s</w:tc>' % (pr, body)


def _merge_at(merges, row, col):
    for merge in merges or []:
        if merge['row'] <= row < merge['row'] + merge['rowspan'] and merge['col'] <= col < merge['col'] + merge['colspan']:
            return merge
    return None


def _table_xml(block):
    rows_xml = []
    rows = block.get('rows') or []
    merges = block.get('merges') or []
    for r, row in enumerate(rows):
        cells = []
        c = 0
        while c < len(row):
            cell = row[c]
            if cell.get('covered'):
                merge = _merge_at(merges, r, c)
                if merge and c == merge['col'] and r > merge['row']:
                    cells.append(_cell_xml(cell, int(merge['colspan']), False))
                    c += int(merge['colspan'])
                    continue
                c += 1
                continue
            span = int(cell.get('colspan') or 1)
            rowspan = int(cell.get('rowspan') or 1)
            cells.append(_cell_xml(cell, span, True if rowspan > 1 else None))
            c += span
        rows_xml.append('<w:tr>%s</w:tr>' % ''.join(cells))
    return '<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/></w:tblPr>%s</w:tbl>' % ''.join(rows_xml)


def _document_xml(doc):
    images = []
    body = []
    next_id = 2
    for block in doc.blocks:
        kind = block.get('type')
        if kind in ('heading', 'paragraph'):
            body.append(_paragraph_xml(block))
        elif kind == 'table':
            body.append(_table_xml(block))
        elif kind == 'image':
            images.append((next_id, block))
            body.append(_image_xml(block, next_id))
            next_id += 1
        elif kind == 'pagebreak':
            body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        elif kind == 'toc':
            body.append('<w:p><w:pPr><w:pStyle w:val="TOC1"/></w:pPr><w:r><w:t>目录</w:t></w:r></w:p>')
    body.append('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1800" w:bottom="1440" w:left="1800" w:header="851" w:footer="992"/></w:sectPr>')
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<w:body>%s</w:body></w:document>'
    ) % ''.join(body)
    return xml, images


def to_docx(doc, path, template=None):
    target = brush(doc, template) if template else doc
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    xml, images = _document_xml(target)
    overrides = ['<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>']
    defaults = [
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
    ]
    seen = set()
    rels = []
    media = []
    for rel_id, block in images:
        asset = block.get('asset')
        data = target.assets.get(asset, b'')
        ext = 'png'
        lower = (asset or '').lower()
        if lower.endswith('.jpg') or lower.endswith('.jpeg') or data[:3] == b'\xff\xd8\xff':
            ext = 'jpeg'
        if ext not in seen:
            content = 'image/png' if ext == 'png' else 'image/jpeg'
            defaults.append('<Default Extension="%s" ContentType="%s"/>' % (ext, content))
            seen.add(ext)
        filename = 'image%d.%s' % (rel_id, 'jpg' if ext == 'jpeg' else 'png')
        media.append(('word/media/' + filename, data))
        rels.append('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/%s"/>' % (rel_id, filename))
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">%s%s</Types>'
    ) % (''.join(defaults), ''.join(overrides))
    package = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '</Relationships>'
    )
    with zipfile.ZipFile(str(path), 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', content_types)
        archive.writestr('_rels/.rels', package)
        archive.writestr('word/document.xml', xml.encode('utf-8'))
        if rels:
            archive.writestr(
                'word/_rels/document.xml.rels',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>' % ''.join(rels),
            )
        for name, data in media:
            archive.writestr(name, data)


def _local(tag):
    return tag.rsplit('}', 1)[-1]


def _attr(el, name):
    for key, value in el.attrib.items():
        if key == name or key.rsplit('}', 1)[-1] == name:
            return value
    return None


def _heading_level(style):
    if not style:
        return None
    compact = style.replace(' ', '')
    for prefix in ('Heading', 'heading', '标题'):
        if compact.startswith(prefix) and compact[len(prefix):].isdigit():
            level = int(compact[len(prefix):])
            if 1 <= level <= 9:
                return level
    return None


def _run_from_xml(run):
    text = []
    props = {}
    for child in list(run):
        name = _local(child.tag)
        if name == 't' and child.text:
            text.append(child.text)
        elif name == 'br':
            if _attr(child, 'type') == 'page':
                text.append('\f')
            else:
                text.append('\n')
        elif name == 'tab':
            text.append('\t')
        elif name == 'rPr':
            for prop in list(child):
                pname = _local(prop.tag)
                if pname == 'b':
                    props['bold'] = _attr(prop, 'val') not in ('0', 'false')
                elif pname == 'i':
                    props['italic'] = _attr(prop, 'val') not in ('0', 'false')
                elif pname == 'sz':
                    raw = _attr(prop, 'val')
                    if raw and raw.isdigit():
                        props['size'] = int(raw) / 2.0
                elif pname == 'rFonts':
                    font = _attr(prop, 'eastAsia') or _attr(prop, 'ascii') or _attr(prop, 'hAnsi')
                    if font:
                        props['font'] = font
    item = {'text': ''.join(text)}
    item.update(props)
    return item


def _paragraph_from_xml(paragraph):
    style = None
    runs = []
    images = []
    for child in list(paragraph):
        name = _local(child.tag)
        if name == 'pPr':
            for prop in list(child):
                if _local(prop.tag) == 'pStyle':
                    style = _attr(prop, 'val')
        elif name == 'r':
            for sub in list(child):
                if _local(sub.tag) == 'drawing':
                    for el in sub.iter():
                        if _local(el.tag) == 'blip':
                            embed = _attr(el, 'embed')
                            if embed:
                                images.append(embed)
            item = _run_from_xml(child)
            if item.get('text'):
                runs.append(item)
    return style, runs, images


def _table_from_xml(table):
    raw_rows = []
    for tr in list(table):
        if _local(tr.tag) != 'tr':
            continue
        cells = []
        for tc in list(tr):
            if _local(tc.tag) != 'tc':
                continue
            span = 1
            vmerge = None
            runs = []
            for child in list(tc):
                name = _local(child.tag)
                if name == 'tcPr':
                    for prop in list(child):
                        pname = _local(prop.tag)
                        if pname == 'gridSpan':
                            raw = _attr(prop, 'val')
                            if raw and raw.isdigit():
                                span = int(raw)
                        elif pname == 'vMerge':
                            vmerge = 'restart' if _attr(prop, 'val') == 'restart' else 'continue'
                elif name == 'p':
                    _style, prouns, _images = _paragraph_from_xml(child)
                    if runs and prouns:
                        runs.append({'text': '\n'})
                    runs.extend(prouns)
            cells.append({'runs': runs, 'colspan': span, 'vmerge': vmerge})
        if cells:
            raw_rows.append(cells)
    return _grid_from_vmerge(raw_rows)


def _grid_from_vmerge(raw_rows):
    grid = {}
    open_origin = {}
    for r, cells in enumerate(raw_rows):
        c = 0
        for cell in cells:
            while (r, c) in grid:
                c += 1
            span = int(cell.get('colspan') or 1)
            if cell.get('vmerge') == 'continue':
                origin = open_origin.get(c)
                if origin is not None:
                    grid[origin]['rowspan'] = int(grid[origin].get('rowspan') or 1) + 1
                for dc in range(span):
                    grid[(r, c + dc)] = {'covered': True, 'runs': []}
                c += span
                continue
            item = {'runs': cell.get('runs') or [], 'colspan': span, 'rowspan': 1}
            grid[(r, c)] = item
            for dc in range(1, span):
                grid[(r, c + dc)] = {'covered': True, 'runs': []}
            if cell.get('vmerge') == 'restart':
                for dc in range(span):
                    open_origin[c + dc] = (r, c)
            else:
                for dc in range(span):
                    open_origin.pop(c + dc, None)
            c += span
    rows, merges = pack_grid(grid)
    return {'type': 'table', 'rows': rows, 'merges': merges}


def from_docx(path):
    blocks = []
    assets = {}
    image_n = 0
    with zipfile.ZipFile(str(path)) as archive:
        names = set(archive.namelist())
        root = ET.fromstring(archive.read('word/document.xml'))
        rels = {}
        if 'word/_rels/document.xml.rels' in names:
            for rel in ET.fromstring(archive.read('word/_rels/document.xml.rels')):
                rels[_attr(rel, 'Id')] = _attr(rel, 'Target')
        body = None
        for child in list(root):
            if _local(child.tag) == 'body':
                body = child
        if body is None:
            return WenjuDoc([], {'source': 'docx'}, {})
        for child in list(body):
            name = _local(child.tag)
            if name == 'p':
                style, runs, images = _paragraph_from_xml(child)
                page = False
                kept = []
                for run in runs:
                    if '\f' in run.get('text', ''):
                        page = True
                        run = dict(run)
                        run['text'] = run['text'].replace('\f', '')
                    if run.get('text'):
                        kept.append(run)
                if page and not kept:
                    blocks.append({'type': 'pagebreak'})
                elif kept:
                    level = _heading_level(style)
                    if level:
                        blocks.append({'type': 'heading', 'level': level, 'runs': kept})
                    elif style and str(style).upper().startswith('TOC'):
                        blocks.append({'type': 'paragraph', 'style': 'toc', 'runs': kept})
                    else:
                        blocks.append({'type': 'paragraph', 'style': 'body', 'runs': kept})
                for embed in images:
                    target = rels.get(embed) or ''
                    member = 'word/' + target.lstrip('/') if not target.startswith('word/') else target
                    if member not in names:
                        continue
                    image_n += 1
                    ext = Path(member).suffix.lower() or '.png'
                    asset = 'assets/image%d%s' % (image_n, ext)
                    assets[asset] = archive.read(member)
                    blocks.append({'type': 'image', 'asset': asset, 'w': 0, 'h': 0})
            elif name == 'tbl':
                blocks.append(_table_from_xml(child))
    return WenjuDoc(blocks, {'source': 'docx'}, assets)
