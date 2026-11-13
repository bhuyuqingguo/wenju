import importlib.util
import os


def _use_qt5():
    flag = os.environ.get("WENJU_QT", "")
    if flag == "5":
        return True
    if flag == "6":
        return False
    return importlib.util.find_spec("PySide6") is None


QT5 = _use_qt5()

if QT5:
    from PySide2.QtCore import (QObject, Signal, Slot, Property, QUrl, QProcess, QTimer,
                                qInstallMessageHandler, Qt, QPoint, QPointF)
    from PySide2.QtGui import (QGuiApplication, QDesktopServices, QIcon, QPalette, QColor,
                               QFontDatabase, QFont)
    from PySide2.QtQml import QQmlApplicationEngine
    from PySide2.QtQuick import QQuickWindow
    from PySide2.QtQuickControls2 import QQuickStyle
    from PySide2.QtWidgets import QApplication, QFileDialog
    QUICK_STYLE = "Default"
else:
    from PySide6.QtCore import (QObject, Signal, Slot, Property, QUrl, QProcess, QTimer,
                                qInstallMessageHandler, Qt, QPoint, QPointF)
    from PySide6.QtGui import (QGuiApplication, QDesktopServices, QIcon, QPalette, QColor,
                               QFontDatabase, QFont)
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickWindow
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication, QFileDialog
    QUICK_STYLE = "Basic"


def set_color_scheme(app, dark):
    hints = app.styleHints()
    scheme = getattr(Qt, "ColorScheme", None)
    if scheme is None or not hasattr(hints, "setColorScheme"):
        return
    hints.setColorScheme(scheme.Dark if dark else scheme.Light)


def delete_engine(engine):
    if QT5:
        import shiboken2
        shiboken2.delete(engine)
    else:
        import shiboken6
        shiboken6.delete(engine)


def process_failed(error):
    if error == getattr(QProcess, "FailedToStart", None):
        return True
    kind = getattr(QProcess, "ProcessError", None)
    return kind is not None and error == getattr(kind, "FailedToStart", None)


def qtest():
    if QT5:
        from PySide2.QtTest import QTest
    else:
        from PySide6.QtTest import QTest
    return QTest
