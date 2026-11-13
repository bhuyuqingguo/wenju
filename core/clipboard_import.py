import base64
import os
import re
import shutil
import struct
import tempfile
from html.parser import HTMLParser
from urllib.parse import unquote, urlparse

import wenju_format

HTML_MIMES = ('text/html', 'application/x-qt-windows-mime;value="HTML Format"')
RTF_MIMES = (
    'text/rtf', 'application/rtf', 'application/x-rtf', 'Rich Text Format',
    'application/x-qt-windows-mime;value="Rich Text Format"',
)
PLAIN_MIMES = ('text/plain',)
IMAGE_MIMES = (('image/png', 'png'), ('image/jpeg', 'jpg'), ('image/jpg', 'jpg'), ('image/bmp', 'bmp'), ('image/gif', 'gif'))
META_MIMES = (
    ('image/x-emf', 'emf'),
    ('image/emf', 'emf'),
    ('application/x-emf', 'emf'),
    ('application/emf', 'emf'),
    ('image/x-wmf', 'wmf'),
    ('image/wmf', 'wmf'),
    ('application/x-wmf', 'wmf'),
    ('application/wmf', 'wmf'),
    ('application/x-qt-windows-mime;value="Enhanced Metafile"', 'emf'),
    ('application/x-qt-windows-mime;value="MetaFilePict"', 'wmf'),
)
_HTML_IMAGE = {
    'png': 'png', 'gif': 'gif', 'bmp': 'bmp', 'x-bmp': 'bmp',
    'jpeg': 'jpg', 'jpg': 'jpg',
    'emf': 'emf', 'x-emf': 'emf', 'wmf': 'wmf', 'x-wmf': 'wmf',
}
HTML_FONT_PT = {1: 8, 2: 10, 3: 12, 4: 14, 5: 18, 6: 24, 7: 36}
_SKIP_RTF = {
    'colortbl', 'info', 'header', 'footer', 'headerf', 'footerf', 'headerl', 'footerr',
    'footnote', 'fldinst', 'field', 'generator', 'xmlnstbl', 'colorschememapping',
    'latentstyles', 'datastore', 'themedata', 'listtable', 'listoverridetable', 'revtbl',
    'rsidtbl', 'mmath', 'object', 'objdata', 'background', 'pn', 'filetbl', 'pgptbl',
    'operator', 'author', 'title', 'subject', 'doccomm', 'comment', 'creatim', 'revtim',
}
_DEST = _SKIP_RTF | {'rtf', 'fonttbl', 'stylesheet', 'pict', 'nonshppict', 'shppict'}
_GENERICS = {'serif', 'sans-serif', 'monospace', 'cursive', 'fantasy'}


class ClipboardEmpty(Exception):
    pass


def _progress(callback, value):
    if callback:
        callback(int(value))


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
                span_c = int(cell.get('colspan') or 1)
                span_r = int(cell.get('rowspan') or 1)
                if span_c > 1 or span_r > 1:
                    merges.append({'row': r, 'col': c, 'rowspan': span_r, 'colspan': span_c})
        rows.append(row)
    return rows, merges


def _asset_name(name):
    text = str(name or '').replace('\\', '/').split('/')[-1]
    return text or 'image.bin'


def _point_size(width, height, data):
    width = float(width or 0)
    height = float(height or 0)
    if data and data[:8] == b'\x89PNG\r\n\x1a\n' and len(data) >= 24 and (width <= 0 or height <= 0):
        px_w, px_h = struct.unpack('>II', data[16:24])
        if width <= 0 and px_w:
            width = px_w * 0.75
        if height <= 0 and px_h:
            height = px_h * 0.75
    if width <= 0:
        width = 72
    if height <= 0:
        height = 72
    return width, height


def _as_bytes(data):
    if data is None:
        return b''
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return data.encode('utf-8')
    raw = data.data() if hasattr(data, 'data') else data
    if isinstance(raw, bytes):
        return raw
    return bytes(raw)


def _first_bytes(mime, names):
    has = getattr(mime, 'hasFormat', None)
    data = getattr(mime, 'data', None)
    if not has or not data:
        return None
    for name in names:
        try:
            present = has(name)
        except Exception:
            present = False
        if not present:
            continue
        raw = _as_bytes(data(name))
        if raw.strip():
            return raw
    return None


def decode_markup(raw):
    if isinstance(raw, str):
        return raw
    head = raw[:1200]
    match = re.search(br'charset\s*=\s*["\']?\s*([A-Za-z0-9_\-]+)', head, re.I)
    encoding = 'utf-8'
    if match:
        encoding = match.group(1).decode('ascii', 'ignore').lower()
        if encoding in ('gb2312', 'gbk', 'gb18030'):
            encoding = 'gb18030'
    if encoding == 'gb18030':
        utf8 = _utf8_document(raw)
        if utf8 is not None:
            return utf8
    try:
        return raw.decode(encoding)
    except UnicodeDecodeError:
        return raw.decode('gb18030', 'replace')


def _utf8_document(raw):
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        return None
    if any(ord(ch) > 127 for ch in text):
        return text
    return None


def html_fragment(raw):
    data = raw.encode('utf-8') if isinstance(raw, str) else bytes(raw)
    if not data.lstrip()[:12].lower().startswith(b'version:'):
        return decode_markup(data)
    values = {}
    pos = 0
    while pos < len(data):
        newline = data.find(b'\n', pos)
        if newline < 0:
            break
        line = data[pos:newline].strip()
        pos = newline + 1
        found = re.match(br'(?i)(StartHTML|EndHTML|StartFragment|EndFragment):(\d+)', line)
        if found:
            values[found.group(1).decode().lower()] = int(found.group(2))
        if line.startswith(b'<') or (values and not line):
            break
        if line and not re.match(br'(?i)(version|starthtml|endhtml|startfragment|endfragment|sourceurl):', line):
            break
    start = values.get('startfragment', values.get('starthtml', 0))
    end = values.get('endfragment', values.get('endhtml', len(data)))
    if 0 <= start < end <= len(data):
        if start > 0 and data[start:start + 1] != b'<' and data[start - 1:start] == b'<':
            start -= 1
        data = data[start:end]
    return decode_markup(data)


def _css(style):
    found = {}
    if not style:
        return found
    for part in style.split(';'):
        if ':' not in part:
            continue
        key, value = part.split(':', 1)
        key = key.strip().lower()
        value = value.strip().strip('"').strip("'")
        if key in ('font-family', 'mso-fareast-font-family', 'mso-ascii-font-family'):
            for family in value.split(','):
                name = family.strip().strip('"').strip("'")
                if name and name.lower() not in _GENERICS:
                    if key == 'mso-fareast-font-family' or 'font' not in found:
                        found['font'] = name
                    break
        elif key == 'font-size':
            match = re.match(r'([0-9.]+)\s*(pt|px)?', value, re.I)
            if match:
                size = float(match.group(1))
                if (match.group(2) or '').lower() == 'px':
                    size = size * 0.75
                found['size'] = size
        elif key == 'font-weight':
            found['bold'] = value.lower() == 'bold' or (value.isdigit() and int(value) >= 600)
        elif key == 'font-style':
            found['italic'] = 'italic' in value.lower()
        elif key == 'mso-outline-level' and value.isdigit():
            found['outline'] = max(1, min(9, int(value)))
        elif key == 'mso-style-name':
            found['style_name'] = value
        elif key in ('page-break-before', 'break-before') and value.lower() in ('always', 'page'):
            found['page'] = True
        elif key in ('page-break-after', 'break-after') and value.lower() in ('always', 'page'):
            found['page_after'] = True
    return found


def _level_from_name(name):
    if not name:
        return None
    match = re.search(r'(?:标题|heading)\s*(\d+)', name, re.I)
    if match:
        level = int(match.group(1))
        if 1 <= level <= 9:
            return level
    return None


def _class_levels_from_css(text):
    levels = {}
    for match in re.finditer(r'([^{}]+)\{([^{}]*)\}', text or ''):
        selector, body = match.group(1), match.group(2)
        level = None
        outline = re.search(r'mso-outline-level\s*:\s*(\d+)', body, re.I)
        if outline:
            level = int(outline.group(1))
        if not level:
            named = re.search(r'mso-style-name\s*:\s*["\']?([^;"\']+)', body, re.I)
            if named:
                level = _level_from_name(named.group(1))
        if not level:
            level = _level_from_name(body)
        if not level or not 1 <= level <= 9:
            continue
        for part in selector.split(','):
            for name in re.findall(r'\.([A-Za-z_][\w-]*)', part):
                levels[name] = level
    return levels


def _level_from_class(class_name):
    if not class_name:
        return None
    for part in class_name.split():
        match = re.match(r'(?:MsoHeading|Heading|wpsHeading|yozo-heading-)(\d+)$', part, re.I)
        if match:
            return int(match.group(1))
        if part.lower() in ('msotitle', 'title'):
            return 1
    return None


def _is_toc(class_name, style_name):
    blob = '%s %s' % (class_name or '', style_name or '')
    return bool(re.search(r'(MsoToc|TOC\s*\d|目录)', blob, re.I))


def _keep_one_picture(kept, incoming, assets):
    """v:imagedata and the img that follows it are one picture."""
    new_name = incoming.get('asset') or ''
    old_name = kept.get('asset') or ''
    new_blob = assets.get(new_name) if new_name else None
    old_blob = assets.get(old_name) if old_name else None
    take_new = bool(new_blob) and not old_blob
    if new_blob and old_blob and _is_meta_name(new_name) and not _is_meta_name(old_name):
        take_new = True
    if take_new:
        if old_name and old_name != new_name:
            assets.pop(old_name, None)
        kept['asset'] = new_name
        if incoming.get('w'):
            kept['w'] = incoming['w']
        if incoming.get('h'):
            kept['h'] = incoming['h']
        if incoming.get('_from'):
            kept['_from'] = incoming['_from']
        return
    if new_name and new_name != old_name:
        assets.pop(new_name, None)


class _HtmlDoc(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.blocks = []
        self.assets = {}
        self.stack = []
        self.runs = []
        self.kind = None
        self.ignore = 0
        self.cell = None
        self.row = None
        self.table = None
        self.table_stack = []
        self.queued_tables = []
        self.images = 0
        self.toc_done = False
        self.later_images = []
        self.class_levels = {}
        self.style_text = []
        self.in_style = False
        self.progress = None
        self.total = 1
        self.seen = 0
        self.page_after = False
        self._same_image = None

    def _style(self):
        merged = {}
        for item in self.stack:
            for key in ('font', 'size', 'bold', 'italic'):
                if key in item:
                    merged[key] = item[key]
        return merged

    def _tick(self):
        self.seen += 1
        if not self.progress or self.seen % 25:
            return
        span = min(1.0, self.seen / float(self.total or 1))
        _progress(self.progress, min(79, 30 + int(49 * span)))

    def _add(self, text):
        if not text:
            return
        style = self._style()
        run = {'text': text}
        if style.get('font'):
            run['eastAsia'] = style['font']
            run['ascii'] = style['font']
        if style.get('size'):
            run['size_pt'] = style['size']
        if style.get('bold'):
            run['bold'] = True
        if style.get('italic'):
            run['italic'] = True
        if self.runs and {k: v for k, v in self.runs[-1].items() if k != 'text'} == {k: v for k, v in run.items() if k != 'text'}:
            self.runs[-1]['text'] += text
            return
        self.runs.append(run)

    def _flush(self):
        runs = [run for run in self.runs if run.get('text')]
        self.runs = []
        kind = self.kind
        self.kind = None
        page_after = self.page_after
        self.page_after = False
        if not runs:
            if page_after and self.cell is None and self.table is None:
                self.blocks.append({'type': 'pagebreak'})
            return
        if self.cell is not None:
            if self.cell['runs']:
                self.cell['runs'].append({'text': '\n'})
            self.cell['runs'].extend(runs)
            return
        if kind and kind[0] == 'h':
            self.blocks.append({'type': 'heading', 'level': kind[1], 'runs': runs})
        else:
            style = kind[1] if kind else 'body'
            if style == 'toc' and not self.toc_done:
                self.blocks.append({'type': 'toc'})
                self.toc_done = True
            self.blocks.append({'type': 'paragraph', 'style': style, 'runs': runs})
        if page_after and self.table is None:
            self.blocks.append({'type': 'pagebreak'})

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attr = {key.lower(): value or '' for key, value in attrs}
        if tag == 'style':
            self.in_style = True
            self.style_text = []
            self.ignore += 1
            return
        if tag == 'script':
            self.ignore += 1
            return
        if self.ignore:
            return
        self._tick()
        css = _css(attr.get('style'))
        if tag != 'img':
            self._same_image = None
        if tag == 'br':
            if css.get('page') and self.cell is None and self.table is None:
                self._flush()
                self.blocks.append({'type': 'pagebreak'})
            else:
                self._add('\n')
            return
        if tag == 'img' or tag.endswith('imagedata'):
            self._flush()
            image = self._image(attr)
            if image is None and src_present(attr):
                width = int(attr['width']) * 0.75 if attr.get('width', '').isdigit() else 0
                height = int(attr['height']) * 0.75 if attr.get('height', '').isdigit() else 0
                image = {'type': 'image', 'asset': '', 'w': width, 'h': height}
            if tag == 'img' and self._same_image is not None:
                if image:
                    _keep_one_picture(self._same_image, image, self.assets)
                self._same_image = None
                return
            if image and self.cell is not None:
                self.cell.setdefault('images', []).append(image)
            elif image:
                self.blocks.append(image)
            self._same_image = image if tag.endswith('imagedata') else None
            return
        if tag in ('b', 'strong'):
            self.stack.append({'bold': True})
            return
        if tag in ('i', 'em'):
            self.stack.append({'italic': True})
            return
        if tag == 'font':
            item = {key: css[key] for key in ('font', 'size', 'bold', 'italic') if key in css}
            if attr.get('face'):
                item['font'] = attr['face'].split(',')[0].strip()
            if 'size' not in item and attr.get('size') and attr['size'].lstrip('+-').isdigit():
                item['size'] = HTML_FONT_PT.get(int(attr['size'].lstrip('+-')), 12)
            self.stack.append(item)
            return
        if tag in ('span', 'a'):
            self.stack.append({key: css[key] for key in ('font', 'size', 'bold', 'italic') if key in css})
            return
        if tag == 'table':
            self._flush()
            if self.table is not None:
                self.table_stack.append((self.table, self.cell))
            self.table = {'grid': {}, 'row': -1, 'cursor': 0}
            self.cell = None
            return
        if tag == 'tr' and self.table is not None:
            self.table['row'] += 1
            self.table['cursor'] = 0
            self.row = []
            return
        if tag in ('td', 'th') and self.table is not None:
            self._flush()
            colspan = int(attr['colspan']) if attr.get('colspan', '').isdigit() else 1
            rowspan = int(attr['rowspan']) if attr.get('rowspan', '').isdigit() else 1
            self.stack.append({key: css[key] for key in ('font', 'size', 'bold', 'italic') if key in css})
            self.cell = {'runs': [], 'colspan': max(1, colspan), 'rowspan': max(1, rowspan)}
            return
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li', 'div'):
            self._open_block(tag, attr, css)

    def _open_block(self, tag, attr, css):
        if tag == 'div':
            if css.get('page') and self.cell is None and self.table is None:
                self._flush()
                self.blocks.append({'type': 'pagebreak'})
            self.page_after = bool(css.get('page_after'))
            self.stack.append({key: css[key] for key in ('font', 'size', 'bold', 'italic') if key in css})
            return
        if css.get('page') and self.cell is None and self.table is None:
            self._flush()
            self.blocks.append({'type': 'pagebreak'})
        else:
            self._flush()
        self.page_after = bool(css.get('page_after'))
        class_name = attr.get('class', '')
        if tag[0] == 'h' and tag[1:].isdigit():
            self.kind = ('h', int(tag[1:]))
        elif _is_toc(class_name, css.get('style_name')):
            self.kind = ('p', 'toc')
        else:
            level = (
                css.get('outline') or _level_from_class(class_name)
                or self._class_level(class_name) or _level_from_name(css.get('style_name'))
            )
            style_name = css.get('style_name') or 'body'
            self.kind = ('h', level) if level else ('p', style_name)
        self.stack.append({key: css[key] for key in ('font', 'size', 'bold', 'italic') if key in css})

    def _class_level(self, class_name):
        for part in (class_name or '').split():
            level = self.class_levels.get(part)
            if level:
                return level
        return None

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == 'style' and self.in_style:
            self.in_style = False
            self.ignore = max(0, self.ignore - 1)
            self.class_levels.update(_class_levels_from_css(''.join(self.style_text)))
            self.style_text = []
            return
        if tag in ('script', 'style'):
            self.ignore = max(0, self.ignore - 1)
            return
        if self.ignore:
            return
        if tag in ('b', 'strong', 'i', 'em', 'font', 'span', 'a', 'div', 'p', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            if tag in ('div', 'p', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
                self._flush()
            if self.stack:
                self.stack.pop()
            return
        if tag in ('td', 'th') and self.cell is not None and self.table is not None:
            self._flush()
            self._place_cell()
            self.cell = None
            if self.stack:
                self.stack.pop()
            return
        if tag == 'tr':
            self.row = None
            return
        if tag == 'table' and self.table is not None:
            self._flush()
            rows, merges = pack_grid(self.table['grid'])
            block = {'type': 'table', 'rows': rows, 'merges': merges} if rows else None
            if self.table_stack:
                self.table, self.cell = self.table_stack.pop()
                if block:
                    self.queued_tables.append(block)
                return
            if block:
                self.blocks.append(block)
            self.blocks.extend(self.queued_tables)
            self.queued_tables = []
            self.table = None

    def handle_data(self, data):
        if data and data.strip():
            self._same_image = None
        if self.in_style:
            if data:
                self.style_text.append(data)
            return
        if self.ignore or not data:
            return
        if data.strip() == '':
            if not self.runs or '\n' in data or '\r' in data:
                return
        elif '\n' in data or '\r' in data:
            data = re.sub(r'[ \t]*[\r\n]+[ \t]*', '', data)
            if not data:
                return
        if self.kind is None and self.cell is None:
            self.kind = ('p', 'body')
        self._add(data)

    def _place_cell(self):
        table = self.table
        row = table['row']
        col = table['cursor']
        while (row, col) in table['grid']:
            col += 1
        colspan = self.cell['colspan']
        rowspan = self.cell['rowspan']
        placed = {'runs': self.cell['runs'], 'colspan': colspan, 'rowspan': rowspan}
        if self.cell.get('images'):
            placed['images'] = list(self.cell['images'])
        table['grid'][(row, col)] = placed
        for dr in range(rowspan):
            for dc in range(colspan):
                if dr == 0 and dc == 0:
                    continue
                table['grid'][(row + dr, col + dc)] = {'covered': True, 'runs': []}
        table['cursor'] = col + colspan

    def _image(self, attr):
        src = attr.get('src') or ''
        width = int(attr['width']) * 0.75 if attr.get('width', '').isdigit() else 0
        height = int(attr['height']) * 0.75 if attr.get('height', '').isdigit() else 0
        data = b''
        ext = ''
        match = re.match(r'data:image/([a-z0-9.+-]+);base64,(.+)', src, re.I | re.S)
        if match:
            kind = match.group(1).lower()
            ext = _HTML_IMAGE.get(kind) or ''
            if not ext:
                return None
            try:
                data = base64.b64decode(re.sub(r'\s+', '', match.group(2)))
            except Exception:
                return None
        else:
            data, ext = _file_image(src)
            if not data:
                if src.startswith('file:'):
                    width, height = _point_size(width, height, b'')
                    return {'type': 'image', 'asset': '', 'w': width, 'h': height, '_from': 'file'}
                return None
        self.images += 1
        asset = 'image%d.%s' % (self.images, ext)
        self.assets[asset] = data
        width, height = _point_size(width, height, data)
        origin = 'data' if src.startswith('data:') else 'file'
        return {'type': 'image', 'asset': asset, 'w': width, 'h': height, '_from': origin}

    def close_doc(self):
        self._flush()
        if self.table is not None:
            rows, merges = pack_grid(self.table['grid'])
            if rows:
                self.blocks.append({'type': 'table', 'rows': rows, 'merges': merges})


def parse_html(raw, progress=None):
    _progress(progress, 30)
    parser = _HtmlDoc()
    fragment = html_fragment(raw)
    parser.progress = progress
    parser.total = max(1, fragment.count('<'))
    parser.feed(fragment)
    parser.close()
    parser.close_doc()
    _progress(progress, 80)
    return parser.blocks, parser.assets


def parse_plain(text, progress=None):
    _progress(progress, 40)
    text = (text or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    blocks = []
    for part in re.split(r'\n{2,}', text):
        if part.strip():
            blocks.append({'type': 'paragraph', 'style': 'body', 'runs': [{'text': part.strip()}]})
    _progress(progress, 80)
    return blocks


def _rtf_string(raw):
    if isinstance(raw, bytes):
        return raw.decode('latin1')
    return raw.encode('latin1', 'replace').decode('latin1')


# Word writes a picture as one hex run, with a newline about every 64 digits.
_HEX_BLOB = re.compile(r'[0-9A-Fa-f]{64,}(?:[\r\n]+[0-9A-Fa-f]{2,})*')


def _cut_plain(text, start, limit):
    end = limit
    for delim in ('\\', '{', '}', '\r', '\n'):
        pos = text.find(delim, start, end)
        if pos != -1:
            end = pos
    return text[start:end], end


def _decode_hex_parts(parts):
    """Decode pict hex in chunks so a 1 MiB picture is not one giant digit string."""
    buf = bytearray()
    carry = ''
    chunk = []
    size = 0

    def take(final):
        nonlocal carry, size
        if not chunk and not carry:
            return
        digits = carry + re.sub(r'[^0-9A-Fa-f]', '', ''.join(chunk))
        del chunk[:]
        size = 0
        carry = ''
        if len(digits) % 2:
            if final:
                digits = digits[:-1]
            else:
                carry = digits[-1]
                digits = digits[:-1]
        if digits:
            buf.extend(bytes.fromhex(digits))

    for part in parts:
        chunk.append(part)
        size += len(part)
        if size >= 262144:
            take(False)
    take(True)
    return bytes(buf)


def _tokens(text):
    i = 0
    n = len(text)

    def group():
        nonlocal i
        i += 1
        body = []
        while i < n and text[i] != '}':
            char = text[i]
            if char == '{':
                body.append(('group', group()))
            elif char == '\\':
                body.append(control())
            elif char in '\r\n':
                i += 1
            else:
                body.append(plain())
        if i < n and text[i] == '}':
            i += 1
        return body

    def control():
        nonlocal i
        i += 1
        if i >= n:
            return ('sym', '', None)
        char = text[i]
        if char == "'":
            hex_digits = text[i + 1:i + 3]
            i += 3
            try:
                return ('hex', int(hex_digits, 16))
            except ValueError:
                return ('hex', 0)
        if not char.isalpha():
            i += 1
            return ('sym', char, None)
        start = i
        while i < n and text[i].isalpha():
            i += 1
        word = text[start:i]
        number = None
        if i < n and (text[i].isdigit() or (text[i] == '-' and i + 1 < n and text[i + 1].isdigit())):
            start = i
            i += 1
            while i < n and text[i].isdigit():
                i += 1
            number = int(text[start:i])
        if word == 'bin' and isinstance(number, int) and number >= 0:
            if i < n and text[i] == ' ':
                i += 1
            count = number if i + number <= n else n - i
            blob = text[i:i + count]
            i += count
            return ('bin', blob, number)
        if i < n and text[i] == ' ':
            i += 1
        return ('word', word, number)

    def plain():
        nonlocal i
        if i + 64 <= n:
            match = _HEX_BLOB.match(text, i)
            if match is not None:
                raw = match.group()
                if len(raw) >= 2048 or '\r' in raw or '\n' in raw:
                    try:
                        data = bytes.fromhex(raw)
                    except ValueError:
                        data = None
                    if data:
                        i = match.end()
                        return ('hexbytes', data)
        chunk, end = _cut_plain(text, i, n)
        i = end
        return ('text', chunk)

    if text[:1] != '{':
        return []
    return group()


def _codepage(charset, ansicpg):
    if ansicpg == 65001 or charset == 65001:
        return 'utf-8'
    if charset in (136,) or ansicpg == 950:
        return 'big5'
    if charset in (134,) or ansicpg in (936, 54936):
        return 'gb18030'
    if ansicpg in (0, 1252, None):
        return 'cp1252'
    name = 'cp%d' % ansicpg
    try:
        ''.encode(name)
        return name
    except LookupError:
        return 'latin1'


class _RtfDoc(object):
    def __init__(self):
        self.fonts = {}
        self.styles = {}
        self.ansicpg = 1252
        self.deff = 0
        self.blocks = []
        self.assets = {}
        self.images = 0
        self.pending_images = []
        self.row_images = []
        self.fmt = {'bold': False, 'italic': False, 'font': None, 'size': None, 'uc': 1}
        self.para = {'outline': None, 'style': None, 'intbl': False}
        self.runs = []
        self.table_rows = []
        self.in_row = False
        self.row_cells = []
        self.row_defs = []
        self.cur_def = {}
        self.skip_chars = 0
        self.progress = None
        self.rtf_total = 1
        self.rtf_seen = 0
        self.in_fallback_pict = False
        self.skip_next_nonshppict = False

    def parse(self, raw, progress=None):
        _progress(progress, 30)
        self.progress = progress
        text = _rtf_string(raw)
        self.rtf_total = max(1, len(text) // 12)
        tokens = _tokens(text)
        self._walk(tokens)
        if self.in_row:
            self._finish_row()
        if self.table_rows:
            self._finish_table()
        self._flush_para()
        _progress(progress, 80)
        return self.blocks, self.assets

    def _dest(self, tokens):
        index = 0
        if tokens and tokens[0][0] in ('word', 'sym') and tokens[0][1] == '*':
            index = 1
            if index < len(tokens) and tokens[index][0] == 'word':
                return tokens[index][1], index + 1
            return '*', index
        if tokens and tokens[0][0] == 'word' and tokens[0][1] in _DEST:
            return tokens[0][1], 1
        return None, 0

    def _walk(self, tokens):
        dest, start = self._dest(tokens)
        if dest == 'fonttbl':
            for token in tokens[start:]:
                if token[0] == 'group':
                    self._font(token[1])
            return
        if dest == 'stylesheet':
            for token in tokens[start:]:
                if token[0] == 'group':
                    self._style_def(token[1])
            return
        if dest == 'pict':
            self._pict(tokens[start:])
            return
        if dest == 'nonshppict':
            self.in_fallback_pict = True
            try:
                self._content(tokens[start:])
            finally:
                self.in_fallback_pict = False
            return
        if dest == 'object':
            self._object(tokens[start:])
            return
        if dest in _SKIP_RTF or dest == '*':
            return
        self._content(tokens[start:] if dest else tokens)

    def _font(self, tokens):
        number = None
        charset = None
        raw = bytearray()
        chars = []
        skip = 0
        uc = 1
        for token in tokens:
            if skip and token[0] in ('text', 'hex'):
                if token[0] == 'hex':
                    skip -= 1
                    continue
                if len(token[1]) <= skip:
                    skip -= len(token[1])
                    continue
                token = ('text', token[1][skip:])
                skip = 0
            if token[0] == 'word' and token[1] == 'f' and token[2] is not None and number is None:
                number = token[2]
            elif token[0] == 'word' and token[1] == 'fcharset':
                charset = token[2]
            elif token[0] == 'word' and token[1] == 'uc' and token[2] is not None:
                uc = token[2]
            elif token[0] == 'word' and token[1] == 'u' and token[2] is not None:
                code = token[2] if token[2] >= 0 else token[2] + 65536
                if 0 <= code <= 0x10FFFF:
                    chars.append(chr(code))
                skip = uc
            elif token[0] == 'hex':
                raw.append(token[1] if isinstance(token[1], int) else 0)
            elif token[0] == 'text':
                chars.append(token[1])
        decoded = raw.decode(_codepage(charset, self.ansicpg), 'replace')
        literal = ''.join(chars)
        if self.ansicpg == 65001 and literal:
            try:
                literal = literal.encode('latin1').decode('utf-8')
            except UnicodeError:
                pass
        name = (decoded + literal).replace(';', '').strip()
        if number is not None:
            self.fonts[number] = {'name': name, 'charset': charset}

    def _style_def(self, tokens):
        number = None
        level = None
        for token in tokens:
            if token[0] != 'word':
                continue
            if token[1] == 's' and token[2] is not None and number is None:
                number = token[2]
            elif token[1] == 'outlinelevel' and token[2] is not None:
                level = token[2] + 1
        if number is not None and level:
            self.styles[number] = max(1, min(9, level))

    def _pict(self, tokens):
        blip = None
        width = height = None
        pieces = []
        text_parts = []

        def flush_text():
            if text_parts:
                pieces.append(_decode_hex_parts(text_parts))
                del text_parts[:]

        for token in tokens:
            kind = token[0]
            if kind == 'group':
                continue
            if kind == 'word' and (token[1] in ('pngblip', 'jpegblip', 'wbitmap', 'dibitmap', 'emfblip') or token[1] == 'wmetafile'):
                blip = token[1]
            elif kind == 'word' and token[1] == 'picwgoal' and token[2]:
                width = token[2] / 20.0
            elif kind == 'word' and token[1] == 'pichgoal' and token[2]:
                height = token[2] / 20.0
            elif kind == 'bin':
                flush_text()
                pieces.append(token[1].encode('latin1'))
            elif kind == 'hexbytes':
                flush_text()
                pieces.append(token[1])
            elif kind == 'text':
                text_parts.append(token[1])
        flush_text()
        if not blip:
            return
        data = b''.join(pieces)
        if not data:
            return
        if blip == 'jpegblip':
            ext = 'jpg'
        elif blip == 'emfblip':
            ext = 'emf'
        elif blip == 'wmetafile':
            ext = 'wmf'
        elif blip in ('wbitmap', 'dibitmap') or data[:2] == b'BM':
            ext = 'bmp'
        elif data[:6] in (b'GIF87a', b'GIF89a'):
            ext = 'gif'
        else:
            ext = 'png'
        if self._skip_raster_fallback(ext):
            return
        self.images += 1
        asset = 'rtf%d.%s' % (self.images, ext)
        self.assets[asset] = data
        width, height = _point_size(width, height, data)
        image = {'type': 'image', 'asset': asset, 'w': width, 'h': height}
        self._place_image(image)

    def _place_image(self, image):
        if self.in_row:
            self.row_images.append(image)
            return
        self._finish_para_before_image()
        self.blocks.append(image)

    def _skip_raster_fallback(self, ext):
        if not self.in_fallback_pict or ext not in ('png', 'jpg', 'gif', 'bmp'):
            return False
        candidates = list(self.blocks) + list(self.pending_images) + list(self.row_images)
        if not candidates:
            return False
        last = candidates[-1]
        return last.get('type') == 'image' and str(last.get('asset') or '').lower().endswith(('.emf', '.wmf'))

    def _object(self, tokens):
        images_before = self.images
        self._walk_object(tokens, False)
        if self.images == images_before:
            self._walk_object(tokens, True)

    def _walk_object(self, tokens, objdata_only):
        for token in tokens:
            if token[0] != 'group':
                continue
            dest, start = self._dest(token[1])
            body = token[1][start:] if dest else token[1]
            if dest == 'objdata':
                if objdata_only:
                    self._objdata_image(body)
                continue
            if objdata_only:
                self._walk_object(token[1], True)
                continue
            if dest == 'pict':
                self._pict(body)
            elif dest in ('result', None):
                self._content(body)
            else:
                self._walk_object(body, False)

    def _objdata_image(self, tokens):
        hex_text = []

        def walk(items):
            for token in items:
                if token[0] == 'text':
                    hex_text.append(token[1])
                elif token[0] == 'group':
                    walk(token[1])

        walk(tokens)
        digits = re.sub(r'[^0-9A-Fa-f]', '', ''.join(hex_text))
        if len(digits) < 32 or len(digits) > wenju_format.MAX_ASSET_BYTES * 2:
            return
        if len(digits) % 2:
            digits = digits[:-1]
        try:
            data = bytes.fromhex(digits)
        except ValueError:
            return
        payload, kind = wenju_format.image_bytes(data)
        if not payload or kind not in ('emf', 'wmf', 'png', 'jpg', 'gif', 'bmp'):
            return
        self.images += 1
        asset = 'rtf%d.%s' % (self.images, kind)
        self.assets[asset] = payload
        width, height = _point_size(None, None, payload)
        image = {'type': 'image', 'asset': asset, 'w': width, 'h': height}
        self._place_image(image)

    def _content(self, tokens):
        pending = bytearray()

        def flush_bytes():
            if not pending:
                return
            self._add(pending.decode(self._encoding(), 'replace'))
            pending[:] = b''

        for token in tokens:
            self.rtf_seen += 1
            if self.progress and self.rtf_seen % 80 == 0:
                span = min(1.0, self.rtf_seen / float(self.rtf_total or 1))
                _progress(self.progress, min(79, 30 + int(49 * span)))
            kind = token[0]
            if kind == 'group':
                flush_bytes()
                dest, _start = self._dest(token[1])
                if dest == 'nonshppict' and self.skip_next_nonshppict:
                    self.skip_next_nonshppict = False
                    continue
                saved = (dict(self.fmt), dict(self.para), self.skip_chars)
                self._walk(token[1])
                self.fmt, self.para, self.skip_chars = saved
                self.skip_next_nonshppict = dest == 'shppict'
                continue
            if kind == 'hexbytes':
                continue
            if not (kind == 'text' and not str(token[1]).strip()):
                self.skip_next_nonshppict = False
            if kind == 'hex':
                if self.skip_chars:
                    self.skip_chars -= 1
                    continue
                pending.append(token[1] if isinstance(token[1], int) else 0)
                continue
            flush_bytes()
            if kind == 'text':
                text = token[1]
                if self.skip_chars:
                    if len(text) <= self.skip_chars:
                        self.skip_chars -= len(text)
                        continue
                    text = text[self.skip_chars:]
                    self.skip_chars = 0
                self._add(text)
            elif kind == 'sym' and token[1] in ('\\', '{', '}'):
                self._add(token[1])
            elif kind == 'sym' and token[1] == '~':
                self._add('\u00a0')
            elif kind == 'word':
                self._word(token[1], token[2])
        flush_bytes()

    def _encoding(self):
        number = self.fmt.get('font')
        if number is None:
            number = self.deff
        font = self.fonts.get(number) or {}
        return _codepage(font.get('charset'), self.ansicpg)

    def _add(self, text):
        if text is None or text == '':
            return
        if self.ansicpg == 65001:
            try:
                text = text.encode('latin1').decode('utf-8')
            except UnicodeError:
                pass
        run = {'text': text}
        if self.fmt.get('bold'):
            run['bold'] = True
        if self.fmt.get('italic'):
            run['italic'] = True
        if self.fmt.get('size'):
            run['size_pt'] = self.fmt['size']
        number = self.fmt.get('font')
        font = self.fonts.get(self.deff if number is None else number)
        if font and font.get('name'):
            run['eastAsia'] = font['name']
            run['ascii'] = font['name']
        if self.runs:
            prev = self.runs[-1]
            if {k: prev.get(k) for k in ('bold', 'italic', 'size_pt', 'eastAsia', 'ascii')} == {k: run.get(k) for k in ('bold', 'italic', 'size_pt', 'eastAsia', 'ascii')}:
                prev['text'] += text
                return
        self.runs.append(run)

    def _clean(self, runs):
        cleaned = []
        for run in runs:
            text = run.get('text') or ''
            if text == '':
                continue
            item = dict(run)
            item['text'] = text
            if cleaned:
                prev = cleaned[-1]
                if {k: prev.get(k) for k in ('bold', 'italic', 'size_pt', 'eastAsia', 'ascii')} == {k: item.get(k) for k in ('bold', 'italic', 'size_pt', 'eastAsia', 'ascii')}:
                    prev['text'] += text
                    continue
            cleaned.append(item)
        while cleaned and cleaned[-1].get('text') == '\n':
            cleaned.pop()
        return [run for run in cleaned if run.get('text')]

    def _flush_para(self):
        runs = self._clean(self.runs)
        self.runs = []
        if not runs:
            return
        level = self.para.get('outline')
        if level is None and self.para.get('style') in self.styles:
            level = self.styles[self.para.get('style')]
        if level:
            self.blocks.append({'type': 'heading', 'level': max(1, min(9, int(level))), 'runs': runs})
        else:
            self.blocks.append({'type': 'paragraph', 'style': 'body', 'runs': runs})

    def _finish_para_before_image(self):
        if self.table_rows and not self.in_row:
            self._finish_table()
        self._flush_para()

    def _word(self, name, number):
        if name == 'uc':
            self.fmt['uc'] = 1 if number is None else number
        elif name == 'u' and number is not None:
            code = number if number >= 0 else number + 65536
            if 0 <= code <= 0x10FFFF:
                self._add(chr(code))
            self.skip_chars = self.fmt.get('uc') or 0
        elif name in ('b', 'i'):
            self.fmt['bold' if name == 'b' else 'italic'] = number is None or number != 0
        elif name == 'fs':
            self.fmt['size'] = None if number is None else number / 2.0
        elif name == 'f' and number is not None:
            self.fmt['font'] = number
        elif name == 'pard':
            self.para = {'outline': None, 'style': None, 'intbl': False}
        elif name == 'plain':
            self.fmt = {'bold': False, 'italic': False, 'font': None, 'size': None, 'uc': self.fmt.get('uc', 1)}
        elif name == 'outlinelevel' and number is not None:
            self.para['outline'] = number + 1
        elif name == 's' and number is not None:
            self.para['style'] = number
        elif name == 'intbl':
            self.para['intbl'] = number is None or number != 0
        elif name == 'par':
            if self.in_row or self.para.get('intbl'):
                self._add('\n')
            else:
                if self.table_rows:
                    self._finish_table()
                self._flush_para()
        elif name == 'line':
            self._add('\n')
        elif name == 'tab':
            self._add('\t')
        elif name == 'page':
            if self.table_rows:
                self._finish_table()
            self._flush_para()
            self.blocks.append({'type': 'pagebreak'})
        elif name == 'trowd':
            self.in_row = True
            self.cur_def = {}
            self.row_defs = []
            if not self.row_cells:
                self.row_cells = []
        elif name == 'clvmgf':
            self.cur_def['vmerge'] = 'restart'
        elif name == 'clvmrg':
            self.cur_def['vmerge'] = 'continue'
        elif name == 'clmgf':
            self.cur_def['hmerge'] = 'restart'
        elif name == 'clmrg':
            self.cur_def['hmerge'] = 'continue'
        elif name == 'cellx':
            self.row_defs.append(self.cur_def)
            self.cur_def = {}
        elif name == 'cell':
            self._capture_cell()
        elif name == 'row':
            self._finish_row()
        elif name == 'ansicpg' and number is not None:
            self.ansicpg = number
        elif name == 'deff' and number is not None:
            self.deff = number

    def _capture_cell(self):
        item = {'runs': self._clean(self.runs)}
        if self.row_images:
            item['images'] = list(self.row_images)
            self.row_images = []
        self.row_cells.append(item)
        self.runs = []

    def _finish_row(self):
        if self.runs:
            self._capture_cell()
        expanded = []
        for index, cell in enumerate(self.row_cells):
            spec = self.row_defs[index] if index < len(self.row_defs) else {}
            if spec.get('hmerge') == 'continue' and expanded:
                expanded[-1]['colspan'] = int(expanded[-1].get('colspan') or 1) + 1
                expanded[-1]['runs'] = _keep_runs(expanded[-1].get('runs'), cell.get('runs'))
                if cell.get('images'):
                    expanded[-1].setdefault('images', []).extend(cell['images'])
                continue
            item = {'runs': cell.get('runs') or [], 'colspan': 1, 'vmerge': spec.get('vmerge')}
            if cell.get('images'):
                item['images'] = list(cell['images'])
            expanded.append(item)
        self.table_rows.append(expanded)
        self.row_cells = []
        self.in_row = False

    def _finish_table(self):
        grid = {}
        open_origin = {}
        for r, cells in enumerate(self.table_rows):
            c = 0
            for cell in cells:
                while (r, c) in grid:
                    c += 1
                span = int(cell.get('colspan') or 1)
                if cell.get('vmerge') == 'continue':
                    origin = open_origin.get(c)
                    if origin is not None and origin in grid:
                        grid[origin]['rowspan'] = int(grid[origin].get('rowspan') or 1) + 1
                        grid[origin]['runs'] = _keep_runs(grid[origin].get('runs'), cell.get('runs'))
                    for dc in range(span):
                        grid[(r, c + dc)] = {'covered': True, 'runs': []}
                    c += span
                    continue
                item = {'runs': cell.get('runs') or [], 'colspan': span, 'rowspan': 1}
                if cell.get('images'):
                    item['images'] = list(cell['images'])
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
        if rows:
            self.blocks.append({'type': 'table', 'rows': rows, 'merges': merges})
        self.table_rows = []
        if self.row_images:
            self.blocks.extend(self.row_images)
            self.row_images = []


def _run_text(runs):
    return ''.join(run.get('text') or '' for run in runs or [])


def _keep_runs(origin, extra):
    if not _run_text(extra):
        return origin or []
    if not _run_text(origin) or _run_text(origin) == _run_text(extra):
        return list(extra if not _run_text(origin) else origin)
    return list(origin) + list(extra)


def parse_rtf(raw, progress=None):
    return _RtfDoc().parse(raw, progress)


def _nonempty(blocks, assets):
    return bool(blocks or assets)


def _has_bytes(raw):
    if not raw:
        return False
    return bool(raw.strip() if isinstance(raw, str) else raw.strip())


def src_present(attr):
    return bool((attr.get('src') or '').strip())


def _merge_rtf_images(blocks, assets, rtf):
    rtf_blocks, rtf_assets = parse_rtf(rtf, None)
    pictures = [block for block in rtf_blocks if block.get('type') == 'image' and block.get('asset')]
    used = 0
    kept = []
    for block in blocks:
        if block.get('type') == 'image' and not block.get('asset'):
            if used >= len(pictures):
                continue
            src = pictures[used]
            used += 1
            kept.append({
                'type': 'image',
                'asset': src['asset'],
                'w': block.get('w') or src.get('w') or 0,
                'h': block.get('h') or src.get('h') or 0,
            })
            assets[src['asset']] = rtf_assets.get(src['asset'], b'')
            continue
        kept.append(block)
    for src in pictures[used:]:
        kept.append(dict(src))
        assets[src['asset']] = rtf_assets.get(src['asset'], b'')
    return kept, assets


_CN = ('', '一', '二', '三', '四', '五', '六', '七', '八', '九')
_SIZES = {
    '初号': 42, '小初': 36, '一号': 26, '小一': 24, '二号': 22, '小二': 18,
    '三号': 16, '小三': 15, '四号': 14, '小四': 12, '五号': 10.5, '小五': 9,
    '六号': 7.5, '小六': 6.5, '七号': 5.5, '八号': 5,
}


def _pt_name(value):
    if isinstance(value, bool) or value is None or value == '':
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text in _SIZES:
        return float(_SIZES[text])
    try:
        return float(text)
    except ValueError:
        return None


def brush_styles(rules):
    if not isinstance(rules, dict) or ('字体' not in rules and '正文' not in rules):
        return rules
    fonts = rules.get('字体') or {}
    body = rules.get('正文') or {}
    heads = rules.get('标题') or {}
    ascii_font = fonts.get('西文') or 'Times New Roman'
    body_size = _pt_name(body.get('字号')) or 16
    styles = {
        '正文': {
            'eastAsia': fonts.get('正文') or '仿宋_GB2312',
            'ascii': ascii_font,
            'hAnsi': ascii_font,
            'size_pt': body_size,
            'bold': bool(body.get('加粗')),
        },
    }
    for level in range(1, 10):
        spec = heads.get(_CN[level] + '级') or {}
        font = spec.get('字体') or fonts.get(_CN[level] + '级标题') or fonts.get('正文')
        styles['标题%d' % level] = {
            'eastAsia': font,
            'ascii': ascii_font,
            'hAnsi': ascii_font,
            'size_pt': _pt_name(spec.get('字号')) or body_size,
            'bold': bool(spec.get('加粗')),
        }
    return styles


def _strip_drive_slash(path):
    if len(path) > 2 and path[0] == '/' and path[2] == ':':
        return path[1:]
    return path


def file_url_candidates(src, windows=None):
    """Paths a file:// URL may name. UTF-8 percent-decoding is first, GBK second.

    windows is accepted so a test can force the Windows drive-letter rule.
    A leading slash before a drive letter is not part of the path on either
    platform: file:///C:/Users is C:/Users.
    """
    text = str(src or '').strip()
    if not text.lower().startswith('file:'):
        return []
    if windows is None:
        windows = os.name == 'nt'
    text = text.replace('\\', '/')
    parsed = urlparse(text)
    raw = parsed.path or ''
    found = []
    seen = set()
    for encoding in ('utf-8', 'gbk'):
        try:
            path = unquote(raw, encoding=encoding, errors='strict')
        except UnicodeDecodeError:
            continue
        if windows or os.name != 'nt':
            path = _strip_drive_slash(path)
        if path and path not in seen:
            seen.add(path)
            found.append(path)
    return found


def _read_image_file(path):
    if not path or not os.path.isfile(path):
        return b'', ''
    try:
        size = os.path.getsize(path)
    except OSError:
        return b'', ''
    if size <= 0 or size > wenju_format.MAX_ASSET_BYTES:
        return b'', ''
    try:
        with open(path, 'rb') as handle:
            data = handle.read()
    except OSError:
        return b'', ''
    payload, kind = wenju_format.image_bytes(data)
    if not kind:
        return b'', ''
    return payload, kind


def _file_image(src):
    for path in file_url_candidates(src, os.name == 'nt'):
        payload, kind = _read_image_file(path)
        if payload:
            return payload, kind
    return b'', ''


def _each_image(blocks):
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        if block.get('type') == 'image':
            yield block
        elif block.get('type') == 'table':
            for row in block.get('rows') or []:
                for cell in row or []:
                    if isinstance(cell, dict):
                        for image in cell.get('images') or []:
                            yield image


def _drop_empty_images(blocks):
    kept = []
    for block in blocks:
        if block.get('type') == 'image' and not block.get('asset'):
            continue
        if block.get('type') == 'table':
            for row in block.get('rows') or []:
                for cell in row or []:
                    if not isinstance(cell, dict) or not cell.get('images'):
                        continue
                    cell['images'] = [image for image in cell['images'] if image.get('asset')]
                    if not cell['images']:
                        cell.pop('images', None)
        kept.append(block)
    return kept


def _is_meta_name(name):
    return str(name or '').lower().endswith(('.emf', '.wmf'))


def _asset_still_used(blocks, name, skip):
    for image in _each_image(blocks):
        if image is not skip and image.get('asset') == name:
            return True
    return False


def _claim_rtf_picture(slot, src, blocks, assets, rtf_assets):
    """Use this RTF picture only when it belongs in this HTML slot.

    A bitmap slot takes an EMF/WMF at the same position. The same bytes are
    already the HTML picture, so the RTF copy is not a second picture.
    Anything else is not consumed: the caller keeps the RTF picture where it
    was parsed.
    """
    if not slot.get('asset') or not src.get('asset'):
        return False
    src_blob = rtf_assets.get(src['asset'], b'')
    slot_blob = assets.get(slot['asset'], b'')
    if _is_meta_name(src.get('asset')) and not _is_meta_name(slot.get('asset')):
        old = slot['asset']
        assets[src['asset']] = src_blob
        slot['asset'] = src['asset']
        if not slot.get('w'):
            slot['w'] = src.get('w') or 0
        if not slot.get('h'):
            slot['h'] = src.get('h') or 0
        if old != src['asset'] and not _asset_still_used(blocks, old, slot):
            assets.pop(old, None)
        return True
    if slot_blob and slot_blob == src_blob:
        return True
    return False


def _pair_pictures(html_images, rtf_images, blocks, assets, rtf_assets):
    """Pair pictures inside one container. Return RTF pictures that stay put.

    An empty or unreadable HTML image does not advance the RTF cursor.
    used only moves when the picture is actually kept in the HTML slot.
    """
    live = [image for image in rtf_images if image.get('asset')]
    used = 0
    for slot in html_images:
        if not slot.get('asset'):
            continue
        if used >= len(live):
            break
        src = live[used]
        if not _claim_rtf_picture(slot, src, blocks, assets, rtf_assets):
            break
        used += 1
    kept = []
    for src in live[used:]:
        kept.append(src)
    return kept


def _copy_picture(src, assets, rtf_assets):
    assets[src['asset']] = rtf_assets.get(src['asset'], b'')
    return {
        'type': 'image',
        'asset': src['asset'],
        'w': src.get('w') or 0,
        'h': src.get('h') or 0,
    }


def _tables_of(blocks):
    return [block for block in blocks or [] if block.get('type') == 'table']


def _open_cells(table):
    found = []
    for row_index, row in enumerate(table.get('rows') or []):
        for col_index, cell in enumerate(row):
            if isinstance(cell, dict) and not cell.get('covered'):
                found.append((row_index, col_index, cell))
    return found


def _apply_rtf_pictures(blocks, assets, rtf):
    rtf_blocks, rtf_assets = parse_rtf(rtf, None)
    rtf_top = [(index, block) for index, block in enumerate(rtf_blocks) if block.get('type') == 'image']
    top_kept = _pair_pictures(
        [block for block in blocks if block.get('type') == 'image'],
        [block for _index, block in rtf_top],
        blocks, assets, rtf_assets,
    )
    kept_top = set(id(block) for block in top_kept)
    html_tables = _tables_of(blocks)
    rtf_tables = _tables_of(rtf_blocks)
    for index, rtf_table in enumerate(rtf_tables):
        html_table = html_tables[index] if index < len(html_tables) else None
        html_cells = {}
        if html_table is not None:
            for row_index, col_index, cell in _open_cells(html_table):
                html_cells[(row_index, col_index)] = cell
        for row_index, col_index, cell in _open_cells(rtf_table):
            html_cell = html_cells.get((row_index, col_index))
            html_images = list(html_cell.get('images') or []) if html_cell is not None else []
            kept = _pair_pictures(html_images, list(cell.get('images') or []), blocks, assets, rtf_assets)
            if html_cell is None or not kept:
                continue
            images = list(html_cell.get('images') or [])
            for src in kept:
                images.append(_copy_picture(src, assets, rtf_assets))
            html_cell['images'] = images
    for index, src in reversed([item for item in rtf_top if id(item[1]) in kept_top]):
        at = index if index < len(blocks) else len(blocks)
        blocks.insert(at, _copy_picture(src, assets, rtf_assets))
    return blocks, assets


def _style_shells(blocks):
    names = {}

    def take(node):
        if not isinstance(node, dict):
            return
        name = node.get('style')
        if name:
            names.setdefault(name, {})
        for row in node.get('rows') or []:
            for cell in row or []:
                take(cell)

    for block in blocks or []:
        take(block)
    return names


def _through_docx(doc, progress=None):
    folder = tempfile.mkdtemp(prefix='wenju-clip-')
    try:
        path = os.path.join(folder, 'paste.docx')
        _progress(progress, 86)
        wenju_format.to_docx(doc, path)
        doc.blocks = []
        doc.assets.clear()
        _progress(progress, 93)
        back = wenju_format.from_docx(path)
        back.source = {'kind': 'clipboard', 'name': ''}
        return back
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def document_from_parts(html=None, rtf=None, plain=None, images=None, progress=None):
    _progress(progress, 5)
    images = {_asset_name(name): data for name, data in dict(images or {}).items()}
    blocks = []
    assets = {}
    if _has_bytes(html):
        blocks, assets = parse_html(html, progress)
    html = None
    if _nonempty(blocks, assets):
        if _has_bytes(rtf):
            blocks, assets = _apply_rtf_pictures(blocks, assets, rtf)
    elif _has_bytes(rtf):
        blocks, assets = parse_rtf(rtf, progress)
    rtf = None
    if not _nonempty(blocks, assets) and plain and str(plain).strip():
        blocks = parse_plain(plain, progress)
        assets = {}
    blocks = _drop_empty_images(blocks)
    if images and not any(True for _image in _each_image(blocks)):
        assets.update(images)
        for name, data in images.items():
            width, height = _point_size(0, 0, data)
            blocks.append({'type': 'image', 'asset': name, 'w': width, 'h': height})
    if not _nonempty(blocks, assets):
        raise ClipboardEmpty('剪贴板里没有可导入的文字、表格或图片')
    _progress(progress, 80)
    doc = wenju_format.WenjuDoc(
        blocks, _style_shells(blocks), assets, source={'kind': 'clipboard', 'name': ''})
    doc = _through_docx(doc, progress)
    _progress(progress, 100)
    return doc


def clip_failure_text(exc):
    """Last line of an exception, or a fixed sentence when the message is empty."""
    try:
        lines = str(exc).splitlines()
    except Exception:
        return '无法读取剪贴板'
    text = lines[-1].strip() if lines else ''
    if not text:
        return '无法读取剪贴板'
    return text[:180]


class ClipRead(object):
    """Whether a clipboard parse may still update the preview.

    cancel marks the parse ignored but leaves running set. The completion
    signal is then dropped. running clears only when the worker thread ends.
    """

    def __init__(self):
        self.running = False
        self.ignore = False

    def start(self):
        self.running = True
        self.ignore = False

    def cancel(self):
        if self.running:
            self.ignore = True

    def accept(self):
        if self.ignore or not self.running:
            return False
        self.running = False
        return True

    def thread_finished(self):
        if not self.ignore:
            return False
        self.running = False
        self.ignore = False
        return True


def parts_from_mime(mime):
    html = _first_bytes(mime, HTML_MIMES)
    if html is None and getattr(mime, 'html', None):
        text = mime.html() or ''
        if text.strip():
            html = text.encode('utf-8')
    rtf = _first_bytes(mime, RTF_MIMES)
    plain = ''
    if getattr(mime, 'text', None) and mime.text():
        plain = mime.text()
    else:
        raw = _first_bytes(mime, PLAIN_MIMES)
        if raw:
            if raw.startswith(b'\xff\xfe') or raw.startswith(b'\xfe\xff'):
                plain = raw.decode('utf-16')
            else:
                plain = raw.decode('utf-8', 'replace')
    images = {}
    chosen = _meta_from_mime(mime) or _bitmap_from_mime(mime)
    if chosen:
        images[chosen[0]] = chosen[1]
    return html, rtf, plain, images


def document_from_mime(mime, progress=None):
    html, rtf, plain, images = parts_from_mime(mime)
    return document_from_parts(html, rtf, plain, images, progress)


def _bitmap_from_mime(mime):
    for mime_name, ext in IMAGE_MIMES:
        raw = _first_bytes(mime, (mime_name,))
        if raw:
            return _coerce_bitmap(raw, ext)
    raw = _first_bytes(mime, ('application/x-qt-image',))
    if raw:
        found = _coerce_bitmap(raw, 'png')
        if found:
            return found
    png = _qt_image_png(mime)
    if png:
        return ('clipboard.png', png)
    return None


def _coerce_bitmap(raw, ext):
    payload, kind = wenju_format.image_bytes(raw)
    if kind in ('png', 'jpg', 'gif', 'bmp'):
        return ('clipboard.%s' % kind, payload)
    if raw:
        return ('clipboard.%s' % ext, bytes(raw) if not isinstance(raw, bytes) else raw)
    return None


def _qt_image_png(mime):
    getter = getattr(mime, 'imageData', None)
    if not getter:
        return b''
    try:
        image = getter()
    except Exception:
        return b''
    if image is None or (hasattr(image, 'isNull') and image.isNull()):
        return b''
    save = getattr(image, 'save', None)
    if not save:
        return b''
    try:
        import qt_compat
        core, _gui, _widgets = qt_compat.load()
        buf = core.QBuffer()
        buf.open(core.QIODevice.WriteOnly)
        if not save(buf, b'PNG'):
            return b''
        return bytes(buf.data())
    except Exception:
        return b''


def _meta_from_mime(mime):
    for name, ext in META_MIMES:
        raw = _first_bytes(mime, (name,))
        if raw:
            return _coerce_meta(raw, ext)
    formats = getattr(mime, 'formats', None)
    if not formats:
        return None
    try:
        names = list(formats())
    except Exception:
        return None
    for name in names:
        low = str(name).lower()
        if 'metafile' not in low and '/emf' not in low and '/wmf' not in low and not low.endswith('emf') and not low.endswith('wmf'):
            continue
        raw = _first_bytes(mime, (name,))
        if not raw:
            continue
        ext = 'wmf' if ('wmf' in low or 'metafilepict' in low) else 'emf'
        found = _coerce_meta(raw, ext)
        if found:
            return found
    return None


def _coerce_meta(raw, ext):
    cleaned, kind = wenju_format.clipboard_metafile(raw)
    if kind:
        return ('clipboard.%s' % kind, cleaned)
    if raw:
        return ('clipboard.%s' % ext, bytes(raw) if not isinstance(raw, bytes) else raw)
    return None


def read_clipboard(progress=None):
    import qt_compat
    _core, gui, widgets = qt_compat.load()
    app = gui.QGuiApplication.instance() or widgets.QApplication.instance()
    if app is None:
        raise RuntimeError('Qt 应用尚未启动')
    return document_from_mime(app.clipboard().mimeData(), progress)
