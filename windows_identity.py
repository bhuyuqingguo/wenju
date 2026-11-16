"""Windows taskbar identity for the Qt window hosted by Python."""

import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import uuid

APP_ID = 'WenJu.Desktop'
SHELL = c.WinDLL('shell32')
HRESULT = c.c_long


class PropertyKey(c.Structure):
    _fields_ = [('format_id', c.c_ubyte * 16), ('property_id', w.DWORD)]


class Value(c.Structure):
    # PROPVARIANT has room for a pair of pointers even when only one is used.
    _fields_ = [('type', w.USHORT), ('reserved', w.USHORT * 3),
                ('payload', c.c_void_p * 2)]


FMTID = uuid.UUID('9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3').bytes_le
IID = (c.c_ubyte * 16).from_buffer_copy(
    uuid.UUID('886d8eeb-8cf2-4446-8d02-cdba1dbdcf99').bytes_le)
SHELL.SHGetPropertyStoreForWindow.argtypes = (w.HWND, c.c_void_p, c.POINTER(c.c_void_p))
SHELL.SHGetPropertyStoreForWindow.restype = HRESULT
SHELL.SetCurrentProcessExplicitAppUserModelID.argtypes = (w.LPCWSTR,)
SHELL.SetCurrentProcessExplicitAppUserModelID.restype = HRESULT


def _check(result):
    if result < 0:
        raise OSError('Windows Shell HRESULT 0x%08x' % (result & 0xffffffff))


def initialize():
    _check(SHELL.SetCurrentProcessExplicitAppUserModelID(APP_ID))


class WindowIdentity:
    def __init__(self, window, root):
        self.store = c.c_void_p()
        self.properties = []
        _check(SHELL.SHGetPropertyStoreForWindow(int(window.winId()), IID, c.byref(self.store)))
        table = c.cast(self.store, c.POINTER(c.POINTER(c.c_void_p))).contents
        self.set_value = c.WINFUNCTYPE(HRESULT, c.c_void_p, c.POINTER(PropertyKey), c.POINTER(Value))(table[6])
        self.release = c.WINFUNCTYPE(w.ULONG, c.c_void_p)(table[2])
        try:
            entry = os.environ.get('WENJU_PRODUCT_ENTRY')
            path = Path(entry) if entry else None
            reliable = path and path.is_absolute() and path.parent.resolve() == root.resolve() and path.is_file()
            self._set(5, APP_ID)
            if reliable:
                self._set(2, '"%s"' % path)
                self._set(3, '@%s,-100' % path)
                self._set(4, '%s,0' % path)
            else:
                self._set(9, True)  # PreventPinning on developer/temporary runs.
        except Exception:
            self.close()
            raise

    def _set(self, number, value=None):
        key = PropertyKey((c.c_ubyte * 16).from_buffer_copy(FMTID), number)
        prop = Value()
        if isinstance(value, str):
            buf = c.create_unicode_buffer(value)
            prop.type = 31  # VT_LPWSTR
            prop.payload[0] = c.addressof(buf)
        elif value is True:
            prop.type = 11  # VT_BOOL
            prop.payload[0] = 0xffff
        _check(self.set_value(self.store, c.byref(key), c.byref(prop)))
        if value is not None:
            self.properties.append(number)

    def close(self):
        if not self.store:
            return
        try:
            for number in reversed(self.properties):
                try:
                    self._set(number)  # VT_EMPTY
                except OSError:
                    pass  # The platform may have already destroyed the HWND.
        finally:
            self.release(self.store)
            self.store = None
