"""Accept local document files dropped onto the import window."""

from pathlib import Path

ORGANIZE_SUFFIXES = ('.docx', '.doc', '.wps', '.rtf', '.wenju')
CONVERT_SUFFIXES = ORGANIZE_SUFFIXES + ('.xlsx', '.xls', '.txt', '.md', '.markdown')
TEMPLATE_PROMPT = '已加入文档。请先选择模板，再开始整理。'


def local_files(mime, suffixes=ORGANIZE_SUFFIXES):
    """Return local paths from a QMimeData file list. Other formats are ignored."""
    urls = []
    if mime is not None and hasattr(mime, 'urls'):
        try:
            urls = list(mime.urls() or [])
        except Exception:
            urls = []
    found = []
    seen = set()
    allowed = {item.lower() for item in suffixes}
    for url in urls:
        if hasattr(url, 'isLocalFile') and not url.isLocalFile():
            continue
        path = Path(url.toLocalFile() if hasattr(url, 'toLocalFile') else str(url))
        if path.suffix.lower() not in allowed or not path.is_file():
            continue
        resolved = str(path.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        found.append(resolved)
    return found


def accept_into(rows, paths, has_template, suffixes=ORGANIZE_SUFFIXES):
    """Append new files to the candidate list. A missing template still keeps the files."""
    known = {row.get('path') for row in rows}
    added = 0
    allowed = {item.lower() for item in suffixes}
    for raw in paths or []:
        if not raw:
            continue
        path = Path(raw)
        if path.suffix.lower() not in allowed or not path.is_file():
            continue
        resolved = str(path.resolve())
        if resolved in known:
            continue
        rows.append({
            'path': resolved,
            'name': path.name,
            'state': '等待整理',
            'output': '',
            'report': '',
            'percent': 0,
        })
        known.add(resolved)
        added += 1
    if added and not has_template:
        return TEMPLATE_PROMPT
    return ''


def _widget_base():
    from qt_compat import QT
    if QT == '5':
        from PySide2.QtCore import QEvent, Qt
        from PySide2.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
        from PySide2.QtWidgets import QWidget
    else:
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
        from PySide6.QtWidgets import QWidget
    return QWidget, QEvent, Qt, QDragEnterEvent, QDragMoveEvent, QDropEvent


class ImportDrop(_widget_base()[0]):
    """Whole-window drop target. setAcceptDrops is on, and the three drag events are handled."""

    def __init__(self, on_files, suffixes=ORGANIZE_SUFFIXES):
        super().__init__()
        self.setAcceptDrops(True)
        self.on_files = on_files
        self.suffixes = suffixes
        self.hover = False

    def dragEnterEvent(self, event):
        if local_files(event.mimeData(), self.suffixes):
            event.acceptProposedAction()
            self.hover = True
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if local_files(event.mimeData(), self.suffixes):
            event.acceptProposedAction()
            self.hover = True
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.hover = False
        event.accept()

    def dropEvent(self, event):
        paths = local_files(event.mimeData(), self.suffixes)
        self.hover = False
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        self.on_files(paths)


def install_window_drop(window, on_files, on_hover=None, suffixes=ORGANIZE_SUFFIXES):
    """Forward the window's drag events to ImportDrop so Explorer drops reach the import page."""
    from qt_compat import QObject
    _QWidget, QEvent, _Qt, _enter, _move, _drop = _widget_base()
    surface = ImportDrop(on_files, suffixes)
    kinds = {QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop, QEvent.Type.DragLeave}

    class _Filter(QObject):
        def eventFilter(self, obj, event):
            kind = event.type()
            if kind not in kinds:
                return False
            if kind == QEvent.Type.DragLeave:
                surface.dragLeaveEvent(event)
                if on_hover:
                    on_hover(False)
                return False
            if not hasattr(event, 'mimeData') or not local_files(event.mimeData(), surface.suffixes):
                return False
            if kind == QEvent.Type.DragEnter:
                surface.dragEnterEvent(event)
            elif kind == QEvent.Type.DragMove:
                surface.dragMoveEvent(event)
            elif kind == QEvent.Type.Drop:
                surface.dropEvent(event)
            else:
                surface.dragLeaveEvent(event)
            if on_hover:
                on_hover(surface.hover)
            return bool(event.isAccepted()) if kind != QEvent.Type.DragLeave else False

    filt = _Filter(window)
    window.installEventFilter(filt)
    app = None
    try:
        from qt_compat import QApplication
        app = QApplication.instance()
    except Exception:
        app = None
    if app is not None:
        app.installEventFilter(filt)
    surface._filter = filt
    return surface
