import base64
import re
from html.parser import HTMLParser

import wenju_format

HTML_MIMES = ('text/html',)
RTF_MIMES = ('text/rtf', 'application/rtf', 'application/x-rtf', 'Rich Text Format')
PLAIN_MIMES = ('text/plain',)
IMAGE_MIMES = (('image/png', 'png'), ('image/jpeg', 'jpg'), ('image/jpg', 'jpg'), ('image/bmp', 'bmp'))
HTML_FONT_PT = {1: 8, 2: 10, 3: 12, 4: 14, 5: 18, 6: 24, 7: 36}
_SKIP_RTF = {
    'colortbl', 'info', 'header', 'footer', 'headerf', 'footerf', 'headerl', 'footerr',
    'footnote', 'fldinst', 'field', 'generator', 'xmlnstbl', 'colorschememapping',
    'latentstyles', 'datastore', 'themedata', 'listtable', 'listoverridetable', 'revtbl',
    'rsidtbl', 'mmath', 'object', 'objdata', 'background', 'pn', 'filetbl', 'pgptbl',
    'operator', 'author', 'title', 'subject', 'doccomm', 'comment', 'creatim', 'revtim',
}
_DEST = _SKIP_RTF | {'rtf', 'fonttbl', 'stylesheet', 'pict'}
_GENERICS = {'serif', 'sans-serif', 'monospace', 'cursive', 'fantasy'}


class ClipboardEmpty(Exception):
    pass


def _progress(callback, value):
    if callback:
        callback(int(value))


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
    try:
        return raw.decode(encoding)
    except UnicodeDecodeError:
        return raw.decode('gb18030', 'replace')


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
        elif key == 'page-break-before' and 'always' in value.lower():
            found['page'] = True
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

    def _style(self):
        merged = {}
        for item in self.stack:
            for key in ('font', 'size', 'bold', 'italic'):
                if key in item:
                    merged[key] = item[key]
        return merged

    def _add(self, text):
        if not text:
            return
        run = {'text': text}
        run.update(self._style())
        if self.runs and {k: v for k, v in self.runs[-1].items() if k != 'text'} == {k: v for k, v in run.items() if k != 'text'}:
            self.runs[-1]['text'] += text
            return
        self.runs.append(run)

    def _flush(self):
        runs = [run for run in self.runs if run.get('text')]
        self.runs = []
        kind = self.kind
        self.kind = None
        if not runs:
            return
        if self.cell is not None:
            if self.cell['runs']:
                self.cell['runs'].append({'text': '\n'})
            self.cell['runs'].extend(runs)
            return
        if kind and kind[0] == 'h':
            self.blocks.append({'type': 'heading', 'level': kind[1], 'runs': runs})
            return
        style = kind[1] if kind else 'body'
        if style == 'toc' and not self.toc_done:
            self.blocks.append({'type': 'toc'})
            self.toc_done = True
        self.blocks.append({'type': 'paragraph', 'style': style, 'runs': runs})

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attr = {key.lower(): value or '' for key, value in attrs}
        if tag in ('script', 'style'):
            self.ignore += 1
            return
        if self.ignore:
            return
        css = _css(attr.get('style'))
        if tag == 'br':
            if css.get('page') and self.cell is None and self.table is None:
                self._flush()
                self.blocks.append({'type': 'pagebreak'})
            else:
                self._add('\n')
            return
        if tag == 'img':
            self._flush()
            image = self._image(attr)
            if image is None and src_present(attr):
                width = int(attr['width']) if attr.get('width', '').isdigit() else 0
                height = int(attr['height']) if attr.get('height', '').isdigit() else 0
                image = {'type': 'image', 'asset': '', 'w': width, 'h': height}
            if image and self.table is not None:
                self.later_images.append(image)
            elif image:
                self.blocks.append(image)
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
            self.stack.append({key: css[key] for key in ('font', 'size', 'bold', 'italic') if key in css})
            return
        if css.get('page') and self.cell is None and self.table is None:
            self._flush()
            self.blocks.append({'type': 'pagebreak'})
        else:
            self._flush()
        class_name = attr.get('class', '')
        if tag[0] == 'h' and tag[1:].isdigit():
            self.kind = ('h', int(tag[1:]))
        elif _is_toc(class_name, css.get('style_name')):
            self.kind = ('p', 'toc')
        else:
            level = css.get('outline') or _level_from_class(class_name) or _level_from_name(css.get('style_name'))
            self.kind = ('h', level) if level else ('p', 'body')
        self.stack.append({key: css[key] for key in ('font', 'size', 'bold', 'italic') if key in css})

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ('script', 'style'):
            self.ignore = max(0, self.ignore - 1)
            return
        if self.ignore:
            return
        if tag in ('b', 'strong', 'i', 'em', 'font', 'span', 'a', 'div', 'p', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            if tag in ('p', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
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
            rows, merges = wenju_format.pack_grid(self.table['grid'])
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
            self.blocks.extend(self.later_images)
            self.later_images = []
            self.table = None

    def handle_data(self, data):
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
        table['grid'][(row, col)] = {'runs': self.cell['runs'], 'colspan': colspan, 'rowspan': rowspan}
        for dr in range(rowspan):
            for dc in range(colspan):
                if dr == 0 and dc == 0:
                    continue
                table['grid'][(row + dr, col + dc)] = {'covered': True, 'runs': []}
        table['cursor'] = col + colspan

    def _image(self, attr):
        src = attr.get('src') or ''
        width = int(attr['width']) if attr.get('width', '').isdigit() else 0
        height = int(attr['height']) if attr.get('height', '').isdigit() else 0
        match = re.match(r'data:image/(png|jpeg|jpg|bmp);base64,(.+)', src, re.I | re.S)
        if not match:
            return None
        kind = match.group(1).lower()
        ext = 'jpg' if kind in ('jpeg', 'jpg') else ('bmp' if kind == 'bmp' else 'png')
        try:
            data = base64.b64decode(re.sub(r'\s+', '', match.group(2)))
        except Exception:
            return None
        self.images += 1
        asset = 'assets/image%d.%s' % (self.images, ext)
        self.assets[asset] = data
        return {'type': 'image', 'asset': asset, 'w': width, 'h': height}

    def close_doc(self):
        self._flush()
        if self.table is not None:
            rows, merges = wenju_format.pack_grid(self.table['grid'])
            if rows:
                self.blocks.append({'type': 'table', 'rows': rows, 'merges': merges})
            self.blocks.extend(self.later_images)


def parse_html(raw, progress=None):
    _progress(progress, 30)
    parser = _HtmlDoc()
    parser.feed(html_fragment(raw))
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
                body.append(('text', plain()))
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
        if i < n and text[i] == ' ':
            i += 1
        return ('word', word, number)

    def plain():
        nonlocal i
        start = i
        while i < n and text[i] not in '\\{}\r\n':
            i += 1
        return text[start:i]

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
        self.fmt = {'bold': False, 'italic': False, 'font': None, 'size': None, 'uc': 1}
        self.para = {'outline': None, 'style': None, 'intbl': False}
        self.runs = []
        self.table_rows = []
        self.in_row = False
        self.row_cells = []
        self.row_defs = []
        self.cur_def = {}
        self.skip_chars = 0

    def parse(self, raw, progress=None):
        _progress(progress, 30)
        tokens = _tokens(_rtf_string(raw))
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
        if tokens and tokens[0][0] == 'word' and tokens[0][1] == '*':
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
        hex_text = []

        def walk(items):
            nonlocal blip, width, height
            for token in items:
                if token[0] == 'word' and token[1] in ('pngblip', 'jpegblip', 'wbitmap', 'dibitmap'):
                    blip = token[1]
                elif token[0] == 'word' and token[1] == 'picwgoal' and token[2]:
                    width = int(token[2] / 15)
                elif token[0] == 'word' and token[1] == 'pichgoal' and token[2]:
                    height = int(token[2] / 15)
                elif token[0] == 'text':
                    hex_text.append(token[1])
                elif token[0] == 'group':
                    walk(token[1])

        walk(tokens)
        digits = re.sub(r'[^0-9A-Fa-f]', '', ''.join(hex_text))
        if len(digits) < 2 or not blip:
            return
        if len(digits) % 2:
            digits = digits[:-1]
        try:
            data = bytes.fromhex(digits)
        except ValueError:
            return
        self.images += 1
        if blip == 'jpegblip':
            ext = 'jpg'
        elif blip in ('wbitmap', 'dibitmap') or data[:2] == b'BM':
            ext = 'bmp'
        else:
            ext = 'png'
        asset = 'assets/rtf%d.%s' % (self.images, ext)
        self.assets[asset] = data
        image = {'type': 'image', 'asset': asset, 'w': width or 0, 'h': height or 0}
        if self.in_row:
            self.pending_images.append(image)
            return
        self._finish_para_before_image()
        self.blocks.append(image)

    def _content(self, tokens):
        pending = bytearray()

        def flush_bytes():
            if not pending:
                return
            self._add(pending.decode(self._encoding(), 'replace'))
            pending[:] = b''

        for token in tokens:
            kind = token[0]
            if kind == 'group':
                flush_bytes()
                saved = (dict(self.fmt), dict(self.para), self.skip_chars)
                self._walk(token[1])
                self.fmt, self.para, self.skip_chars = saved
                continue
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
            run['size'] = self.fmt['size']
        number = self.fmt.get('font')
        font = self.fonts.get(self.deff if number is None else number)
        if font and font.get('name'):
            run['font'] = font['name']
        if self.runs:
            prev = self.runs[-1]
            if {k: prev.get(k) for k in ('bold', 'italic', 'size', 'font')} == {k: run.get(k) for k in ('bold', 'italic', 'size', 'font')}:
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
                if {k: prev.get(k) for k in ('bold', 'italic', 'size', 'font')} == {k: item.get(k) for k in ('bold', 'italic', 'size', 'font')}:
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
            if self.table_rows and not self.in_row:
                self._finish_table()
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
            if self.in_row and self.row_cells:
                self.row_defs = []
                self.cur_def = {}
            else:
                self.in_row = True
                self.row_cells = []
                self.row_defs = []
                self.cur_def = {}
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
        index = len(self.row_cells)
        spec = self.row_defs[index] if index < len(self.row_defs) else {}
        self.row_cells.append({
            'runs': self._clean(self.runs),
            'vmerge': spec.get('vmerge'),
            'hmerge': spec.get('hmerge'),
        })
        self.runs = []

    def _finish_row(self):
        if self.runs:
            self._capture_cell()
        expanded = []
        for cell in self.row_cells:
            if cell.get('hmerge') == 'continue' and expanded:
                expanded[-1]['colspan'] = int(expanded[-1].get('colspan') or 1) + 1
                continue
            item = {'runs': cell.get('runs') or [], 'colspan': 1, 'vmerge': cell.get('vmerge')}
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
        rows, merges = wenju_format.pack_grid(grid)
        if rows:
            self.blocks.append({'type': 'table', 'rows': rows, 'merges': merges})
        self.table_rows = []
        if self.pending_images:
            self.blocks.extend(self.pending_images)
            self.pending_images = []


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


def document_from_parts(html=None, rtf=None, plain=None, images=None, progress=None):
    _progress(progress, 5)
    images = dict(images or {})
    blocks = []
    assets = {}
    if _has_bytes(html):
        blocks, assets = parse_html(html, progress)
    if _nonempty(blocks, assets):
        if _has_bytes(rtf) and not any(block.get('type') == 'image' and block.get('asset') for block in blocks):
            blocks, assets = _merge_rtf_images(blocks, assets, rtf)
    elif _has_bytes(rtf):
        blocks, assets = parse_rtf(rtf, progress)
    if not _nonempty(blocks, assets) and plain and str(plain).strip():
        blocks = parse_plain(plain, progress)
        assets = {}
    blocks = [block for block in blocks if not (block.get('type') == 'image' and not block.get('asset'))]
    if images and not any(block.get('type') == 'image' for block in blocks):
        assets.update(images)
        for name in images:
            blocks.append({'type': 'image', 'asset': name, 'w': 0, 'h': 0})
    if not _nonempty(blocks, assets):
        raise ClipboardEmpty('剪贴板里没有可导入的文字、表格或图片')
    _progress(progress, 100)
    return wenju_format.WenjuDoc(blocks, {'source': 'clipboard', 'mode': 'original'}, assets)


def document_from_mime(mime, progress=None):
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
    for mime_name, ext in IMAGE_MIMES:
        raw = _first_bytes(mime, (mime_name,))
        if raw:
            images['assets/clipboard.%s' % ext] = raw
            break
    return document_from_parts(html, rtf, plain, images, progress)


def read_clipboard(progress=None):
    import qt_compat
    _core, gui, widgets = qt_compat.load()
    app = gui.QGuiApplication.instance() or widgets.QApplication.instance()
    if app is None:
        raise RuntimeError('Qt 应用尚未启动')
    return document_from_mime(app.clipboard().mimeData(), progress)
