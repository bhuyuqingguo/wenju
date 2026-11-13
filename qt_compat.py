"""Qt binding used by the UI.

Win10/11 and Kylin packages ship PySide6. The Windows 7 package ships only
PySide2 and sets WENJU_QT=5. With PySide6 installed and WENJU_QT unset, this
module loads PySide6 and keeps the existing style and color-scheme calls.
"""
import importlib
import importlib.util
import os

_forced_pyside2 = os.environ.get('WENJU_QT') == '5'
QT = '6'
if _forced_pyside2:
    QT = '5'
else:
    try:
        from PySide6.QtCore import QObject, Signal, Slot, Property, QUrl, QProcess, QTimer, qInstallMessageHandler, Qt, QPoint, QPointF, QMimeData, QMetaObject
        from PySide6.QtGui import QGuiApplication, QDesktopServices, QIcon, QPalette, QColor, QFontDatabase, QFont
        from PySide6.QtQml import QQmlApplicationEngine
        from PySide6.QtQuick import QQuickWindow
        from PySide6.QtQuickControls2 import QQuickStyle
        from PySide6.QtWidgets import QApplication, QFileDialog
        from PySide6.QtTest import QTest
        import shiboken6 as _shiboken
    except ImportError:
        QT = '5'

if QT == '5':
    try:
        from PySide2.QtCore import QObject, Signal, Slot, Property, QUrl, QProcess, QTimer, qInstallMessageHandler, Qt, QPoint, QPointF, QMimeData, QMetaObject
        from PySide2.QtGui import QGuiApplication, QDesktopServices, QIcon, QPalette, QColor, QFontDatabase, QFont
        from PySide2.QtQml import QQmlApplicationEngine
        from PySide2.QtQuick import QQuickWindow
        from PySide2.QtQuickControls2 import QQuickStyle
        from PySide2.QtWidgets import QApplication, QFileDialog
        from PySide2.QtTest import QTest
        import shiboken2 as _shiboken
    except ImportError:
        if _forced_pyside2:
            raise
        QT = ''


def binding():
    flag = os.environ.get('WENJU_QT', '').strip()
    if flag == '5':
        return 'PySide2'
    if flag == '6':
        return 'PySide6'
    if importlib.util.find_spec('PySide6') is not None:
        return 'PySide6'
    return 'PySide2'


def load():
    name = 'PySide2' if QT == '5' else 'PySide6'
    return (
        importlib.import_module(name + '.QtCore'),
        importlib.import_module(name + '.QtGui'),
        importlib.import_module(name + '.QtWidgets'),
    )


def exec_app(app):
    if QT == '5':
        return app.exec_()
    return app.exec()


def delete_qobject(obj):
    _shiboken.delete(obj)


def set_color_scheme(app, dark):
    scheme = getattr(Qt, 'ColorScheme', None)
    hints = app.styleHints()
    if scheme is None or not hasattr(hints, 'setColorScheme'):
        return
    hints.setColorScheme(scheme.Dark if dark else scheme.Light)


def quick_style():
    # Basic exists on Qt 6. Qt 5.15 uses Fusion; the QML controls paint their own backgrounds.
    return 'Fusion' if QT == '5' else 'Basic'


def failed_to_start(qprocess):
    nested = getattr(qprocess, "ProcessError", None)
    if nested is not None and hasattr(nested, "FailedToStart"):
        return nested.FailedToStart
    return qprocess.FailedToStart
