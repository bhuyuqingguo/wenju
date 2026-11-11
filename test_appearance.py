import copy,json,tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication
from appearance import Appearance,THEMES
from preset_store import PresetStore

app=QApplication([])
with tempfile.TemporaryDirectory(prefix='wenju-look-') as tmp:
    a=Appearance(tmp,app);store=PresetStore(tmp);before=copy.deepcopy(store.rules);store.persist()
    saved=(Path(tmp)/'current.json').read_bytes()
    for t in THEMES:
        for size in (12,14,16,18):
            a.setPreferences(t['id'],'Arial',size)
            b=Appearance(tmp,app)
            assert (b.themeId,b.fontFamily,b.fontSize)==(t['id'],'Arial',size)
            assert b.colors['ink'] and b.colors['surface'] and b.scale==size/14
    assert (Path(tmp)/'current.json').read_bytes()==saved
    assert store.rules==before
    old=copy.deepcopy(a.state)
    a.setPreferences('invalid','Arial',14);assert a.state==old
    a.setPreferences('blue','',14);assert a.state==old
    a.setPreferences('blue','Arial',90);assert a.state==old
    a.reset();assert a.themeId=='blue' and a.fontSize==14
print('PASS: 5 skins x 4 UI sizes, persistence, validation, reset, no document rule changes')
