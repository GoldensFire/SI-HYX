# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Present a reused tooltip window only after its new frame has been painted."""
from weakref import ref

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication, QLabel


def source_is_current(owner, point=None):
    """Reject late help events, including another cell in the same viewport."""
    if QApplication.activePopupWidget() is not None:
        return False
    cursor = QCursor.pos()
    if point is not None and (cursor - point).manhattanLength() > 2:
        return False
    try:
        if not owner.isVisible():
            return False
        current = QApplication.widgetAt(cursor)
        while current is not None:
            if current is owner:
                return True
            # A child's own tip takes precedence over its container's tip.
            if current.property("infoTipText") or current.toolTip():
                return False
            current = current.parentWidget()
    except RuntimeError:  # The source was deleted while an event was queued.
        pass
    return False


def _prepare_frame(self, owner, point=None, managed=False):
    # Changing QLabel.text() does not repaint the native backing store. Even
    # repaint() immediately after show() can do nothing until the window is
    # exposed. Mask it BEFORE setText/resize/move, including visible updates.
    self.setWindowOpacity(0.0)
    self._frame_version += 1
    self._awaiting_frame = True
    self._source_ref = ref(owner) if owner is not None else None
    self._source_point = point
    self._hover_managed = managed


def paintEvent(self, event):  # noqa: N802 — Qt override
    QLabel.paintEvent(self, event)
    if self._awaiting_frame:
        version = self._frame_version
        # Qt ends painting and flushes the backing store AFTER paintEvent.
        # Reveal on the next event-loop turn, never from inside painting.
        QTimer.singleShot(0, lambda: self._reveal_frame(version))


def _reveal_frame(self, version):
    if (version != self._frame_version or not self._awaiting_frame
            or not self.isVisible()):
        return
    if self._source_ref is not None:
        owner = self._source_ref()
        if owner is None or not source_is_current(owner, self._source_point):
            self.hide()
            return
        if self._hover_managed:
            from widgets import HoverTipManager
            current, text, _ = HoverTipManager._tip_at(QCursor.pos())
            if current is not owner or text != self.text():
                self.hide()
                return
    self._awaiting_frame = False
    self.setWindowOpacity(1.0)


def hideEvent(self, event):  # noqa: N802 — Qt override
    # A queued reveal from the previous hover must not reveal another frame.
    self._frame_version += 1
    self._awaiting_frame = False
    self.setWindowOpacity(0.0)
    QLabel.hideEvent(self, event)
