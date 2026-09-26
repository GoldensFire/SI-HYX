# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_SubtitleTimeline. Public namespace: edit_tab_widgets."""
import edit_tab_widgets as _api


class _SubtitleTimeline(_api.QWidget):
    """Таймлайн реплик субтитров для SubtitleCreatorDialog: линейка с засечками
    времени, плейхед и дорожка с перетаскиваемыми/растягиваемыми блоками — по
    одному на реплику. Обобщение единственной пары IN/OUT из WaveformWidget
    (coord-математика/hit-testing/Ctrl+wheel-зум скопированы оттуда) на N
    произвольных интервалов с ограничением о несоседних столкновениях."""

    seekRequested       = _api.pyqtSignal(float)
    cueChanged          = _api.pyqtSignal(int, float, float)   # index, start, end
    cueSelected         = _api.pyqtSignal(int)
    viewChanged         = _api.pyqtSignal(float, float)        # offset, visible_duration
    interactionStarted  = _api.pyqtSignal()   # начало drag'а блока — снимок для undo

    RULER_H = 20
    _EDGE_TOL = 8
    _ROW_H = 26
    _ROW_GAP = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.duration = 0.0     # длина ВИДИМОГО диапазона (не всего видео)
        self.range_start = 0.0  # начало диапазона (абсолютное время исходника)
        self.cues = []          # [(start, end)] — только тайминг, без текста/стиля
        self.selected = -1
        self.playhead_s = 0.0
        self.zoom = 1.0
        self.view_offset = 0.0
        self.setMinimumHeight(self.RULER_H + self._ROW_H + 2 * self._ROW_GAP)
        self.setMouseTracking(True)
        self.setFocusPolicy(_api.Qt.FocusPolicy.ClickFocus)
        self.dragging = None       # None | 'start' | 'end' | 'move' | 'maybe_move'
        self.drag_index = -1
        self.drag_start_x = None
        self.orig_start = 0.0
        self.orig_end = 0.0

    # ── Данные ──────────────────────────────────────────────────────────────
    def set_cues(self, cues):
        self.cues = [(float(s), float(e)) for s, e in cues]
        if self.selected >= len(self.cues):
            self.selected = len(self.cues) - 1
        self.update()

    def set_range(self, start_s, end_s):
        """Ограничивает таймлайн диапазоном [start_s, end_s] (абсолютное время
        исходника) — тем самым, что выделен в Монтаже, а не всем видео."""
        self.range_start = max(0.0, float(start_s))
        self.duration = max(0.001, float(end_s) - self.range_start)
        self.zoom = 1.0
        self.view_offset = self.range_start
        self.update()

    def set_playhead(self, t):
        self.playhead_s = max(0.0, float(t))
        self.update()

    def set_selected(self, idx):
        self.selected = idx
        self.update()

    # ── Коорд. математика (как в WaveformWidget: view_offset/zoom) ──────────
    def _visible(self):
        return max(0.001, self.duration / self.zoom) if self.duration > 0 else 1.0

    def time_to_x(self, t):
        w = max(1, self.width())
        return (t - self.view_offset) / self._visible() * w

    def x_to_time(self, x):
        w = max(1, self.width())
        return self.view_offset + (x / w) * self._visible()

    # ── Рисование ────────────────────────────────────────────────────────────
    def paintEvent(self, ev):
        p = _api.QPainter(self)
        p.fillRect(self.rect(), _api.QColor(_api.C['surface3']))
        self._draw_ruler(p)
        self._draw_cues(p)
        self._draw_playhead(p)
        p.end()

    @staticmethod
    def _nice_tick_step(px_per_s):
        for c in (0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600):
            if c * px_per_s >= 70:
                return c
        return 3600

    def _draw_ruler(self, p):
        w = max(1, self.width())
        p.fillRect(0, 0, w, self.RULER_H, _api.QColor(_api.C['surface2']))
        if self.duration <= 0:
            return
        visible = self._visible()
        step = self._nice_tick_step(w / visible)
        p.setPen(_api.QPen(_api.QColor(_api.C['text3'])))
        t = _api.math.floor(self.view_offset / step) * step
        end_t = self.view_offset + visible + step
        while t <= end_t:
            x = self.time_to_x(t)
            if 0 <= x <= w:
                p.drawLine(int(x), self.RULER_H - 6, int(x), self.RULER_H)
                p.drawText(int(x) + 3, self.RULER_H - 7, _api.s_to_time(max(0.0, t))[:8])
            t += step

    def _draw_cues(self, p):
        y = self.RULER_H + self._ROW_GAP
        w = max(1, self.width())
        for i, (s, e) in enumerate(self.cues):
            x0 = self.time_to_x(s); x1 = self.time_to_x(e)
            if x1 < 0 or x0 > w:
                continue
            r = _api.QRect(int(x0), y, max(2, int(x1 - x0)), self._ROW_H)
            selected = (i == self.selected)
            bg = _api.QColor(_api.C['accent'] if selected else _api.C['wave_sel'])
            bg.setAlpha(230 if selected else 160)
            p.fillRect(r, bg)
            p.setPen(_api.QPen(_api.QColor(_api.C['accent'] if selected else _api.C['border2'])))
            p.drawRect(r)

    def _draw_playhead(self, p):
        if self.duration <= 0:
            return
        x = self.time_to_x(self.playhead_s)
        if 0 <= x <= self.width():
            pen = _api.QPen(_api.QColor(_api.C['playhead'])); pen.setWidth(2)
            p.setPen(pen)
            p.drawLine(int(x), 0, int(x), self.height())

    # ── Hit-testing (по образцу WaveformWidget.mousePressEvent) ─────────────
    def _row_bounds(self):
        top = self.RULER_H + self._ROW_GAP
        return top, top + self._ROW_H

    def _hit_test(self, x, y=None):
        # Блоки реплик рисуются ТОЛЬКО в полосе дорожки (см. _draw_cues) — выше
        # неё линейка времени, ниже пустой остаток фиксированной высоты виджета.
        # Раньше hit-test смотрел только на X, и клик ВЫШЕ/НИЖЕ дорожки (по тем
        # же X-координатам, что и реплика) тоже считался попаданием в блок —
        # кликнуть «просто перейти на этот момент» там было нельзя, вместо
        # этого всегда предлагалось перетащить реплику.
        if y is not None:
            row_top, row_bottom = self._row_bounds()
            if y < row_top or y > row_bottom:
                return -1, None
        for i, (s, e) in enumerate(self.cues):
            x0 = self.time_to_x(s); x1 = self.time_to_x(e)
            if abs(x - x0) <= self._EDGE_TOL:
                return i, 'start'
            if abs(x - x1) <= self._EDGE_TOL:
                return i, 'end'
            if x0 + self._EDGE_TOL < x < x1 - self._EDGE_TOL:
                return i, 'move'
        return -1, None

    def _neighbor_bounds(self, i):
        lo = self.range_start; hi = self.range_start + self.duration
        if i > 0:
            lo = self.cues[i - 1][1]
        if i < len(self.cues) - 1:
            hi = self.cues[i + 1][0]
        return lo, hi

    def mousePressEvent(self, ev):
        if ev.button() == _api.Qt.MouseButton.RightButton:
            ev.ignore(); return
        self.setFocus(_api.Qt.FocusReason.MouseFocusReason)
        x = ev.position().x(); y = ev.position().y()
        if self.duration <= 0:
            return
        idx, mode = self._hit_test(x, y)
        if idx >= 0:
            self.selected = idx
            self.cueSelected.emit(idx)
            self.orig_start, self.orig_end = self.cues[idx]
            self.drag_index = idx
            self.drag_start_x = x
            self.dragging = 'maybe_move' if mode == 'move' else mode
            self.interactionStarted.emit()
            self.update()
            return
        t = max(self.range_start, min(self.range_start + self.duration, self.x_to_time(x)))
        self.seekRequested.emit(t)

    def mouseMoveEvent(self, ev):
        x = ev.position().x(); y = ev.position().y()
        if self.dragging and self.drag_index >= 0:
            if self.dragging == 'maybe_move':
                if abs(x - (self.drag_start_x or x)) < 6:
                    return
                self.dragging = 'move'
            i = self.drag_index
            lo, hi = self._neighbor_bounds(i)
            s0, e0 = self.cues[i]
            if self.dragging == 'start':
                t = max(lo, min(self.x_to_time(x), e0 - 0.05))
                self.cues[i] = (t, e0)
            elif self.dragging == 'end':
                t = min(hi, max(self.x_to_time(x), s0 + 0.05))
                self.cues[i] = (s0, t)
            elif self.dragging == 'move':
                shift = self.x_to_time(x) - self.x_to_time(self.drag_start_x)
                ns = self.orig_start + shift; ne = self.orig_end + shift
                if ns < lo:
                    d = lo - ns; ns += d; ne += d
                if ne > hi:
                    d = ne - hi; ns -= d; ne -= d
                self.cues[i] = (ns, ne)
            s, e = self.cues[i]
            self.cueChanged.emit(i, s, e)
            self.update()
            return
        idx, mode = self._hit_test(x, y)
        cur = {'start': _api.Qt.CursorShape.SizeHorCursor, 'end': _api.Qt.CursorShape.SizeHorCursor,
               'move': _api.Qt.CursorShape.SizeAllCursor}.get(mode)
        if cur is not None:
            self.setCursor(cur)
        else:
            self.unsetCursor()

    def mouseReleaseEvent(self, ev):
        self.dragging = None; self.drag_index = -1; self.drag_start_x = None

    def leaveEvent(self, ev):
        self.unsetCursor()

    # ── Зум (Ctrl+колесо, как в WaveformWidget) ──────────────────────────────
    def wheelEvent(self, event):
        if not (_api.QApplication.keyboardModifiers() & _api.Qt.KeyboardModifier.ControlModifier):
            event.ignore(); return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        cursor_x = event.position().x()
        w = max(1, self.width())
        t_at_cursor = self.view_offset + (cursor_x / w) * self._visible()
        factor = 1.15 if delta > 0 else (1.0 / 1.15)
        self.set_zoom(self.zoom * factor, anchor_t=t_at_cursor, anchor_frac=cursor_x / w)
        event.accept()

    def set_zoom(self, zoom, anchor_t=None, anchor_frac=0.5):
        self.zoom = max(0.25, min(zoom, 200.0))
        visible_after = self._visible()
        if anchor_t is not None:
            new_view = anchor_t - anchor_frac * visible_after
        else:
            new_view = self.view_offset
        lo = self.range_start
        new_view = max(lo, min(new_view, lo + max(0.0, self.duration - visible_after)))
        self.view_offset = new_view
        self.viewChanged.emit(self.view_offset, visible_after)
        self.update()

    def set_view_offset(self, offset):
        visible = self._visible()
        lo = self.range_start
        self.view_offset = max(lo, min(offset, lo + max(0.0, self.duration - visible)))
        self.viewChanged.emit(self.view_offset, visible)
        self.update()

_SubtitleTimeline.__module__ = _api.__name__
_api._SubtitleTimeline = _SubtitleTimeline

def slider_value_at(slider, x):
    """Значение горизонтального QSlider в точке x (координаты виджета).

    Стандартный QSlider по клику лишь «подкрадывается» к курсору page-step'ами;
    чтобы ручка прыгала РОВНО в точку клика, значение надо посчитать самим по
    геометрии желоба и ручки. Общий помощник для полосы воспроизведения
    (SeekSlider) и ползунка громкости (VolumeSlider) — раньше эта арифметика
    жила только в SeekSlider."""
    opt = _api.QStyleOptionSlider()
    slider.initStyleOption(opt)
    groove = slider.style().subControlRect(
        _api.QStyle.ComplexControl.CC_Slider, opt,
        _api.QStyle.SubControl.SC_SliderGroove, slider)
    handle = slider.style().subControlRect(
        _api.QStyle.ComplexControl.CC_Slider, opt,
        _api.QStyle.SubControl.SC_SliderHandle, slider)
    span = (groove.right() - groove.left() - handle.width())
    pos = x - groove.left() - handle.width() // 2
    if span <= 0:
        return slider.minimum()
    return _api.QStyle.sliderValueFromPosition(
        slider.minimum(), slider.maximum(), pos, span)

slider_value_at.__module__ = _api.__name__
_api.slider_value_at = slider_value_at
