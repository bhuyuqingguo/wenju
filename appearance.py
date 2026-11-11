"""UI-only preferences; independent from document formatting and templates."""
from pathlib import Path
import json
from PySide6.QtCore import QObject, Property, Signal, Slot, Qt
from PySide6.QtGui import QPalette, QColor, QFont
from preset_store import atomic_json

THEMES = [
    dict(id='blue',name='文矩 · 深海蓝',desc='经典品牌色，清晰而沉稳',accent='#245a83',nav='#183a57',bg='#f4f6f9',surface='#ffffff',soft='#eaf0f6',field='#f9fafc',ink='#22344a',muted='#65778b',line='#dce3eb',selected='#2c526f',gold='#e6b35f',dark=False),
    dict(id='jade',name='青竹 · 雅绿',desc='清润柔和，适合长时间阅读',accent='#316c60',nav='#22483f',bg='#f2f6f3',surface='#ffffff',soft='#e5efe9',field='#f6faf7',ink='#263f36',muted='#627b70',line='#d5e3da',selected='#376456',gold='#e6c58b',dark=False),
    dict(id='paper',name='纸墨 · 暖白',desc='温暖纸感，专注文字本身',accent='#80613f',nav='#453e36',bg='#f6f2e9',surface='#fffcf5',soft='#eee6d8',field='#faf5eb',ink='#433c32',muted='#80725f',line='#e0d7c7',selected='#685b49',gold='#d9b16c',dark=False),
    dict(id='iris',name='鸢尾 · 雾紫',desc='轻盈克制，带一点灵感',accent='#695a91',nav='#39344f',bg='#f5f3f8',surface='#ffffff',soft='#ece8f4',field='#faf8fc',ink='#393449',muted='#7b728d',line='#e1dbea',selected='#554a70',gold='#d8b889',dark=False),
    dict(id='night',name='星夜 · 深色',desc='降低亮度，适合夜间工作',accent='#88b9df',nav='#121d2a',bg='#182330',surface='#223040',soft='#2b3d50',field='#1c2a39',ink='#e0e9f2',muted='#a8b9c9',line='#3b4f62',selected='#344d65',gold='#e6b35f',dark=True),
]

class Appearance(QObject):
    changed=Signal()
    def __init__(self,data,app):
        super().__init__();self.path=Path(data)/'appearance.json';self.app=app
        self.state={'theme':'blue','font':'Microsoft YaHei UI' if __import__('sys').platform=='win32' else 'Noto Sans CJK SC','size':14,'intro':True,'motion':True}
        try:
            s=json.loads(self.path.read_text('utf-8'))
            if s.get('theme') in [t['id'] for t in THEMES]:self.state['theme']=s['theme']
            if isinstance(s.get('font'),str) and s['font'].strip():self.state['font']=s['font']
            if s.get('size') in (12,14,16,18):self.state['size']=s['size']
            if isinstance(s.get('intro'),bool):self.state['intro']=s['intro']
        except (OSError,ValueError,TypeError):pass
        self.state['motion']=s.get('motion',True) if 's' in locals() and isinstance(s.get('motion',True),bool) else True
        self.apply()
    @Property('QVariantList',constant=True)
    def themes(self):return THEMES
    @Property(str,notify=changed)
    def themeId(self):return self.state['theme']
    @Property(str,notify=changed)
    def fontFamily(self):return self.state['font']
    @Property(int,notify=changed)
    def fontSize(self):return self.state['size']
    @Property(float,notify=changed)
    def scale(self):return self.state['size']/14
    @Property(bool,notify=changed)
    def motion(self):return self.state.get('motion',True) and __import__('os').environ.get('WENJU_LOW_POWER')!='1'
    @Slot(bool)
    def setMotion(self,value):
        self.state['motion']=value;atomic_json(self.path,self.state);self.changed.emit()
    @Property(bool,notify=changed)
    def showIntro(self):return self.state.get('intro',True)
    @Slot(bool)
    def setShowIntro(self,value):
        self.state['intro']=value;atomic_json(self.path,self.state);self.changed.emit()
    @Property('QVariantMap',notify=changed)
    def colors(self):
        t=next(t for t in THEMES if t['id']==self.themeId)
        return {**t,'onAccent':'#142433' if t['dark'] else '#ffffff','navText':'#ffffff','navMuted':'#b4c6d3','success':'#88c4ad' if t['dark'] else '#35806c'}
    @Property('QVariantMap',notify=changed)
    def palette(self):
        c=self.colors;out={}
        groups={
          'bg':['#f4f6f9'], 'surface':['#ffffff'],
          'nav':['#183a57'],'selected':['#2c526f'],
          'accent':['#245a83','#316b97','#294c6b'],
          'ink':['#22344a','#354b61'],
          'muted':['#7b8899','#8795a5','#a0aab7','#a3adba','#9eafbf'],
          'soft':['#eaf0f6','#e9eff6','#e8eef5','#eaf1f8','#e9eef4','#edf2f7','#d6e3ef','#e3edf6'],
          'field':['#f9fafc','#f7f9fc','#f1f4f8'],
          'line':['#dce3eb','#dce4ed','#e0e5ed','#dbe5ef','#e2e7ee','#edf0f5','#dfe5ed','#e0e6ee','#dfe6ee','#d5dee8','#edf0f4'],
          'navMuted':['#a6bbcd','#738fa6','#adc1d0','#819bad','#9aabba','#688297'],
          'selected':['#2c526f','#35536c','#1e405d','#49647b','#45647d'],
          'gold':['#e6b35f','#c79a46'], 'success':['#35806c','#8cbaa8','#5a9684']}
        for role,values in groups.items():
            for value in values:out[value]=c[role]
        return out
    def apply(self):
        c=self.colors;p=QPalette()
        for role,value in [(QPalette.Window,c['bg']),(QPalette.WindowText,c['ink']),(QPalette.Base,c['field']),(QPalette.Text,c['ink']),(QPalette.Button,c['surface']),(QPalette.ButtonText,c['ink']),(QPalette.Highlight,c['accent']),(QPalette.HighlightedText,c['onAccent']),(QPalette.ToolTipBase,c['surface']),(QPalette.ToolTipText,c['ink'])]:p.setColor(role,QColor(value))
        self.app.setPalette(p)
        f=QFont(self.fontFamily);f.setPixelSize(self.fontSize);self.app.setFont(f)
        self.app.styleHints().setColorScheme(Qt.ColorScheme.Dark if c['dark'] else Qt.ColorScheme.Light)
    @Slot(str,str,int)
    def setPreferences(self,theme,font,size):
        if theme not in [t['id'] for t in THEMES] or size not in (12,14,16,18) or not font.strip():return
        self.state.update({'theme':theme,'font':font.strip(),'size':size});atomic_json(self.path,self.state);self.apply();self.changed.emit()
    @Slot()
    def reset(self):self.setPreferences('blue','Microsoft YaHei UI' if __import__('sys').platform=='win32' else 'Noto Sans CJK SC',14)
