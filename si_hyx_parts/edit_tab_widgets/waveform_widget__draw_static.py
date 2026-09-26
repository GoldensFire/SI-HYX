# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""WaveformWidget: _draw_static. Public namespace: edit_tab_widgets."""
import edit_tab_widgets as _api


def _draw_static(self, painter, w, h):
    """Draw all static elements (everything except playhead and hover cursor)."""
    mid = h / 2.0

    grad = _api.QLinearGradient(0, 0, 0, h)
    grad.setColorAt(0.0, _api.QColor(30, 30, 46))   # base
    grad.setColorAt(1.0, _api.QColor(24, 24, 37))   # mantle
    painter.fillRect(0, 0, w, h, _api.QBrush(grad))

    painter.setPen(_api.QPen(_api.QColor(69, 71, 90), 1))  # surface1
    painter.drawLine(0, int(mid), w, int(mid))

    if self.loading_text:
        dots = "." * self._anim_dots
        txt = f"{self.loading_text}{dots}"
        painter.setPen(_api.QPen(_api.QColor(137, 180, 250)))  # blue
        font = painter.font()
        font.setPointSize(10)
        font.setFamily("Segoe UI" if _api.os.name == 'nt' else "SF Pro Display")
        painter.setFont(font)
        painter.drawText(_api.QRect(0, 0, w, h), _api.Qt.AlignmentFlag.AlignCenter, txt)
        return

    visible_duration = max(0.001, self.duration / self.zoom)

    def time_to_x(t):
        rel = (t - self.view_offset) / visible_duration
        return int(rel * w)

    if self.disp_samples and self.duration > 0:
        n = len(self.disp_samples)
        scale_bg = (h / 2) * 0.86
        for i in range(0, w):
            t = self.view_offset + (i / max(1, w)) * visible_duration
            if t > self.duration:
                break  # за пределами клипа (при отдалении zoom<1) — пусто
            idx = int((t / self.duration) * n)
            idx = max(0, min(n - 1, idx))
            val = self.disp_samples[idx]
            v = val * 0.92
            y1 = int(mid - v * scale_bg)
            y2 = int(mid + v * scale_bg)
            alpha = int(110 + val * 70)
            painter.setPen(_api.QPen(_api.QColor(108, 117, 161, alpha)))  # muted blue/overlay
            painter.drawLine(i, y1, i, y2)
    else:
        if self.duration > 0:
            painter.setPen(_api.QPen(_api.QColor(_api.C["text3"])))
            font = painter.font(); font.setPointSize(9)
            painter.setFont(font)
            painter.drawText(_api.QRect(0, 0, w, h), _api.Qt.AlignmentFlag.AlignCenter, "Нет аудио данных")
        else:
            painter.setPen(_api.QPen(_api.QColor(_api.C["text3"])))
            font = painter.font(); font.setPointSize(10)
            painter.setFont(font)
            painter.drawText(_api.QRect(0, 0, w, h), _api.Qt.AlignmentFlag.AlignCenter,
                             "Перетащите видео или аудио файл сюда")

    painter.setPen(_api.QPen(_api.QColor(_api.C["border"]), 1))
    painter.drawLine(0, 0, w, 0)
    painter.drawLine(0, h - 1, w, h - 1)

    if self.duration <= 0:
        return

    x_in  = time_to_x(self.in_s)
    x_out = time_to_x(self.out_s)
    if x_out < x_in:
        x_in, x_out = x_out, x_in

    sel_w = max(1, x_out - x_in)
    painter.setBrush(_api.QBrush(_api.QColor(137, 180, 250, 28)))  # blue selection wash
    painter.setPen(_api.Qt.PenStyle.NoPen)
    painter.drawRect(x_in, 0, sel_w, h)

    if self.disp_samples and self.duration > 0:
        n = len(self.disp_samples)
        scale_sel = (h / 2) * 0.92
        left_i = max(0, x_in); right_i = min(w - 1, x_out)
        for i in range(left_i, right_i + 1):
            t = self.view_offset + (i / max(1, w)) * visible_duration
            idx = int((t / self.duration) * n)
            if idx >= n:
                break
            val = self.disp_samples[idx]
            v = val * 1.04
            y1 = int(mid - v * scale_sel)
            y2 = int(mid + v * scale_sel)
            alpha = int(180 + val * 60)
            painter.setPen(_api.QPen(_api.QColor(137, 180, 250, alpha)))  # blue
            painter.drawLine(i, y1, i, y2)

    painter.setPen(_api.QPen(_api.QColor(_api.C["red"]), 2))
    painter.drawLine(x_in, 0, x_in, h)
    painter.setPen(_api.QPen(_api.QColor(_api.C["green"]), 2))
    painter.drawLine(x_out, 0, x_out, h)

    handle_r = max(5, int(h * 0.055))
    painter.setBrush(_api.QBrush(_api.QColor(_api.C["red"])))
    painter.setPen(_api.QPen(_api.QColor(_api.C["bg"]), 1))
    painter.drawEllipse(_api.QPoint(x_in, int(mid)), handle_r, handle_r)
    painter.setBrush(_api.QBrush(_api.QColor(_api.C["green"])))
    painter.setPen(_api.QPen(_api.QColor(_api.C["bg"]), 1))
    painter.drawEllipse(_api.QPoint(x_out, int(mid)), handle_r, handle_r)

    painter.setPen(_api.QPen(_api.QColor(_api.C["text"])))
    font = painter.font(); font.setPointSize(6); font.setBold(True)
    painter.setFont(font)
    fm = _api.QFontMetrics(font)
    for label, x_pos, col in [("I", x_in, _api.C["red"]), ("O", x_out, _api.C["green"])]:
        lw = fm.horizontalAdvance(label)
        painter.setPen(_api.QPen(_api.QColor(col)))
        painter.drawText(x_pos - lw // 2, int(mid) + fm.ascent() // 2, label)

def paintEvent(self, event):
    painter = _api.QPainter(self)
    painter.setRenderHint(_api.QPainter.RenderHint.Antialiasing)
    w = self.width(); h = self.height()

    # Cache key covers everything that affects static drawing.
    # Playhead and hover cursor are drawn dynamically on top.
    # Кэш рисуется в ФИЗИЧЕСКИХ пикселях экрана: картинка w×h при масштабе
    # Windows 125 % растягивалась, и текст на таймлайне выходил мыльным.
    dpr = max(1.0, float(self.devicePixelRatioF()))
    cache_key = (w, h, dpr, id(self.samples), len(self.samples),
                 self.duration, self.zoom, self.view_offset,
                 self.in_s, self.out_s, self.loading_text, self._anim_dots)
    if self._cache is None or self._cache_key != cache_key:
        self._cache = _api.QPixmap(max(1, round(w * dpr)), max(1, round(h * dpr)))
        self._cache.setDevicePixelRatio(dpr)
        self._cache_key = cache_key
        cp = _api.QPainter(self._cache)
        cp.setRenderHint(_api.QPainter.RenderHint.Antialiasing)
        cp.setRenderHint(_api.QPainter.RenderHint.TextAntialiasing)
        self._draw_static(cp, w, h)
        cp.end()

    painter.drawPixmap(0, 0, self._cache)

    if self.loading_text or self.duration <= 0:
        return

    visible_duration = max(0.001, self.duration / self.zoom)

    def time_to_x(t):
        rel = (t - self.view_offset) / visible_duration
        return int(rel * w)

    # Playhead
    if 0.0 <= self.playhead_s <= self.duration:
        vis_end = self.view_offset + visible_duration
        if self.view_offset <= self.playhead_s <= vis_end:
            x_ph = time_to_x(self.playhead_s)
            painter.setPen(_api.QPen(_api.QColor(_api.C["playhead"]), 2, _api.Qt.PenStyle.SolidLine))
            painter.drawLine(x_ph, 0, x_ph, h)
            path = _api.QPainterPath()
            path.moveTo(x_ph - 5, 0)
            path.lineTo(x_ph + 5, 0)
            path.lineTo(x_ph, 8)
            path.closeSubpath()
            painter.setBrush(_api.QBrush(_api.QColor(_api.C["playhead"])))
            painter.setPen(_api.Qt.PenStyle.NoPen)
            painter.drawPath(path)

    # Hover cursor
    if self.hover_x is not None:
        hx = int(self.hover_x)
        painter.setPen(_api.QPen(_api.QColor(255, 255, 255, 40), 1, _api.Qt.PenStyle.DotLine))
        painter.drawLine(hx, 0, hx, h)

# ── Mouse events ───────────────────────────────────────────────────────
def mousePressEvent(self, ev):
    # ПКМ — не сик/перетаскивание, а контекстное меню обрезки (его поднимает
    # customContextMenuRequested). Иначе правый клик дёргал бы плейхед.
    if ev.button() == _api.Qt.MouseButton.RightButton:
        ev.ignore(); return
    # Забираем клавиатурный фокус НА СЕБЯ: метод переопределён и не зовёт
    # super().mousePressEvent(), поэтому штатный перехват фокуса по ClickFocus
    # не срабатывает, и фокус оставался на нативной видео-поверхности
    # (исключена из WidgetWithChildrenShortcut) → Ctrl+Z/Ctrl+Y после
    # перетаскивания полоски не доходили до undo/redo.
    self.setFocus(_api.Qt.FocusReason.MouseFocusReason)
    try:
        x = ev.position().x()
    except Exception:
        x = ev.x()
    if self.duration <= 0:
        self.seekRequested.emit(0.0); return
    w = max(1, self.width()); x = max(0, min(w, x))

    def time_to_x_local(t):
        visible = max(0.001, self.duration / self.zoom)
        rel = (t - self.view_offset) / visible
        return int(rel * w)

    x_in  = time_to_x_local(self.in_s)
    x_out = time_to_x_local(self.out_s)
    threshold = 8
    modifiers = _api.QApplication.keyboardModifiers()
    if not (modifiers & _api.Qt.KeyboardModifier.ControlModifier):
        if abs(x - x_in) <= threshold:
            self.interactionStarted.emit()
            self.dragging = 'in'; self.drag_start_x = x; self.orig_in = self.in_s
            self.show_tooltip_for_pos(ev); return
        if abs(x - x_out) <= threshold:
            self.interactionStarted.emit()
            self.dragging = 'out'; self.drag_start_x = x; self.orig_out = self.out_s
            self.show_tooltip_for_pos(ev); return
        left = min(x_in, x_out); right = max(x_in, x_out)
        if (right - left) > (threshold * 3) and (left + threshold < x < right - threshold):
            self.interactionStarted.emit()
            self.dragging = 'maybe_move'; self.drag_start_x = x
            self.orig_in = self.in_s; self.orig_out = self.out_s
            self.show_tooltip_for_pos(ev); return
    rel = x / w
    t = self.view_offset + rel * max(0.001, self.duration / self.zoom)
    t = max(0.0, min(self.duration, t))
    self.seekRequested.emit(t)

def mouseMoveEvent(self, ev):
    try:
        mx = ev.position().x(); gpos = ev.globalPosition()
    except Exception:
        mx = ev.x(); gpos = ev.globalPos()
    self.hover_x = mx
    if self.dragging and self.duration > 0:
        w = max(1, self.width()); mx = max(0, min(w, mx))
        if self.dragging == 'maybe_move':
            if abs(mx - (self.drag_start_x if self.drag_start_x is not None else mx)) < 6:
                self.show_tooltip_at_global_pos(gpos, self.hover_time_from_x(mx))
                self.update(); return
            else:
                self.dragging = 'move'; self.orig_in = self.in_s; self.orig_out = self.out_s
        visible = max(0.001, self.duration / self.zoom)
        if self.dragging == 'in':
            t = self.view_offset + (mx / w) * visible
            new_in = max(0.0, min(t, self.out_s - (1.0 / 1000.0)))
            self.in_s = new_in
            self.inSetRequested.emit(self.in_s); self.selectionChanged.emit(self.in_s, self.out_s)
        elif self.dragging == 'out':
            t = self.view_offset + (mx / w) * visible
            new_out = min(self.duration, max(t, self.in_s + (1.0 / 1000.0)))
            self.out_s = new_out
            self.outSetRequested.emit(self.out_s); self.selectionChanged.emit(self.in_s, self.out_s)
        elif self.dragging == 'move':
            start_t = self.view_offset + ((self.drag_start_x if self.drag_start_x is not None else mx) / w) * visible
            cur_t   = self.view_offset + (mx / w) * visible
            shift = cur_t - start_t
            new_in = self.orig_in + shift; new_out = self.orig_out + shift
            if new_in < 0:
                shift_c = -new_in; new_in += shift_c; new_out += shift_c
            if new_out > self.duration:
                shift_c = new_out - self.duration; new_in -= shift_c; new_out -= shift_c
            self.in_s = new_in; self.out_s = new_out
            self.inSetRequested.emit(self.in_s)
            self.outSetRequested.emit(self.out_s)
            self.selectionChanged.emit(self.in_s, self.out_s)
        self.show_tooltip_at_global_pos(gpos, self.hover_time_from_x(mx))
        self.update(); return
    self.update()

def mouseReleaseEvent(self, ev):
    try:
        rx = ev.position().x()
    except Exception:
        rx = ev.x()
    if self.dragging == 'maybe_move':
        w = max(1, self.width()); rx = max(0, min(w, rx))
        visible = max(0.001, self.duration / self.zoom)
        t = self.view_offset + (rx / w) * visible
        t = max(0.0, min(self.duration, t))
        self.playSeekRequested.emit(t)
    self.dragging = None; self.drag_start_x = None
    self.orig_in = 0.0; self.orig_out = 0.0
    _api.QToolTip.hideText(); self.tooltip_visible = False

def leaveEvent(self, ev):
    self.hover_x = None; _api.QToolTip.hideText(); self.tooltip_visible = False; self.update()

def hover_time_from_x(self, x):
    w = max(1, self.width())
    rel = max(0.0, min(1.0, x / w))
    visible = max(0.001, self.duration / self.zoom)
    return self.view_offset + rel * visible

def show_tooltip_for_pos(self, ev):
    try:
        gpos = ev.globalPosition(); x = ev.position().x()
    except Exception:
        gpos = ev.globalPos(); x = ev.x()
    t = self.hover_time_from_x(x)
    self.show_tooltip_at_global_pos(gpos, t)
