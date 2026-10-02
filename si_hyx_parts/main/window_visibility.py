# -*- coding: utf-8 -*-
"""Keep the last usable window rectangle across minimize/restore and screens."""
import os

from PyQt6.QtCore import QEvent, QObject, QRect, QTimer
from PyQt6.QtWidgets import QApplication


def titlebar_visible(rect, areas):
    if not rect.isValid():
        return False
    title = QRect(rect.x(), rect.y(), rect.width(), 32)
    return any((visible := title.intersected(area)).width() >= 64
               and visible.height() >= 16 for area in areas)


def native_minimized(window):
    # Qt may not have processed WM_SIZE yet. Do not mistake Windows' minimized
    # coordinates (-32000 physical pixels) for a user move or a valid restore.
    if os.name != "nt":
        return False
    handle = window.windowHandle()
    if handle is None:
        return False
    import ctypes
    user = ctypes.windll.user32
    user.IsIconic.argtypes = [ctypes.c_void_p]
    user.IsIconic.restype = ctypes.c_int
    return bool(user.IsIconic(int(handle.winId())))


class WindowVisibilityGuard(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.last_visible = QRect(window.geometry())
        self.pending = False
        self.recovering = False
        window.installEventFilter(self)
        app = QApplication.instance()
        app.screenRemoved.connect(self.schedule)
        app.primaryScreenChanged.connect(self.schedule)

    def areas(self):
        return [screen.availableGeometry() for screen in QApplication.screens()]

    def schedule(self, *_):
        if not self.pending:
            self.pending = True
            QTimer.singleShot(0, self.recover)

    def eventFilter(self, obj, event):  # noqa: N802 — Qt override
        if obj is self.window and not self.recovering:
            kind = event.type()
            if kind in (QEvent.Type.Move, QEvent.Type.Resize):
                window = self.window
                if (not window.isMinimized() and not native_minimized(window)
                        and titlebar_visible(window.geometry(), self.areas())):
                    if not window.isMaximized() and not window.isFullScreen():
                        self.last_visible = QRect(window.geometry())
                else:
                    self.schedule()
            elif kind in (QEvent.Type.WindowStateChange, QEvent.Type.WindowActivate,
                          QEvent.Type.Show):
                self.schedule()
        return False

    def recover(self):
        self.pending = False
        window = self.window
        if (not window.isVisible() or window.isMinimized()
                or native_minimized(window)):
            return False
        areas = self.areas()
        if not areas or titlebar_visible(window.geometry(), areas):
            return False
        target = QRect(self.last_visible)
        if not titlebar_visible(target, areas):
            area = areas[0]
            width = min(max(target.width(), 720), area.width())
            height = min(max(target.height(), 480), area.height())
            target = QRect(area.x() + (area.width() - width) // 2,
                           area.y() + (area.height() - height) // 2, width, height)
        self.recovering = True
        try:
            window.setGeometry(target)
            window.update()
            self.last_visible = QRect(window.geometry())
        finally:
            self.recovering = False
        return True
