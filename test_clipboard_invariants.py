"""Bounded check of the clipboard-import invariants against the real parser.

Run: python -m unittest test_clipboard_invariants -v

The bound is every sequence of at most two blocks. Each block is one of:
a paragraph, a PNG, an EMF, an empty table, a table whose cell holds a PNG,
or a table whose cell holds an EMF. Each sequence is imported the way a
Word paste arrives: HTML file:// pictures plus RTF \\bin pictures of the
same bytes, in the same order. The check then looks at the document that
from_docx reads back.
"""
import ast
import hashlib
import os
import struct
import tempfile
import time
import tracemalloc
import unittest
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parent
import sys
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'core'))
import clipboard_import as clip
import wenju_format as fmt

SYMBOLS = (
    ('p',),
    ('img', 'png'),
    ('img', 'emf'),
    ('table', None),
    ('table', 'png'),
    ('table', 'emf'),
)
_PNG = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
    b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf'
    b'\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82'
)
_BLIP = {'png': 'pngblip', 'jpg': 'jpegblip', 'emf': 'emfblip', 'wmf': 'wmetafile'}


def fat_picture(kind, serial):
    size = 1024 * 1024
    blob = bytearray(picture(kind, serial))
    if len(blob) >= size:
        return bytes(blob)
    blob.extend(b'\x00' * (size - len(blob)))
    if kind == 'emf':
        struct.pack_into('<I', blob, 48, size)
    return bytes(blob)


def picture(kind, serial):
    mark = struct.pack('>I', int(serial) + 1)
    if kind == 'png':
        return _PNG + mark
    if kind == 'jpg':
        return b'\xff\xd8\xff' + mark + b'\xff\xd9'
    if kind == 'emf':
        data = bytearray(88)
        data[0:4] = b'\x01\x00\x00\x00'
        struct.pack_into('<I', data, 4, 88)
        data[40:44] = b' EMF'
        struct.pack_into('<I', data, 48, 88)
        data[52:56] = mark
        return bytes(data)
    if kind == 'wmf':
        words = 12
        data = bytearray(words * 2)
        data[0:4] = b'\x01\x00\x09\x00'
        struct.pack_into('<I', data, 6, words)
        data[16:20] = mark
        return bytes(data)
    raise ValueError(kind)


def expand(sequence):
    items = []
    serial = 0
    for symbol in sequence:
        if symbol[0] == 'p':
            items.append(('p', '段%d' % len(items)))
            continue
        if symbol[0] == 'img':
            items.append(('img', symbol[1], picture(symbol[1], serial)))
            serial += 1
            continue
        pics = []
        if symbol[1]:
            pics.append((symbol[1], picture(symbol[1], serial)))
            serial += 1
        items.append(('table', '格%d' % len(items), pics))
    return items


def _rtf_text(text):
    parts = []
    for char in text:
        code = ord(char)
        if char in '\\{}':
            parts.append('\\' + char)
        elif code < 128:
            parts.append(char)
        else:
            parts.append('\\u%d?' % code)
    return ''.join(parts)


def _pict(kind, blob):
    return '{\\pict\\%s\\bin%d %s}' % (_BLIP[kind], len(blob), blob.decode('latin1'))


def _write_html(items, folder):
    parts = ['<html><body>']
    number = 0
    for item in items:
        if item[0] == 'p':
            parts.append('<p>%s</p>' % item[1])
        elif item[0] == 'break':
            parts.append('<p style="page-break-after:always">%s</p>' % item[1])
        elif item[0] == 'img':
            path = folder / ('i%d.%s' % (number, item[1]))
            path.write_bytes(item[2])
            parts.append('<img src="%s" width="96" height="96">' % path.as_uri())
            number += 1
        else:
            parts.append('<table><tr><td>%s' % item[1])
            for kind, blob in item[2]:
                path = folder / ('i%d.%s' % (number, kind))
                path.write_bytes(blob)
                parts.append('<img src="%s" width="96" height="96">' % path.as_uri())
                number += 1
            parts.append('</td></tr></table>')
    parts.append('</body></html>')
    return ''.join(parts).encode('utf-8')


def _write_rtf(items):
    parts = ['{\\rtf1\\ansi ']
    for item in items:
        if item[0] == 'p':
            parts.append(_rtf_text(item[1]) + '\\par ')
        elif item[0] == 'break':
            parts.append(_rtf_text(item[1]) + '\\page ')
        elif item[0] == 'img':
            parts.append(_pict(item[1], item[2]) + '\\par ')
        else:
            parts.append('\\trowd\\cellx3000\\intbl ' + _rtf_text(item[1]))
            for kind, blob in item[2]:
                parts.append(_pict(kind, blob))
            parts.append('\\cell\\row ')
    parts.append('}')
    return ''.join(parts)


def _digest(blob):
    return hashlib.sha256(blob).digest()


def _spine_hashes(doc):
    spine = []
    for item in actual_spine(doc):
        kind = item[0]
        if kind == 'image':
            spine.append(('image', _digest(item[1])))
        elif kind == 'table':
            cells = []
            for text, blobs in item[1]:
                cells.append((text, tuple(_digest(blob) for blob in blobs)))
            spine.append(('table', tuple(cells)))
        elif kind == 'text':
            spine.append(('text', item[1]))
        else:
            spine.append((kind,))
    return spine


def _scale_inputs(folder):
    html_parts = ['<html><body>']
    rtf_parts = ['{\\rtf1\\ansi ']
    spine = []
    serial = 0
    number = 0
    kinds = ('png', 'jpg', 'emf')
    for page in range(200):
        outer = kinds[page % 3]
        inner = kinds[(page + 1) % 3]
        html_parts.append('<p style="page-break-after:always">页%d</p>' % page)
        rtf_parts.append(_rtf_text('页%d' % page) + '\\page ')
        spine.append(('text', '页%d' % page))
        spine.append(('break',))
        blob = fat_picture(outer, serial)
        serial += 1
        path = folder / ('i%d.%s' % (number, outer))
        path.write_bytes(blob)
        html_parts.append('<img src="%s" width="96" height="96">' % path.as_uri())
        rtf_parts.append(_pict(outer, blob) + '\\par ')
        spine.append(('image', _digest(blob)))
        number += 1
        blob = fat_picture(inner, serial)
        serial += 1
        path = folder / ('i%d.%s' % (number, inner))
        path.write_bytes(blob)
        html_parts.append('<table><tr><td>格%d' % page)
        html_parts.append('<img src="%s" width="96" height="96">' % path.as_uri())
        html_parts.append('</td></tr></table>')
        rtf_parts.append('\\trowd\\cellx3000\\intbl ' + _rtf_text('格%d' % page))
        rtf_parts.append(_pict(inner, blob))
        rtf_parts.append('\\cell\\row ')
        spine.append(('table', (('格%d' % page, (_digest(blob),)),)))
        number += 1
    html_parts.append('</body></html>')
    rtf_parts.append('}')
    return ''.join(html_parts).encode('utf-8'), ''.join(rtf_parts), spine


def expected_spine(items):
    spine = []
    for item in items:
        if item[0] in ('p', 'break'):
            spine.append(('text', item[1]))
            if item[0] == 'break':
                spine.append(('break',))
        elif item[0] == 'img':
            spine.append(('image', item[2]))
        else:
            spine.append(('table', ((item[1], tuple(blob for _kind, blob in item[2])),)))
    return spine


def actual_spine(doc):
    spine = []
    for block in doc.blocks:
        kind = block.get('type')
        if kind in ('paragraph', 'heading'):
            text = ''.join(run.get('text', '') for run in block.get('runs') or []).strip()
            if text:
                spine.append(('text', text))
        elif kind == 'pagebreak':
            spine.append(('break',))
        elif kind == 'image':
            spine.append(('image', doc.assets[block['asset']]))
        elif kind == 'table':
            cells = []
            for row in block.get('rows') or []:
                for cell in row:
                    if not isinstance(cell, dict) or cell.get('covered'):
                        continue
                    text = ''.join(run.get('text', '') for run in cell.get('runs') or []).strip()
                    blobs = tuple(doc.assets[image['asset']] for image in cell.get('images') or [])
                    cells.append((text, blobs))
            spine.append(('table', tuple(cells)))
    return spine


def import_parts(items, folder, channel):
    html = _write_html(items, folder) if channel != 'rtf' else None
    rtf = _write_rtf(items) if channel != 'html' else None
    return clip.document_from_parts(html=html, rtf=rtf)


def sequences(length):
    return product(SYMBOLS, repeat=length)


class ClipboardInvariantTests(unittest.TestCase):
    def test_picture_bytes_are_recognized(self):
        for kind in ('png', 'jpg', 'emf', 'wmf'):
            blob = picture(kind, 4)
            payload, found = fmt.image_bytes(blob)
            self.assertEqual(found, kind)
            self.assertEqual(payload, blob)

    def test_every_short_document_keeps_pictures_once_and_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for length in (1, 2):
                for sequence in sequences(length):
                    items = expand(sequence)
                    doc = import_parts(items, folder, 'both')
                    self.assertEqual(fmt.validate(doc), [])
                    self.assertEqual(actual_spine(doc), expected_spine(items))
                    expected_blobs = []
                    for item in items:
                        if item[0] == 'img':
                            expected_blobs.append(item[2])
                        elif item[0] == 'table':
                            expected_blobs.extend(blob for _kind, blob in item[2])
                    self.assertEqual(sorted(doc.assets.values()), sorted(expected_blobs))

    def test_html_only_and_rtf_only_keep_the_same_spine(self):
        items = expand((('p',), ('img', 'png'), ('table', 'emf'), ('img', 'emf'), ('table', None)))
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for channel in ('html', 'rtf'):
                doc = import_parts(items, folder, channel)
                self.assertEqual(actual_spine(doc), expected_spine(items), channel)

    def test_emf_and_wmf_replace_the_png_preview_without_duplicating_it(self):
        for kind in ('emf', 'wmf'):
            meta = picture(kind, 9)
            preview = picture('png', 9)
            with tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                path = folder / 'preview.png'
                path.write_bytes(preview)
                html = ('<html><body><p>前文</p><img src="%s" width="96" height="96"><p>后文</p></body></html>' % path.as_uri()).encode('utf-8')
                rtf = '{\\rtf1\\ansi 前文\\par %s\\par 后文\\par}' % _pict(kind, meta)
                doc = clip.document_from_parts(html=html, rtf=rtf)
            self.assertEqual(actual_spine(doc), [
                ('text', '前文'),
                ('image', meta),
                ('text', '后文'),
            ])
            self.assertNotIn(preview, doc.assets.values())
            self.assertEqual(list(doc.assets.values()), [meta])

    def test_bin_payload_keeps_braces_and_the_text_after_it(self):
        blob = picture('png', 11) + b'{}\\'
        rtf = '{\\rtf1\\ansi before %s after\\par}' % _pict('png', blob)
        doc = clip.document_from_parts(rtf=rtf)
        self.assertEqual(actual_spine(doc), [('text', 'before'), ('image', blob), ('text', 'after')])

    def test_a_picture_stays_in_its_own_cell(self):
        left = picture('png', 1)
        right = picture('emf', 2)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            left_path = folder / 'left.png'
            right_path = folder / 'right.emf'
            left_path.write_bytes(left)
            right_path.write_bytes(right)
            html = (
                '<html><body><table><tr>'
                '<td>左<img src="%s" width="96" height="96"></td>'
                '<td>右<img src="%s" width="96" height="96"></td>'
                '</tr></table></body></html>'
            ) % (left_path.as_uri(), right_path.as_uri())
            rtf = (
                '{\\rtf1\\ansi\\trowd\\cellx3000\\cellx6000\\intbl 左%s\\cell 右%s\\cell\\row}'
            ) % (_pict('png', left), _pict('emf', right))
            doc = clip.document_from_parts(html=html.encode('utf-8'), rtf=rtf)
        table = next(block for block in doc.blocks if block['type'] == 'table')
        self.assertEqual(
            ''.join(run.get('text', '') for run in table['rows'][0][0]['runs']).strip(), '左')
        self.assertEqual(
            ''.join(run.get('text', '') for run in table['rows'][0][1]['runs']).strip(), '右')
        self.assertEqual(doc.assets[table['rows'][0][0]['images'][0]['asset']], left)
        self.assertEqual(doc.assets[table['rows'][0][1]['images'][0]['asset']], right)
        self.assertFalse(any(block['type'] == 'image' for block in doc.blocks))

    def test_a_lone_mime_image_is_used_only_when_the_document_has_none(self):
        lone = picture('png', 3)
        items = expand((('img', 'emf'),))
        with tempfile.TemporaryDirectory() as tmp:
            present = import_parts(items, Path(tmp), 'html')
        # Rebuild with the extra mime image by calling the parts entry directly.
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            html = _write_html(items, folder)
            crowded = clip.document_from_parts(html=html, images={'clipboard.png': lone})
            empty = clip.document_from_parts(plain='只有字', images={'clipboard.png': lone})
        self.assertEqual(actual_spine(crowded), actual_spine(present))
        self.assertEqual(actual_spine(empty), [('text', '只有字'), ('image', lone)])

    def test_reading_does_not_save_or_leave_a_file(self):
        calls = []
        real_save = fmt.save

        def record_save(*args, **kwargs):
            calls.append(args)
            raise AssertionError('save during read')

        fmt.save = record_save
        clip.wenju_format.save = record_save
        watch = Path(tempfile.mkdtemp(prefix='wenju-out-'))
        previous = os.getcwd()
        try:
            os.chdir(str(watch))
            with tempfile.TemporaryDirectory() as tmp:
                doc = import_parts(expand((('img', 'emf'), ('table', 'png'))), Path(tmp), 'both')
            self.assertTrue(doc.assets)
        finally:
            os.chdir(previous)
            fmt.save = real_save
            clip.wenju_format.save = real_save
        self.assertEqual(calls, [])
        self.assertEqual(list(watch.iterdir()), [])
        self.assertFalse(list(Path(tempfile.gettempdir()).glob('wenju-clip-*')))
        watch.rmdir()

    def test_only_convert_calls_save(self):
        app_tree = ast.parse((ROOT / 'app.py').read_text(encoding='utf-8'))
        functions = {}
        for node in ast.walk(app_tree):
            if isinstance(node, ast.FunctionDef):
                functions[node.name] = node

        def calls(node):
            found = set()
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                func = child.func
                if isinstance(func, ast.Attribute):
                    found.add(func.attr)
                elif isinstance(func, ast.Name):
                    found.add(func.id)
            return found

        quiet = ('importClipboard', '_clip_ready', '_clip_failed', 'setConvertTarget', 'setClipboardBrush')
        for name in quiet:
            hit = calls(functions[name]) & {'save', 'to_docx', '_write_clipboard', '_clipboard_item'}
            self.assertFalse(hit, name)
        self.assertIn('save', calls(functions['_clipboard_item']))
        callers = [name for name, node in functions.items() if '_clipboard_item' in calls(node)]
        self.assertEqual(callers, ['_begin_batch'])
        batch = ast.get_source_segment((ROOT / 'app.py').read_text(encoding='utf-8'), functions['_begin_batch'])
        head, _, tail = batch.partition("if action=='convert':")
        self.assertNotIn('_clipboard_item', head)
        self.assertIn('_clipboard_item', tail)
        parser = ast.parse((ROOT / 'core' / 'clipboard_import.py').read_text(encoding='utf-8'))
        for node in ast.walk(parser):
            if isinstance(node, ast.FunctionDef) and node.name in ('document_from_parts', '_through_docx', 'parts_from_mime'):
                self.assertNotIn('save', calls(node), node.name)

    def test_two_hundred_pages_reconcile(self):
        progress = []
        with tempfile.TemporaryDirectory() as tmp:
            html, rtf, expected = _scale_inputs(Path(tmp))
            tracemalloc.start()
            started = time.perf_counter()
            doc = clip.document_from_parts(html=html, rtf=rtf, progress=progress.append)
            elapsed = time.perf_counter() - started
            _current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
        rss = _proc_kib('VmRSS')
        hwm = _proc_kib('VmHWM')
        self.assertEqual(_spine_hashes(doc), expected)
        self.assertEqual(fmt.validate(doc), [])
        self.assertEqual(progress[-1], 100)
        self.assertLess(elapsed, 120)
        self.assertLess(peak, 4 * 1024 * 1024 * 1024)
        print(
            'SCALE pages=200 images=400 bytes_each=1048576 tables=200 seconds=%.2f tracemalloc_mib=%.1f rss_mib=%.1f hwm_mib=%.1f'
            % (elapsed, peak / (1024 * 1024), rss / 1024, hwm / 1024)
        )


def _proc_kib(name):
    for line in Path('/proc/self/status').read_text(encoding='utf-8').splitlines():
        if line.startswith(name + ':'):
            return int(line.split()[1])
    return 0


if __name__ == '__main__':
    unittest.main()
