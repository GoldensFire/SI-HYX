# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: распространяется/изменяется на условиях GNU General Public
# License v3 (или новее) от Free Software Foundation. БЕЗ ВСЯКИХ ГАРАНТИЙ.
# Полный текст — в файле LICENSE (https://www.gnu.org/licenses/gpl-3.0.txt).
# taskbar.py — индикатор прогресса на иконке в панели задач Windows 11
# через нативный COM-интерфейс ITaskbarList3 (без сторонних зависимостей, чистый ctypes).
#
# Использование (только из GUI-потока):
#   tb = TaskbarProgress()
#   tb.set_value(hwnd, 40, 100)   # 40%
#   tb.set_state(hwnd, TaskbarProgress.INDETERMINATE)
#   tb.clear(hwnd)                # убрать индикатор
#
# hwnd = int(window.winId()). На не-Windows все методы — no-op.

import sys

_IS_WIN = sys.platform == "win32"


class TaskbarProgress:
    # TBPFLAG (windows ShObjIdl)
    NOPROGRESS    = 0x0
    INDETERMINATE = 0x1
    NORMAL        = 0x2
    ERROR         = 0x4
    PAUSED        = 0x8

    def __init__(self):
        self._ok = False
        self._taskbar = None
        self._set_value = None
        self._set_state = None
        if _IS_WIN:
            try:
                self._init_com()
                self._ok = True
            except Exception:
                self._ok = False

    def _init_com(self):
        import ctypes
        from ctypes import wintypes, POINTER, byref, c_void_p

        ole32 = ctypes.OleDLL("ole32")

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD),
                        ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD),
                        ("Data4", ctypes.c_ubyte * 8)]

        def _guid(s):
            g = GUID()
            ole32.CLSIDFromString(ctypes.c_wchar_p(s), byref(g))
            return g

        CLSID_TaskbarList = _guid("{56FDF344-FD6D-11d0-958A-006097C9A090}")
        IID_ITaskbarList3 = _guid("{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}")

        # Qt обычно уже инициализировал COM в GUI-потоке; повторный вызов
        # вернёт S_FALSE — не критично, поэтому исключение глушим.
        try:
            ole32.CoInitialize(None)
        except Exception:
            pass

        CLSCTX_INPROC_SERVER = 0x1
        ppv = c_void_p()
        ole32.CoCreateInstance(byref(CLSID_TaskbarList), None,
                               CLSCTX_INPROC_SERVER, byref(IID_ITaskbarList3),
                               byref(ppv))
        if not ppv.value:
            raise OSError("CoCreateInstance(TaskbarList) failed")
        self._taskbar = ppv

        # COM-объект = указатель на указатель на vtable (массив адресов методов).
        vtbl_addr = ctypes.cast(ppv, POINTER(c_void_p))[0]
        funcs = ctypes.cast(c_void_p(vtbl_addr), POINTER(c_void_p))

        HRESULT = ctypes.c_long
        ULONGLONG = ctypes.c_ulonglong
        HWND = c_void_p
        # Индексы в vtable ITaskbarList3:
        #   IUnknown: 0 QueryInterface, 1 AddRef, 2 Release
        #   ITaskbarList:  3 HrInit ...
        #   ITaskbarList3: 9 SetProgressValue, 10 SetProgressState
        HrInit = ctypes.WINFUNCTYPE(HRESULT, c_void_p)(funcs[3])
        HrInit(ppv)
        self._set_value = ctypes.WINFUNCTYPE(
            HRESULT, c_void_p, HWND, ULONGLONG, ULONGLONG)(funcs[9])
        self._set_state = ctypes.WINFUNCTYPE(
            HRESULT, c_void_p, HWND, ctypes.c_int)(funcs[10])

    @property
    def available(self):
        return self._ok

    def set_value(self, hwnd, completed, total=100):
        """Заполненность прогресс-бара на иконке (0..total). completed<=0 →
        неопределённый («бегущий») режим."""
        if not self._ok or not hwnd:
            return
        try:
            import ctypes
            h = ctypes.c_void_p(int(hwnd))
            if completed <= 0:
                self._set_state(self._taskbar, h, self.INDETERMINATE)
            else:
                self._set_state(self._taskbar, h, self.NORMAL)
                self._set_value(self._taskbar, h, int(completed), int(total) or 100)
        except Exception:
            pass

    def set_state(self, hwnd, state):
        if not self._ok or not hwnd:
            return
        try:
            import ctypes
            self._set_state(self._taskbar, ctypes.c_void_p(int(hwnd)), int(state))
        except Exception:
            pass

    def clear(self, hwnd):
        """Убрать индикатор с иконки."""
        self.set_state(hwnd, self.NOPROGRESS)
