"""Editable sample results kept separate from the active work plan."""
import copy
import re

from preset_store import BASE, checked, fields, sections
from qt_compat import QObject, Property, Signal, Slot, font_families


class InferenceDraft(QObject):
    changed = Signal()
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rules = copy.deepcopy(BASE)
        self.section = '页面'

    def load(self, rules):
        self.rules = copy.deepcopy(rules)
        self.section = '页面'
        self.changed.emit()

    @Property('QVariantList', notify=changed)
    def ruleSections(self):
        return sections(self.rules)

    @Property('QVariantList', notify=changed)
    def ruleFields(self):
        rows = fields(self.rules, self.section)
        for row in rows:
            if row['kind'] == 'choice' and row['editable'] and not row['path'].endswith('.字号'):
                row['values'] = list(dict.fromkeys(row['values'] + font_families()))
                row['labels'] = row['values']
        return rows

    @Property(str, notify=changed)
    def sectionName(self):
        return self.section.replace('.', ' / ')

    @Property(str, notify=changed)
    def sectionTip(self):
        return next((item['tip'] for item in self.ruleSections if item['key'] == self.section), '')

    @Slot(str)
    def setSection(self, section):
        if any(item['key'] == section for item in self.ruleSections):
            self.section = section
            self.changed.emit()

    @Slot(str, 'QVariant', result=bool)
    def editRule(self, path, value):
        try:
            target, default = self.rules, BASE
            *groups, key = path.split('.')
            for group in groups:
                target, default = target[group], default[group]
            if isinstance(default[key], list) and isinstance(value, str):
                value = [item.strip() for item in re.split('[、,，;；\n]', value) if item.strip()]
            value = checked(path, value, default[key])
            if target[key] != value:
                target[key] = value
                if path == '页码.格式':
                    left, right = {'1': ('', ''), '- 1 -': ('- ', ' -'), '第 1 页': ('第 ', ' 页')}[value]
                    target['左侧字符'], target['右侧字符'] = left, right
                self.changed.emit()
            return True
        except (KeyError, ValueError) as exc:
            self.error.emit(str(exc))
            return False
