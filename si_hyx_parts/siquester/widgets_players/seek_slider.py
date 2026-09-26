# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""SeekSlider. Public namespace: siquester.widgets_players."""
import siquester.widgets_players as _api


class SeekSlider(_api.QSlider):
    """QSlider that emits user_seek(value) on any mouse interaction."""
    user_seek    = _api.pyqtSignal(int)
    user_release = _api.pyqtSignal()   # emitted when mouse button is released

    def __init__(self, parent=None):
        super().__init__(_api.Qt.Orientation.Horizontal, parent)
        self._pressing = False

    def _val_from_x(self, x: float) -> int:
        frac = max(0.0, min(1.0, x / max(1, self.width())))
        return int(frac * (self.maximum() - self.minimum())) + self.minimum()

    def mousePressEvent(self, e):
        if e.button() == _api.Qt.MouseButton.LeftButton:
            self._pressing = True
            val = self._val_from_x(e.position().x())
            self.setValue(val)
            self.user_seek.emit(val)
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._pressing:
            val = self._val_from_x(e.position().x())
            self.setValue(val)
            self.user_seek.emit(val)
        else:
            super().mouseMoveEvent(e)

    def wheelEvent(self, e):
        e.ignore()   # never let scroll wheel change seek position

    def mouseReleaseEvent(self, e):
        if e.button() == _api.Qt.MouseButton.LeftButton:
            self._pressing = False
            val = self._val_from_x(e.position().x())
            self.setValue(val)
            self.user_seek.emit(val)
            self.user_release.emit()
        else:
            super().mouseReleaseEvent(e)

SeekSlider.__module__ = _api.__name__
_api.SeekSlider = SeekSlider
