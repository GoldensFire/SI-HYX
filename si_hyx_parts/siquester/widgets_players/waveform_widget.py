# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""WaveformWidget. Public namespace: siquester.widgets_players."""
import siquester.widgets_players as _api


class WaveformWidget(_api.QWidget):
    """Waveform bars that always reflect real amplitude — color animates during playback."""
    clicked_at = _api.pyqtSignal(float)  # 0..1 fraction

    def __init__(self, bars: list, parent=None):
        super().__init__(parent)
        self._bars = bars or [0.3] * 50
        self._phase = 0.0
        self._playing = False
        self._progress = 0.0
        self._timer = _api.QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        self.setFixedHeight(38)
        self.setCursor(_api.Qt.CursorShape.PointingHandCursor)

    def set_playing(self, playing: bool):
        self._playing = playing
        if playing: self._timer.start()
        else: self._timer.stop(); self.update()

    def set_bars(self, bars: list):
        """Safe to call only from the main thread via a signal."""
        self._bars = bars
        self.update()

    def set_progress(self, frac: float):
        self._progress = max(0.0, min(1.0, frac)); self.update()

    def _tick(self):
        self._phase += 0.18; self.update()

    def paintEvent(self, _):
        p = _api.QPainter(self); p.setRenderHint(_api.QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        n = len(self._bars)
        if not n: p.end(); return
        gap = 2.0
        bar_w = max(2.0, (w - gap * (n - 1)) / n)
        off = (w - (bar_w * n + gap * (n - 1))) / 2
        inner_h = h - 8
        for i, amp in enumerate(self._bars):
            x = off + i * (bar_w + gap)
            played = (i / n) < self._progress
            # Bar height always reflects actual amplitude — no height animation
            bh = max(3.0, amp * inner_h + 2)
            y = (h - bh) / 2
            # Color: subtle pulse on unplayed bars during playback
            if played:
                color = _api.QColor("#cba6f7")
            elif self._playing:
                # Gentle brightness pulse on unplayed bars to show activity
                pulse = _api.math.sin(self._phase + i * 0.3) * 0.15 + 0.85
                base = int(0x30 * pulse); color = _api.QColor(base, int(0x22 * pulse), int(0x50 * pulse))
            else:
                color = _api.QColor("#313244")
            r = min(bar_w / 2, bh / 2, 2.5)
            path = _api.QPainterPath()
            path.addRoundedRect(_api.QRectF(x, y, bar_w, bh), r, r)
            p.fillPath(path, _api.QBrush(color))
        p.end()

    def mousePressEvent(self, e):
        self.clicked_at.emit(max(0.0, min(1.0, e.position().x() / self.width())))
        super().mousePressEvent(e)

WaveformWidget.__module__ = _api.__name__
_api.WaveformWidget = WaveformWidget

class _AspectWidget(_api.QWidget):
    """Container that enforces a 16:9 aspect ratio via Qt's layout hint system.
    hasHeightForWidth() / heightForWidth() tell the layout engine to compute
    the height from the width in one pass — no setMinimumHeight feedback loops.
    """
    def __init__(self, child: _api.QWidget, parent=None):
        super().__init__(parent)
        self.setSizePolicy(_api._Expand, _api._Pref)
        self._child = child
        child.setParent(self)
        child.move(0, 0)

    def hasHeightForWidth(self) -> bool: return True
    def heightForWidth(self, w: int) -> int: return max(1, w * 9 // 16)

    def sizeHint(self):
        w = self.width() or 400
        return _api.QSize(w, self.heightForWidth(w))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Fill child exactly — no layout engine involved, no feedback
        self._child.setGeometry(0, 0, self.width(), self.height())

_AspectWidget.__module__ = _api.__name__
_api._AspectWidget = _AspectWidget
