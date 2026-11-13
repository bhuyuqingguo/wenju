import ast
import base64
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
import sys
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'core'))
import clipboard_import as clip
import wenju_format as fmt

SAMPLES = ROOT / 'core' / '样例' / 'clipboard'


def text_of(doc):
    parts = []
    for block in doc.blocks:
        kind = block.get('type')
        if kind in ('heading', 'paragraph'):
            parts.append(''.join(run.get('text', '') for run in block.get('runs') or []))
        elif kind == 'table':
            for row in block.get('rows') or []:
                for cell in row:
                    if cell.get('covered'):
                        continue
                    parts.append(''.join(run.get('text', '') for run in cell.get('runs') or []))
    return '\n'.join(parts)


def cf_html(payload):
    data = payload if isinstance(payload, bytes) else payload.encode('utf-8')
    template = 'Version:1.0\r\nStartHTML:{s:010d}\r\nEndHTML:{e:010d}\r\nStartFragment:{sf:010d}\r\nEndFragment:{ef:010d}\r\n'
    prefix = template.format(s=0, e=0, sf=0, ef=0).encode('ascii')
    start = len(prefix)
    end = start + len(data)
    prefix = template.format(s=start, e=end, sf=start, ef=end).encode('ascii')
    return prefix + data


class FakeMime(object):
    def __init__(self, formats, html='', text=''):
        self._formats = formats
        self._html = html
        self._text = text

    def hasFormat(self, name):
        return name in self._formats

    def data(self, name):
        return self._formats.get(name, b'')

    def html(self):
        return self._html

    def text(self):
        return self._text


class ClipboardTests(unittest.TestCase):
    def test_py38_syntax(self):
        for name in ('core/wenju_format.py', 'core/clipboard_import.py', 'qt_compat.py'):
            tree = ast.parse((ROOT / name).read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                self.assertFalse(isinstance(node, ast.NamedExpr))
                self.assertFalse(hasattr(ast, 'Match') and isinstance(node, ast.Match))

    def test_wps_html_keeps_structure(self):
        raw = (SAMPLES / 'wps.html').read_bytes()
        doc = clip.document_from_parts(html=cf_html(raw))
        self.assertEqual(fmt.validate(doc), [])
        self.assertEqual(doc.blocks[0]['type'], 'heading')
        self.assertEqual(doc.blocks[0]['level'], 1)
        self.assertEqual(doc.blocks[0]['runs'][0]['text'], '通知标题')
        self.assertEqual(doc.blocks[0]['runs'][0]['eastAsia'], '黑体')
        self.assertEqual(doc.blocks[0]['runs'][0]['size_pt'], 22)
        self.assertTrue(doc.blocks[0]['runs'][0]['bold'])
        self.assertEqual(doc.blocks[1]['runs'][0]['eastAsia'], '仿宋_GB2312')
        self.assertEqual(doc.blocks[1]['runs'][0]['size_pt'], 16)
        self.assertEqual(doc.blocks[2]['type'], 'toc')
        self.assertEqual(doc.blocks[3]['style'], 'toc')
        self.assertEqual(doc.blocks[3]['runs'][0]['text'], '一、事项')
        self.assertEqual(doc.blocks[4]['type'], 'heading')
        self.assertEqual(doc.blocks[4]['level'], 2)
        self.assertEqual(doc.blocks[4]['runs'][0]['eastAsia'], '楷体')
        table = next(block for block in doc.blocks if block['type'] == 'table')
        self.assertEqual(table['merges'], [
            {'row': 0, 'col': 0, 'rowspan': 1, 'colspan': 2},
            {'row': 1, 'col': 0, 'rowspan': 2, 'colspan': 1},
        ])
        self.assertEqual(table['rows'][0][0]['runs'][0]['text'], '表头')
        self.assertTrue(table['rows'][0][1]['covered'])
        self.assertEqual(table['rows'][1][0]['runs'][0]['text'], '左')
        self.assertEqual(table['rows'][1][1]['runs'][0]['text'], '右上')
        self.assertTrue(table['rows'][2][0]['covered'])
        self.assertEqual(table['rows'][2][1]['runs'][0]['text'], '右下')
        image = next(block for block in doc.blocks if block['type'] == 'image')
        self.assertEqual(image['w'], 7.5)
        self.assertEqual(image['h'], 6)
        self.assertTrue(doc.assets[image['asset']].startswith(b'\x89PNG'))
        self.assertIn({'type': 'pagebreak'}, doc.blocks)
        self.assertIn('第二页', text_of(doc))

    def test_yozo_html_gb18030(self):
        doc = clip.document_from_parts(html=(SAMPLES / 'yozo.html').read_bytes())
        self.assertEqual(fmt.validate(doc), [])
        self.assertEqual(doc.blocks[0]['type'], 'heading')
        self.assertEqual(doc.blocks[0]['level'], 2)
        self.assertEqual(doc.blocks[0]['runs'][0]['text'], '永中标题')
        self.assertEqual(doc.blocks[0]['runs'][0]['eastAsia'], '黑体')
        self.assertEqual(doc.blocks[0]['runs'][0]['size_pt'], 18)
        self.assertEqual(doc.blocks[1]['runs'][0]['eastAsia'], '宋体')
        self.assertEqual(doc.blocks[1]['runs'][0]['size_pt'], 12)
        table = next(block for block in doc.blocks if block['type'] == 'table')
        self.assertEqual(table['rows'][0][0]['runs'][0]['text'], '合并列')
        self.assertEqual(table['merges'][0]['colspan'], 2)
        self.assertEqual(table['rows'][1][0]['runs'][0]['text'], '甲')
        self.assertEqual(table['rows'][1][1]['runs'][0]['text'], '乙')
        self.assertIn({'type': 'pagebreak'}, doc.blocks)
        self.assertIn('下一页', text_of(doc))

    def test_wps_rtf(self):
        doc = clip.document_from_parts(rtf=(SAMPLES / 'wps.rtf').read_bytes())
        self.assertEqual(fmt.validate(doc), [])
        self.assertEqual(doc.blocks[0]['type'], 'heading')
        self.assertEqual(doc.blocks[0]['level'], 1)
        run = doc.blocks[0]['runs'][0]
        self.assertEqual(run['text'], '通知标题')
        self.assertEqual(run['eastAsia'], '黑体')
        self.assertEqual(run['size_pt'], 22)
        self.assertTrue(run['bold'])
        self.assertEqual(doc.blocks[1]['runs'][0]['text'], '正文第一段')
        self.assertEqual(doc.blocks[1]['runs'][0]['eastAsia'], '宋体')
        self.assertEqual(doc.blocks[1]['runs'][0]['size_pt'], 16)
        self.assertNotIn('bold', doc.blocks[1]['runs'][0])
        table = next(block for block in doc.blocks if block['type'] == 'table')
        self.assertEqual(table['rows'][0][0]['runs'][0]['text'], '表头')
        self.assertEqual(table['merges'][0]['colspan'], 2)
        self.assertEqual(table['rows'][1][0]['runs'][0]['text'], '左')
        self.assertEqual(table['rows'][1][1]['runs'][0]['text'], '右上')
        self.assertEqual(table['rows'][2][1]['runs'][0]['text'], '右下')
        self.assertTrue(any(item['rowspan'] == 2 for item in table['merges']))
        self.assertIn({'type': 'pagebreak'}, doc.blocks)
        self.assertEqual(doc.blocks[-1]['runs'][0]['text'], '第二页')

    def test_yozo_rtf_stylesheet_heading(self):
        doc = clip.document_from_parts(rtf=(SAMPLES / 'yozo.rtf').read_bytes())
        self.assertEqual(doc.blocks[0]['level'], 1)
        self.assertEqual(doc.blocks[0]['runs'][0]['text'], '永中标题')
        self.assertEqual(doc.blocks[0]['runs'][0]['eastAsia'], '黑体')
        self.assertEqual(doc.blocks[0]['runs'][0]['size_pt'], 18)
        self.assertEqual(doc.blocks[1]['runs'][0]['text'], '永中正文')
        self.assertEqual(doc.blocks[1]['runs'][0]['eastAsia'], '宋体')
        table = doc.blocks[2]
        self.assertEqual(table['rows'][0][0]['runs'][0]['text'], '甲')
        self.assertEqual(table['rows'][0][1]['runs'][0]['text'], '乙')
        self.assertEqual(sorted((item['row'], item['col'], item['rowspan']) for item in table['merges']), [(0, 0, 2), (0, 1, 2)])
        self.assertTrue(table['rows'][1][0]['covered'])
        self.assertTrue(table['rows'][1][1]['covered'])

    def test_rtf_pict(self):
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg==')
        rtf = r'{\rtf1\ansi\pard before\par{\pict\pngblip\picwgoal150\pichgoal300 ' + png.hex() + r'}\par after\par}'
        doc = clip.document_from_parts(rtf=rtf.encode('ascii'))
        image = next(block for block in doc.blocks if block['type'] == 'image')
        self.assertEqual(doc.assets[image['asset']], png)
        self.assertEqual(image['w'], 7.5)
        self.assertEqual(image['h'], 15)
        self.assertIn('before', text_of(doc))
        self.assertIn('after', text_of(doc))

    def test_plain_and_empty(self):
        doc = clip.document_from_parts(plain=(SAMPLES / 'plain.txt').read_text(encoding='utf-8'))
        self.assertEqual([block['runs'][0]['text'] for block in doc.blocks], ['第一段', '第二段'])
        with self.assertRaises(clip.ClipboardEmpty):
            clip.document_from_parts(html=b'<html></html>', plain='  ')

    def test_html_wins_over_rtf_and_plain(self):
        doc = clip.document_from_parts(
            html='<p>来自 HTML</p>',
            rtf=br'{\rtf1\ansi\pard from rtf\par}',
            plain='来自纯文本',
        )
        self.assertIn('来自 HTML', text_of(doc))
        self.assertNotIn('from rtf', text_of(doc))
        self.assertNotIn('来自纯文本', text_of(doc))

    def test_empty_html_falls_through_to_rtf(self):
        doc = clip.document_from_parts(html=b'<html><body></body></html>', rtf=(SAMPLES / 'yozo.rtf').read_bytes(), plain='纯文本')
        self.assertIn('永中标题', text_of(doc))
        self.assertNotIn('纯文本', text_of(doc))

    def test_windows_rtf_mime_and_loose_image(self):
        png = b'\x89PNG\r\n\x1a\nrest'
        mime = FakeMime({
            'Rich Text Format': (SAMPLES / 'wps.rtf').read_bytes(),
            'text/plain': '不要用纯文本'.encode('utf-8'),
            'image/png': png,
        })
        doc = clip.document_from_mime(mime)
        self.assertIn('通知标题', text_of(doc))
        self.assertNotIn('不要用纯文本', text_of(doc))
        image = next(block for block in doc.blocks if block['type'] == 'image')
        self.assertEqual(doc.assets[image['asset']], png)

    def test_nested_html_table_keeps_outer_cells(self):
        html = (
            '<table><tr><td>外左</td><td>前文<table>'
            '<tr><td colspan="2">内头</td></tr><tr><td>内甲</td><td>内乙</td></tr>'
            '</table>后文</td></tr><tr><td>外下</td><td>右下</td></tr></table>'
        )
        doc = clip.document_from_parts(html=html)
        found = text_of(doc)
        for word in ('外左', '前文', '后文', '外下', '右下', '内头', '内甲', '内乙'):
            self.assertIn(word, found)
        inner = [block for block in doc.blocks if block['type'] == 'table'][1]
        self.assertEqual(inner['merges'], [{'row': 0, 'col': 0, 'rowspan': 1, 'colspan': 2}])

    def test_repeated_trowd_keeps_the_row(self):
        rtf = (
            r"{\rtf1\ansi\ansicpg936{\fonttbl{\f0\fnil\fcharset134 \'cb\'ce\'cc\'e5;}}"
            r"\trowd\clmgf\cellx3000\clmrg\cellx6000\intbl\f0 \'b1\'ed\'cd\'b7\cell\cell"
            r"\trowd\clmgf\cellx3000\clmrg\cellx6000\row\pard after\par}"
        )
        doc = clip.document_from_parts(rtf=rtf)
        table = next(block for block in doc.blocks if block['type'] == 'table')
        self.assertEqual(text_of(doc).split('\n')[0], '表头')
        self.assertEqual(table['merges'][0]['colspan'], 2)
        self.assertIn('after', text_of(doc))

    def test_rtf_pict_inside_a_cell_keeps_the_words(self):
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg==')
        rtf = r'{\rtf1\ansi\trowd\cellx3000\intbl before {\pict\pngblip ' + png.hex() + r'} after\cell\row}'
        doc = clip.document_from_parts(rtf=rtf)
        table = next(block for block in doc.blocks if block['type'] == 'table')
        cell = ''.join(run.get('text', '') for run in table['rows'][0][0]['runs'])
        self.assertIn('before', cell)
        self.assertIn('after', cell)
        image = next(block for block in doc.blocks if block['type'] == 'image')
        self.assertEqual(doc.assets[image['asset']], png)

    def test_utf8_rtf_and_unicode_font_names(self):
        raw = '{\\rtf1\\ansi\\ansicpg65001\\deff0{\\fonttbl{\\f0\\fnil\\fcharset134 黑体;}}\\pard\\f0\\fs44 通知\\par}'.encode('utf-8')
        doc = clip.document_from_parts(rtf=raw)
        run = doc.blocks[0]['runs'][0]
        self.assertEqual(run['text'], '通知')
        self.assertEqual(run['eastAsia'], '黑体')
        self.assertEqual(run['size_pt'], 22)
        named = clip.document_from_parts(rtf=(
            r'{\rtf1\ansi\ansicpg936\deff0{\fonttbl{\f0\fnil\fcharset134 \u23435?\u20307?;}}'
            r'\pard\f0\fs32 \u27491?\u25991?\par}'
        ))
        body = named.blocks[0]['runs'][0]
        self.assertEqual(body['text'], '正文')
        self.assertEqual(body['eastAsia'], '宋体')
        self.assertEqual(body['size_pt'], 16)

    def test_browser_divs_keep_paragraphs_and_merged_header(self):
        html = (
            '<html><body>'
            '<div style="font-family: 宋体, sans-serif; font-size: 16px">第一段</div>'
            '<div><b>第二段</b></div>'
            '<table><tr><th colspan="2">表头</th></tr>'
            '<tr><td rowspan="2">左</td><td>右上</td></tr>'
            '<tr><td>右下</td></tr></table>'
            '</body></html>'
        )
        doc = clip.document_from_parts(html=html.encode('utf-8'))
        self.assertEqual(fmt.validate(doc), [])
        self.assertEqual(doc.blocks[0]['runs'][0]['text'], '第一段')
        self.assertEqual(doc.blocks[0]['runs'][0]['eastAsia'], '宋体')
        self.assertEqual(doc.blocks[0]['runs'][0]['size_pt'], 12)
        self.assertEqual(doc.blocks[1]['runs'][0]['text'], '第二段')
        self.assertTrue(doc.blocks[1]['runs'][0]['bold'])
        table = next(block for block in doc.blocks if block['type'] == 'table')
        self.assertEqual(table['rows'][0][0]['runs'][0]['text'], '表头')
        self.assertTrue(table['rows'][0][1]['covered'])
        self.assertEqual(table['merges'][0]['colspan'], 2)
        self.assertEqual(table['rows'][1][0]['runs'][0]['text'], '左')
        self.assertTrue(table['rows'][2][0]['covered'])
        self.assertEqual(table['rows'][2][1]['runs'][0]['text'], '右下')

    def test_font_tag_and_cell_style_keep_point_size(self):
        html = (
            '<p><font face="宋体" style="font-size:16pt">甲</font></p>'
            '<p><font face="宋体" size="3" style="font-size:16pt">乙</font></p>'
            '<table><tr><td style="font-family:黑体;font-size:14pt">丙</td>'
            '<td style="font-family:楷体;font-size:16pt">丁</td></tr></table>'
        )
        doc = clip.document_from_parts(html=html)
        self.assertEqual(doc.blocks[0]['runs'][0], {'text': '甲', 'eastAsia': '宋体', 'ascii': '宋体', 'size_pt': 16})
        self.assertEqual(doc.blocks[1]['runs'][0]['size_pt'], 16)
        table = next(block for block in doc.blocks if block['type'] == 'table')
        self.assertEqual(table['rows'][0][0]['runs'][0], {'text': '丙', 'eastAsia': '黑体', 'ascii': '黑体', 'size_pt': 14})
        self.assertEqual(table['rows'][0][1]['runs'][0], {'text': '丁', 'eastAsia': '楷体', 'ascii': '楷体', 'size_pt': 16})

    def test_file_image_in_html_keeps_the_rtf_pict(self):
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg==')
        html = (SAMPLES / 'wps.html').read_text(encoding='utf-8').replace(
            'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg==',
            'file:///C:/Users/AppData/Local/Temp/wps_clip.png',
        )
        rtf = r'{\rtf1\ansi\pard{\pict\pngblip\picwgoal150\pichgoal120 ' + png.hex() + r'}}'
        doc = clip.document_from_parts(html=html.encode('utf-8'), rtf=rtf.encode('ascii'))
        self.assertIn('通知标题', text_of(doc))
        image = next(block for block in doc.blocks if block['type'] == 'image')
        self.assertEqual(doc.assets[image['asset']], png)
        self.assertGreater(image['w'], 0)

    def test_bmp_data_uri_and_wbitmap(self):
        bmp = b'BM\x1a\x00\x00\x00\x00\x00\x00\x00'
        html = '<p>说明文字</p><img src="data:image/bmp;base64,%s">' % base64.b64encode(bmp).decode('ascii')
        doc = clip.document_from_parts(html=html)
        image = next(block for block in doc.blocks if block['type'] == 'image')
        self.assertEqual(doc.assets[image['asset']], bmp)
        self.assertIn('说明文字', text_of(doc))
        rtf = r'{\rtf1\ansi\pard before\par{\pict\wbitmap0\picwgoal150\pichgoal150 424d1a000000}\par after\par}'
        drawn = clip.document_from_parts(rtf=rtf.encode('ascii'))
        found = next(block for block in drawn.blocks if block['type'] == 'image')
        self.assertTrue(drawn.assets[found['asset']].startswith(b'BM'))
        self.assertIn('before', text_of(drawn))
        self.assertIn('after', text_of(drawn))

    def test_bmp_docx_keeps_the_bitmap(self):
        payload = b'BMrest-of-bitmap'
        doc = clip.document_from_parts(plain='图说', images={'clipboard.bmp': payload})
        folder = Path(tempfile.mkdtemp())
        try:
            docx = folder / 'bmp.docx'
            fmt.to_docx(doc, docx)
            with zipfile.ZipFile(str(docx)) as archive:
                types = archive.read('[Content_Types].xml').decode('utf-8')
                self.assertIn('Extension="bmp"', types)
                self.assertIn('image/bmp', types)
                media = [name for name in archive.namelist() if name.startswith('word/media/')]
                self.assertTrue(media)
                self.assertTrue(archive.read(media[0]).startswith(b'BM'))
        finally:
            shutil.rmtree(str(folder))

    def test_review_wps_fragment_charset_breaks_and_images(self):
        body = (
            '<p class="MsoHeading1"><span style="font-family:黑体;font-size:22.0pt;font-weight:bold">通知标题</span></p>'
            '<p class="MsoNormal"><span style="font-family:仿宋_GB2312;font-size:16.0pt">正文第一段</span></p>'
        )
        context = (
            '<html><head><meta charset="utf-8"></head><body><!--StartFragment-->'
            + body + '<!--EndFragment--></body></html>'
        ).encode('utf-8')
        header_tmpl = (
            'Version:0.9\r\nStartHTML:{s:010d}\r\nEndHTML:{e:010d}\r\n'
            'StartFragment:{sf:010d}\r\nEndFragment:{ef:010d}\r\n'
        )
        header_len = len(header_tmpl.format(s=0, e=0, sf=0, ef=0).encode('ascii'))
        content_at = context.find(b'<!--StartFragment-->') + len(b'<!--StartFragment-->')
        end_at = context.find(b'<!--EndFragment-->')
        start = header_len + content_at + 1
        header = header_tmpl.format(
            s=header_len, e=header_len + len(context), sf=start, ef=header_len + end_at,
        ).encode('ascii')
        shifted = clip.document_from_parts(html=header + context)
        self.assertEqual(shifted.blocks[0]['type'], 'heading')
        self.assertEqual(shifted.blocks[0]['level'], 1)
        self.assertEqual(shifted.blocks[0]['runs'][0]['text'], '通知标题')
        self.assertEqual(shifted.blocks[0]['runs'][0]['eastAsia'], '黑体')
        self.assertEqual(shifted.blocks[1]['runs'][0]['text'], '正文第一段')
        self.assertEqual(shifted.blocks[1]['runs'][0]['eastAsia'], '仿宋_GB2312')

        labeled = '''<html><head><meta http-equiv="Content-Type" content="text/html; charset=gb2312"></head>
<body>
<p class="MsoHeading1"><span style="font-family:黑体;font-size:22.0pt;font-weight:bold">通知标题</span></p>
<p class="MsoNormal"><span style="font-family:仿宋_GB2312;font-size:16.0pt">正文第一段</span></p>
</body></html>'''
        decoded = clip.document_from_parts(html=labeled.encode('utf-8'))
        self.assertEqual(decoded.blocks[0]['runs'][0]['text'], '通知标题')
        self.assertEqual(decoded.blocks[0]['runs'][0]['eastAsia'], '黑体')
        self.assertEqual(decoded.blocks[1]['runs'][0]['eastAsia'], '仿宋_GB2312')

        breaks = {
            'before': '<p>第一页</p><div style="page-break-before:always"></div><p>第二页</p>',
            'after': '<p style="page-break-after:always">上一页</p><p>下一页</p>',
            'modern': '<h2 style="break-before:page">第二页标题</h2>',
        }
        for html in breaks.values():
            doc = clip.document_from_parts(html=html)
            self.assertIn({'type': 'pagebreak'}, doc.blocks)
        modern = clip.document_from_parts(html=breaks['modern'])
        self.assertEqual(modern.blocks[0]['type'], 'pagebreak')
        self.assertEqual(modern.blocks[1]['level'], 2)

        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg==')
        jpeg = bytes.fromhex('ffd8ffe000104a46494600010100000100010000ffd9')
        html = (
            '<p>说明</p><img src="data:image/jpeg;base64,%s">'
            '<table><tr><td>格内<img src="file:///tmp/cell.png" width="12" height="8">字</td></tr></table>'
        ) % base64.b64encode(jpeg).decode('ascii')
        rtf = r'{\rtf1\ansi\pard{\pict\pngblip\picwgoal180\pichgoal120 ' + png.hex() + '}}'
        mixed = clip.document_from_parts(html=html.encode('utf-8'), rtf=rtf.encode('ascii'))
        self.assertIn(jpeg, mixed.assets.values())
        self.assertIn(png, mixed.assets.values())
        cell = ''.join(
            run.get('text', '')
            for block in mixed.blocks if block['type'] == 'table'
            for row in block['rows'] for item in row if not item.get('covered')
            for run in item.get('runs') or []
        )
        self.assertIn('格内', cell)
        self.assertIn('字', cell)

    def test_review_rtf_merge_keeps_visible_text(self):
        def hexrun(text):
            return ''.join("\\'%02x" % byte for byte in text.encode('gb18030'))

        late = (
            r'{\rtf1\ansi\ansicpg936{\fonttbl{\f0\fnil\fcharset134 \'cb\'ce\'cc\'e5;}}'
            r'\pard\intbl\f0 ' + hexrun('表头') + r'\cell\cell'
            r'\trowd\clmgf\cellx3000\clmrg\cellx6000\row'
            r'\pard\intbl ' + hexrun('左') + r'\cell ' + hexrun('右下') + r'\cell'
            r'\trowd\clvmgf\cellx3000\cellx6000\row'
            r'\pard ' + hexrun('之后') + r'\par}'
        )
        doc = clip.document_from_parts(rtf=late.encode('ascii'))
        tables = [block for block in doc.blocks if block['type'] == 'table']
        self.assertEqual(len(tables), 1)
        table = tables[0]
        visible = text_of(doc)
        self.assertIn('表头', visible)
        self.assertIn('左', visible)
        self.assertIn('右下', visible)
        self.assertIn('之后', visible)
        self.assertEqual(table['rows'][0][0]['runs'][0]['text'], '表头')
        self.assertEqual(table['rows'][1][0]['runs'][0]['text'], '左')
        self.assertEqual(table['rows'][1][1]['runs'][0]['text'], '右下')
        self.assertEqual(table['merges'][0]['colspan'], 2)

        only_tail = clip.document_from_parts(rtf=(
            r'{\rtf1\ansi\ansicpg936{\fonttbl{\f0\fnil\fcharset134 \'cb\'ce\'cc\'e5;}}'
            r'\trowd\clmgf\cellx3000\clmrg\cellx6000\intbl\f0\cell '
            + hexrun('表头') + r'\cell\row\pard after\par}'
        ).encode('ascii'))
        self.assertIn('表头', text_of(only_tail))

        vertical = clip.document_from_parts(rtf=(
            r'{\rtf1\ansi\ansicpg936{\fonttbl{\f0\fnil\fcharset134 \'cb\'ce\'cc\'e5;}}'
            r'\trowd\clvmgf\cellx3000\cellx6000\intbl\f0\cell ' + hexrun('右上') + r'\cell\row'
            r'\trowd\clvmrg\cellx3000\cellx6000\intbl ' + hexrun('左') + r'\cell ' + hexrun('右下') + r'\cell\row}'
        ).encode('ascii'))
        self.assertIn('左', text_of(vertical))
        self.assertIn('右上', text_of(vertical))
        self.assertIn('右下', text_of(vertical))

        both = clip.document_from_parts(rtf=(
            r'{\rtf1\ansi\ansicpg936{\fonttbl{\f0\fnil\fcharset134 \'cb\'ce\'cc\'e5;}}'
            r'\trowd\clmgf\cellx3000\clmrg\cellx6000\intbl\f0 '
            + hexrun('表') + r'\cell ' + hexrun('头') + r'\cell\row}'
        ).encode('ascii'))
        self.assertIn('表', text_of(both))
        self.assertIn('头', text_of(both))

    def test_long_html_progress_moves(self):
        html = '<html><body>' + ''.join('<p>第%d段</p>' % index for index in range(2000)) + '</body></html>'
        seen = []
        doc = clip.document_from_parts(html=html, progress=seen.append)
        self.assertEqual(seen[0], 5)
        self.assertEqual(seen[-1], 100)
        self.assertEqual(seen, sorted(seen))
        self.assertGreater(len(set(seen)), 4)
        self.assertLess(seen[1], 100)
        self.assertEqual(len(doc.blocks), 2000)

    def test_progress_reaches_100(self):
        seen = []
        clip.document_from_parts(html=(SAMPLES / 'wps.html').read_bytes(), progress=seen.append)
        self.assertEqual(seen[0], 5)
        self.assertEqual(seen[-1], 100)
        self.assertEqual(seen, sorted(seen))
        self.assertTrue(all(0 <= value <= 100 for value in seen))

    def test_save_load_and_docx_roundtrip(self):
        doc = clip.document_from_parts(html=(SAMPLES / 'wps.html').read_bytes())
        folder = Path(tempfile.mkdtemp())
        try:
            wenju = folder / 'clip.wenju'
            fmt.save(doc, wenju)
            with zipfile.ZipFile(str(wenju)) as archive:
                names = set(archive.namelist())
                self.assertTrue({'document.json', 'manifest.json', 'styles.json'} <= names)
                self.assertTrue(any(name.startswith('assets/') for name in names))
                self.assertIsInstance(json.loads(archive.read('document.json').decode('utf-8')).get('blocks'), list)
            loaded = fmt.load(wenju)
            self.assertEqual(loaded.blocks, doc.blocks)
            self.assertEqual(loaded.assets, doc.assets)
            docx = folder / 'clip.docx'
            fmt.to_docx(loaded, docx)
            back = fmt.from_docx(docx)
            self.assertIn('通知标题', text_of(back))
            self.assertIn('正文第一段', text_of(back))
            self.assertIn('表头', text_of(back))
            self.assertIn('右下', text_of(back))
            self.assertIn('第二页', text_of(back))
            self.assertTrue(any(block['type'] == 'heading' and block['level'] == 1 for block in back.blocks))
            self.assertTrue(any(name.startswith('word/media/') for name in zipfile.ZipFile(str(docx)).namelist()))
            rules = json.loads((ROOT / 'core' / 'rules.json').read_text(encoding='utf-8-sig'))
            brushed = folder / 'brushed.docx'
            fmt.to_docx(loaded, brushed, template=clip.brush_styles(rules))
            painted = fmt.from_docx(brushed)
            heading = next(block for block in painted.blocks if block['type'] == 'heading')
            self.assertEqual(heading['runs'][0]['eastAsia'], '黑体')
            self.assertEqual(heading['runs'][0]['size_pt'], 16)
            self.assertNotIn('bold', heading['runs'][0])
            body = next(block for block in painted.blocks if block['type'] == 'paragraph' and '正文' in ''.join(run.get('text', '') for run in block['runs']))
            self.assertEqual(body['runs'][0]['eastAsia'], '仿宋_GB2312')
            xml = zipfile.ZipFile(str(brushed)).read('word/document.xml').decode('utf-8')
            self.assertIn('仿宋_GB2312', xml)
            self.assertNotRegex(xml, r'eastAsia="仿宋"')
            self.assertEqual(body['runs'][0]['size_pt'], 16)
        finally:
            shutil.rmtree(str(folder))

    def test_qt_binding_flag(self):
        import qt_compat
        previous = os.environ.get('WENJU_QT')
        try:
            os.environ['WENJU_QT'] = '5'
            self.assertEqual(qt_compat.binding(), 'PySide2')
            os.environ['WENJU_QT'] = '6'
            self.assertEqual(qt_compat.binding(), 'PySide6')
            os.environ.pop('WENJU_QT', None)
            expected = 'PySide6' if importlib.util.find_spec('PySide6') is not None else 'PySide2'
            self.assertEqual(qt_compat.binding(), expected)
        finally:
            if previous is None:
                os.environ.pop('WENJU_QT', None)
            else:
                os.environ['WENJU_QT'] = previous

    def test_validate_rejects_a_bad_block(self):
        doc = fmt.WenjuDoc([{'type': 'heading', 'level': 0, 'runs': []}, {'type': 'image', 'asset': 'missing.png', 'w': 1, 'h': 1}], {}, {})
        errors = fmt.validate(doc)
        self.assertTrue(errors)


if __name__ == '__main__':
    unittest.main()
