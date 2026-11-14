"""Drag a local file onto the import target and see it land in the candidate list."""

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))

from qt_compat import QUrl, QMimeData, Qt, QPoint
from import_drop import (
    CONVERT_SUFFIXES,
    ORGANIZE_SUFFIXES,
    TEMPLATE_PROMPT,
    ImportDrop,
    accept_into,
    local_files,
)


def _events():
    from qt_compat import QT
    if QT == "5":
        from PySide2.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
    else:
        from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
    return QDragEnterEvent, QDragMoveEvent, QDropEvent


def _send(surface, mime):
    enter_cls, move_cls, drop_cls = _events()
    pos = QPoint(24, 16)
    enter = enter_cls(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    surface.dragEnterEvent(enter)
    assert enter.isAccepted(), "drag enter ignored a local document"
    move = move_cls(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    surface.dragMoveEvent(move)
    assert move.isAccepted()
    assert surface.hover
    drop = drop_cls(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    surface.dropEvent(drop)
    assert drop.isAccepted()
    assert surface.hover is False


def main():
    from qt_compat import QApplication
    app = QApplication.instance() or QApplication([])
    assert app is not None
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        docx = folder / "报告.docx"
        wenju = folder / "笔记.wenju"
        skipped = folder / "图片.png"
        docx.write_bytes(b"docx")
        wenju.write_bytes(b"wenju")
        skipped.write_bytes(b"png")
        rows = []
        notes = []

        def receive(paths):
            notes.append(accept_into(rows, paths, has_template=False))

        surface = ImportDrop(receive, ORGANIZE_SUFFIXES)
        assert surface.acceptDrops()
        mime = QMimeData()
        mime.setUrls([
            QUrl.fromLocalFile(str(docx)),
            QUrl.fromLocalFile(str(wenju)),
            QUrl.fromLocalFile(str(skipped)),
        ])
        found = local_files(mime, ORGANIZE_SUFFIXES)
        assert [Path(item).name for item in found] == ["报告.docx", "笔记.wenju"]
        _send(surface, mime)
        assert [row["name"] for row in rows] == ["报告.docx", "笔记.wenju"]
        assert notes == [TEMPLATE_PROMPT]
        _send(surface, mime)
        assert len(rows) == 2

        chosen = []

        def receive_ready(paths):
            accept_into(chosen, paths, has_template=True)

        ready = ImportDrop(receive_ready)
        _send(ready, mime)
        assert [row["name"] for row in chosen] == ["报告.docx", "笔记.wenju"]
        assert accept_into(chosen, [str(docx)], True) == ""

        foreign = QMimeData()
        foreign.setUrls([QUrl("https://example.com/报告.docx")])
        enter_cls, _move_cls, _drop_cls = _events()
        ignored = enter_cls(QPoint(1, 1), Qt.CopyAction, foreign, Qt.LeftButton, Qt.NoModifier)
        surface.dragEnterEvent(ignored)
        assert not ignored.isAccepted()
        assert ".wps" in ORGANIZE_SUFFIXES and ".xlsx" in CONVERT_SUFFIXES
    print("PASS: file drop enters, moves, and lands in the candidate list")


if __name__ == "__main__":
    main()
