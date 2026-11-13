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
