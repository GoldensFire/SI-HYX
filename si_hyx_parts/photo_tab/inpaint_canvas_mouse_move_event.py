# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""InpaintCanvas: mouseMoveEvent. Public namespace: photo_tab."""
import photo_tab as _api


def mouseMoveEvent(self, ev):
    self._mouse_w = ev.position()
    if self._panning and self._pan_start is not None:
        d = ev.position() - self._pan_start
        self._off = self._off_start + d
        self._clamp_off()
        self._update_crop_buttons()
        self.update()
        return
    if self.img_bgr is None:
        self.update()
        return
    # Изменение размера наложенного изображения тяганием ручки.
    if self._pending_resize and (ev.buttons() & _api.Qt.MouseButton.LeftButton):
        keep = bool(ev.modifiers() & _api.Qt.KeyboardModifier.ShiftModifier)
        self._resize_pending(self._w2i(ev.position()), keep_aspect=keep)
        self.update()
        return
    # Перетаскивание плавающего объекта (фигура/текст/картинка).
    if self._pending_move and (ev.buttons() & _api.Qt.MouseButton.LeftButton):
        ipt = self._w2i(ev.position())
        if self._pending_anchor is not None:
            self._translate_pending(ipt - self._pending_anchor)
        self._pending_anchor = ipt
        self.update()
        return
    if self._shape_drawing:
        self._shape_cur = self._w2i(ev.position())
        self.update()
        return
    # Наведение на плавающий объект: курсор-стрелки на ручках размера, «лапа»
    # внутри. Работает в любом инструменте, пока есть незакреплённый объект
    # (а в TOOL_MOVE — ещё и стрелка вне объекта).
    if self._pending is not None and not self._pending_move:
        handle = self._pending_handle_at(ev.position())
        if handle in ('tl', 'tr', 'bl', 'br', 't', 'b', 'l', 'r'):
            self.setCursor(self._crop_cursor(handle))
            self.update()
            return
        if handle == 'move':
            self.setCursor(_api.Qt.CursorShape.SizeAllCursor)
            self.update()
            return
        if self._tool == self.TOOL_MOVE:
            self.setCursor(_api.Qt.CursorShape.OpenHandCursor)
            self.update()
            return
    if self._tool == self.TOOL_MOVE:
        # Пустое место под «Курсором» — рука (готов панорамировать, как в Photoshop).
        self.setCursor(_api.Qt.CursorShape.OpenHandCursor)
        self.update()
        return
    # Пока не рисуем — отслеживаем Alt для подсказки «пипетка» у кисти.
    if not self._painting:
        self._set_alt(bool(ev.modifiers() & _api.Qt.KeyboardModifier.AltModifier))
    if self._painting:
        self._paint_to(self._w2i(ev.position()))
        self.update()
        return
    if self._tool == self.TOOL_CROP:
        if self._crop_drag and (ev.buttons() & _api.Qt.MouseButton.LeftButton):
            self._drag_crop(self._w2i(ev.position()))
            self._update_crop_buttons()
        else:
            # Подсказка курсором: над какой ручкой находимся.
            self.setCursor(self._crop_cursor(
                self._crop_handle_at(ev.position())))
    self.update()

def mouseDoubleClickEvent(self, ev):
    if (ev.button() == _api.Qt.MouseButton.LeftButton and self._pending is not None
            and self._pending.get('kind') == 'text'):
        self.edit_pending_text(self._w2i(ev.position()))
        return
    super(_api.InpaintCanvas, self).mouseDoubleClickEvent(ev)

def mouseReleaseEvent(self, ev):
    _default_cursor = (_api.Qt.CursorShape.OpenHandCursor if self._tool == self.TOOL_MOVE
                       else _api.Qt.CursorShape.CrossCursor)
    # Любое панорамирование (средняя кнопка ИЛИ «Курсор»-рука) завершаем здесь.
    if self._panning:
        self._panning = False
        self.setCursor(_default_cursor)
        return
    # Завершили изменение размера наложенного изображения.
    if self._pending_resize and ev.button() == _api.Qt.MouseButton.LeftButton:
        self._pending_resize = None
        self._pending_rs_rect0 = None
        self.setCursor(_default_cursor)
        self.update()
        return
    # Завершили перетаскивание плавающего объекта — он остаётся выделенным.
    if self._pending_move and ev.button() == _api.Qt.MouseButton.LeftButton:
        self._pending_move = False
        self._pending_anchor = None
        self.setCursor(_default_cursor)
        self.update()
        return
    if self._shape_drawing and ev.button() == _api.Qt.MouseButton.LeftButton:
        self._shape_cur = self._w2i(ev.position())
        a, b = self._shape_start, self._shape_cur
        self._shape_drawing = False
        self._shape_start = self._shape_cur = None
        self._make_pending_shape(a, b)
        self.update()
        return
    if self._painting:
        self._painting = False
        self._last_img_pt = None
        was_mask = self._tool == self.TOOL_MASK
        # Ластик стирает мазки кисти (слой краски) — пересчитываем флаг краски.
        if self._tool == self.TOOL_ERASE:
            self._recompute_paint_flag()
        if self._tool == self.TOOL_BLUR:
            self._end_blur_stroke()
            self.imageChanged.emit()
        # Кисть/ластик могли изменить _has_paint — сигналим вкладке пере-включить
        # кнопки (кнопка «Ластик» неактивна, пока нечего стирать, см. _refresh_enabled).
        if self._tool in (self.TOOL_BRUSH, self.TOOL_ERASE):
            self.imageChanged.emit()
        # Завершено выделение для удаления — сигналим вкладке: убрать закрашенное
        # (как Photoshop Spot Healing Brush: пометил — сразу убралось).
        if was_mask and self._has_strokes:
            self.strokeFinished.emit()
    if self._crop_drag:
        self._crop_drag = None

def leaveEvent(self, ev):
    self._mouse_w = None
    self.update()
    super(_api.InpaintCanvas, self).leaveEvent(ev)

def wheelEvent(self, ev):
    if self.img_bgr is None:
        return
    # Зум мышью — забираем фокус холсту, чтобы WASD/стрелки сразу панорамировали.
    self.setFocus(_api.Qt.FocusReason.MouseFocusReason)
    dy = ev.angleDelta().y()
    if dy == 0:
        return
    factor = 1.2 if dy > 0 else 1 / 1.2
    old = self._scale
    new = max(0.02, min(40.0, old * factor))
    if new == old:
        return
    cur = ev.position()
    # Зум вокруг курсора: точка под курсором остаётся на месте.
    self._off = _api.QPointF(cur.x() - (cur.x() - self._off.x()) * (new / old),
                        cur.y() - (cur.y() - self._off.y()) * (new / old))
    self._scale = new
    self._user_zoomed = True
    self._clamp_off()
    self._update_crop_buttons()
    self.update()

def _pan_by(self, dx, dy):
    """Сдвигает «камеру» (видимую область) на dx,dy экранных px. Двигаем только
        по оси, где картинка больше холста (при приближении), иначе не даём ей
        бесцельно ездить по пустому полю."""
    if self.img_bgr is None:
        return
    cw, ch = self._content_size()
    if dx and cw <= self.width():
        dx = 0
    if dy and ch <= self.height():
        dy = 0
    if not dx and not dy:
        return
    self._off = _api.QPointF(self._off.x() + dx, self._off.y() + dy)
    self._user_zoomed = True
    self._clamp_off()
    self._update_crop_buttons()
    self.update()

def keyPressEvent(self, ev):
    k = ev.key()
    mods = ev.modifiers()
    ctrl = bool(mods & _api.Qt.KeyboardModifier.ControlModifier)
    shift = bool(mods & _api.Qt.KeyboardModifier.ShiftModifier)
    # WASD/стрелки — панорамирование при приближении (без Ctrl, чтобы не
    # конфликтовать с Ctrl+Z/Y). Шаг крупнее с Shift. WASD читаются по физической
    # клавише → работают на любой раскладке (см. _pan_dir_from_event).
    pan_dir = _api._pan_dir_from_event(ev)
    if not ctrl and pan_dir is not None and self.img_bgr is not None:
        step = 120 if shift else 50
        sx, sy = pan_dir
        self._pan_by(sx * step, sy * step)
        return
    if k == _api.Qt.Key.Key_Alt:
        self._set_alt(True)
    if k == _api.Qt.Key.Key_Escape and self._pending is not None:
        # Esc убирает незакреплённый объект (фигуру/текст) без вжигания.
        self.cancel_pending()
    elif k in (_api.Qt.Key.Key_Return, _api.Qt.Key.Key_Enter) and self._pending is not None:
        # Enter закрепляет плавающий объект.
        self._commit_pending()
    elif k == _api.Qt.Key.Key_Escape and self._tool == self.TOOL_CROP:
        self.cancel_crop()
    elif k in (_api.Qt.Key.Key_Return, _api.Qt.Key.Key_Enter) and self.has_crop():
        self.apply_crop()
    elif k == _api.Qt.Key.Key_Y and ctrl:
        self.redo()
    elif k == _api.Qt.Key.Key_Z and ctrl and shift:
        self.redo()
    elif k == _api.Qt.Key.Key_Z and ctrl:
        self.undo()
    else:
        super(_api.InpaintCanvas, self).keyPressEvent(ev)

def keyReleaseEvent(self, ev):
    if ev.key() == _api.Qt.Key.Key_Alt:
        self._set_alt(False)
    super(_api.InpaintCanvas, self).keyReleaseEvent(ev)

def resizeEvent(self, ev):
    if self.img_bgr is not None and not self._user_zoomed:
        self._fit()
    self._update_crop_buttons()
    super(_api.InpaintCanvas, self).resizeEvent(ev)
