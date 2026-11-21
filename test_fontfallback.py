"""Font fallback without the real GB2312 face installed."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / 'core'))
import fontfallback
from templates import apply_official_photo
from preset_store import BASE

fontfallback.reset_index()
fontfallback._INDEX = {'仿宋': '仿宋', 'fangsong': '仿宋'}
chosen, found = fontfallback.choose('仿宋_GB2312')
assert found and chosen == '仿宋', (chosen, found)
print('LOG: 仿宋_GB2312 missing, chose', chosen)

fontfallback._INDEX = {}
chosen, found = fontfallback.choose('仿宋_GB2312')
assert not found and chosen == '仿宋_GB2312'
rules = apply_official_photo(BASE)
text = fontfallback.guidance(rules)
assert '仿宋_GB2312' in text and '可选字体' in text
assert '方正小标宋简体' in text
print('LOG: neither face installed')
print(text)
print('PASS: fangsong fallback and missing-font guidance')

import os, struct, tempfile
os.environ['WENJU_DATA_DIR'] = tempfile.mkdtemp(prefix='wenju-font-embed-')
import fontembed
import paths

def _otf(family):
    def record(name_id, text, offset):
        raw = text.encode('utf-16-be')
        return struct.pack('>HHHHHH', 3, 1, 0x0409, name_id, len(raw), offset), raw
    recs, blobs, cursor = [], [], 0
    for name_id, text in ((1, family), (2, 'Regular')):
        rec, blob = record(name_id, text, cursor)
        recs.append(rec); blobs.append(blob); cursor += len(blob)
    name = struct.pack('>HHH', 0, len(recs), 6 + 12 * len(recs)) + b''.join(recs) + b''.join(blobs)
    header = b'OTTO' + struct.pack('>HHHH', 1, 0, 0, 0)
    entry = struct.pack('>4sIII', b'name', 0, 12 + 16, len(name))
    return header + entry + name

managed = paths.font_dirs()
assert any(path.endswith(os.path.join('开源字体')) or path.endswith('/开源字体') for path in managed), managed
folder = next(path for path in managed if path.endswith('开源字体'))
os.makedirs(os.path.join(folder, 'sans'), exist_ok=True)
target = os.path.join(folder, 'sans', 'WenJuTest-Regular.otf')
open(target, 'wb').write(_otf('WenJu OTF'))
indexed = fontembed.index_fonts(fontembed.font_dirs(managed))
assert 'wenju otf' in indexed, sorted(indexed)
items = {
    'word/_rels/document.xml.rels': b'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>',
    '[Content_Types].xml': b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/></Types>',
}
done, missing = fontembed.embed_fonts(items, ['WenJu OTF'], managed, [])
assert done == ['WenJu OTF'] and missing == [] and any(name.startswith('word/fonts/') for name in items), (done, missing)
print('PASS: otf in the managed font directory is embedded')
