# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""InpaintCanvas: _resize_pending. Public namespace: photo_tab."""
import photo_tab as _api


def _resize_pending(self, ipt, keep_aspect=False):
    """Меняет размер наложенного изображения тяганием ручки self._pending_resize.
        ipt — позиция мыши в коорд. изображения. keep_aspect (Shift) — сохранять
        пропорции (для угловых ручек)."""
    if (self._pending is None or self._pending_resize is None
            or self._pending_rs_rect0 is None):
        return
    d = self._pending_resize
    r0 = self._pending_rs_rect0
    l, t, r, b = r0.left(), r0.top(), r0.right(), r0.bottom()
    minsz = 12.0
    x, y = ipt.x(), ipt.y()
    if 'l' in d: l = min(x, r - minsz)
    if 'r' in d: r = max(x, l + minsz)
    if 't' in d: t = min(y, b - minsz)
    if 'b' in d: b = max(y, t + minsz)
    new_w = r - l; new_h = b - t
    # Пропорции (Shift) для угловых ручек: подгоняем по доминирующей оси,
    # удерживая противоположный угол на месте.
    if keep_aspect and d in ('tl', 'tr', 'bl', 'br') and r0.width() > 0 and r0.height() > 0:
        ar = r0.width() / r0.height()
        if new_w / max(1e-6, new_h) > ar:
            new_w = new_h * ar
        else:
            new_h = new_w / ar
        if 'l' in d: l = r - new_w
        else: r = l + new_w
        if 't' in d: t = b - new_h
        else: b = t + new_h
    self._pending['pos'] = _api.QPointF(l, t)
    self._pending['w'] = max(minsz, new_w)
    self._pending['h'] = max(minsz, new_h)

def _bake_object(self, obj):
    """Вжигает объект в изображение (с записью в историю отмены)."""
    if self.img_bgr is None:
        return
    self._push_history()
    img = _api.np_bgr_to_qimage(self.img_bgr).convertToFormat(
        _api.QtGuiImage.Format.Format_RGB888)
    p = _api.QPainter(img)
    self._draw_object(p, obj)
    p.end()
    self.img_bgr = _api.qimage_to_np_bgr(img)
    self._rebuild_base()

def _commit_pending(self):
    """Закрепляет (вжигает) плавающий объект в картинку, если он есть."""
    if self._pending is None:
        return
    obj = self._pending
    self._pending = None
    self._pending_move = False
    self._pending_resize = None
    self._pending_rs_rect0 = None
    # Вырожденную линию/стрелку (клик без движения) не вжигаем.
    if obj['kind'] == 'shape' and obj['tool'] in (self.TOOL_LINE, self.TOOL_ARROW):
        a, b = obj['a'], obj['b']
        if (abs(a.x() - b.x()) + abs(a.y() - b.y())) < 1.5:
            self.update()
            return
    self._bake_object(obj)
    if obj['kind'] == 'text':
        msg = "Текст вжат."
    elif obj['kind'] == 'image':
        msg = "Изображение вжато."
    else:
        msg = "Фигура вжата."
    self.statusChanged.emit(msg)
    self.update()

def commit_pending(self):
    """Публичный вызов: вкладка вжигает плавающий объект перед сохранением/
        запуском нейросети, чтобы он попал в результат."""
    self._commit_pending()

def cancel_pending(self):
    """Убирает плавающий объект без вжигания (Esc)."""
    if self._pending is None:
        return
    self._pending = None
    self._pending_move = False
    self._pending_resize = None
    self._pending_rs_rect0 = None
    self.update()
    self.statusChanged.emit("Объект отменён.")

def _set_alt(self, on):
    """Включает/выключает режим «временной пипетки» (Alt при активной кисти):
        курсор и подсказка меняются, кольцо-курсор кисти не рисуется."""
    on = bool(on) and self._tool == self.TOOL_BRUSH and self.img_bgr is not None
    if on != self._alt:
        self._alt = on
        self.setCursor(_api.eyedropper_cursor() if on
                       else _api.Qt.CursorShape.CrossCursor)
        self.update()

def _pick_color_at(self, ipt):
    """Берёт цвет пикселя изображения под точкой ipt (коорд. изображения) —
        Alt-пипетка как в Photoshop: цвет кисти становится взятым."""
    if self.img_bgr is None:
        return
    h, w = self.img_bgr.shape[:2]
    x = int(min(max(ipt.x(), 0), w - 1))
    y = int(min(max(ipt.y(), 0), h - 1))
    px = self.img_bgr[y, x]
    col = _api.QColor(int(px[2]), int(px[1]), int(px[0]))   # BGR → RGB
    self.set_brush_color(col)
    self.colorPicked.emit(col)
    self.statusChanged.emit(f"Цвет взят пипеткой: {col.name().upper()}")

def clear_mask(self):
    self._commit_pending()
    if self._overlay is None:
        return
    self._push_history()
    self._overlay.fill(0)
    self._has_strokes = False
    self.update()
    self.statusChanged.emit("Маска очищена.")

def clear_canvas(self):
    """Полностью очищает холст. Состояние «до» кладём в историю, чтобы Ctrl+Z
        вернул очищенную картинку (раньше история стиралась — вернуть было нельзя)."""
    self._commit_pending()
    had_image = self.img_bgr is not None
    if had_image:
        self._push_history()        # снимок «до очистки» для Ctrl+Z
    self.img_bgr = None
    self._overlay = None
    self._paint_layer = None
    self._alpha = None
    self._has_paint = False
    self._base_pix = None
    self._has_strokes = False
    self._pending = None
    self._pending_move = False
    self._crop_a = self._crop_b = None
    self._crop_drag = None
    self._user_zoomed = False
    self._update_crop_buttons()
    self.update()
    self.statusChanged.emit("Холст очищен." +
                            (" Ctrl+Z — вернуть." if had_image else ""))

def composited_bgr(self):
    """То, что видит пользователь: фото с вжатыми мазками «Кисти» (слой краски).
        Маску удаления (красную) НЕ вжигаем — это служебное выделение. Без краски
        возвращает само изображение. Не мутирует состояние (для сохранения)."""
    if self.img_bgr is None:
        return None
    if not self._has_paint or self._paint_layer is None:
        return self.img_bgr
    img = _api.np_bgr_to_qimage(self.img_bgr).convertToFormat(
        _api.QtGuiImage.Format.Format_RGB888)
    p = _api.QPainter(img)
    p.drawImage(0, 0, self._paint_layer)
    p.end()
    return _api.qimage_to_np_bgr(img)

def bake_paint(self):
    """Вжигает слой краски в img_bgr и очищает слой. Зовём перед удалением
        объекта/кадрированием, чтобы мазки попали в результат. Историю НЕ трогаем —
        её снимает вызывающий код (apply_crop/_run_inpaint)."""
    if self.img_bgr is None or self._paint_layer is None or not self._has_paint:
        return
    # Если фон удалён — закрашенные кистью пиксели становятся непрозрачными
    # (рисуем «поверх пустоты»), иначе мазок не был бы виден.
    if self._alpha is not None:
        pa = self._layer_alpha(self._paint_layer)
        self._alpha = _api._np.maximum(self._alpha,
                                  (pa > 10).astype(_api._np.uint8) * 255)
    self.img_bgr = self.composited_bgr()
    self._paint_layer.fill(0)
    self._has_paint = False
    self._rebuild_base()

def fit(self):
    self._user_zoomed = False
    self._fit()
    self._update_crop_buttons()
    self.update()

# ── Кадрирование ────────────────────────────────────────────────────────
def has_crop(self) -> bool:
    return self._crop_a is not None and self._crop_b is not None

def _update_crop_buttons(self):
    """Показывает/прячет и позиционирует кнопки «Применить/Отмена» у рамки
        кадрирования (как плавающая панель Photoshop). Зовётся при любом
        изменении рамки/зума/размера холста."""
    show = (self._tool == self.TOOL_CROP and self.has_crop()
            and self.img_bgr is not None)
    if not show:
        if self._crop_apply_btn.isVisible():
            self._crop_apply_btn.setVisible(False)
            self._crop_cancel_btn.setVisible(False)
        if self._crop_aspect_combo.isVisible():
            self._crop_aspect_combo.setVisible(False)
        return
    r = self._crop_rect_w()
    # Селектор пропорций — над верх-левым углом рамки (как панель кадрирования
    # в Photoshop); если сверху не влезает — внутрь рамки у верхнего края.
    ac = self._crop_aspect_combo
    ach = ac.sizeHint().height()
    acw = max(ac.sizeHint().width(), 96)
    ax = int(max(2, min(r.left(), self.width() - acw - 2)))
    ay = int(r.top() - ach - 6)
    if ay < 2:
        ay = int(r.top() + 6)
    ay = max(2, min(ay, self.height() - ach - 2))
    ac.setGeometry(ax, ay, acw, ach)
    ac.setVisible(True)
    ac.raise_()
    aw = self._crop_apply_btn.sizeHint()
    cw = self._crop_cancel_btn.sizeHint()
    gap = 6
    h = max(aw.height(), cw.height())
    total = aw.width() + cw.width() + gap
    # Прижимаем к правому-нижнему углу рамки, под ней; если снизу не влезает —
    # переносим внутрь рамки над её нижним краем. Затем зажимаем в холст.
    x = int(r.right() - total)
    y = int(r.bottom() + gap)
    if y + h > self.height():
        y = int(r.bottom() - h - gap)
    x = max(2, min(x, self.width() - total - 2))
    y = max(2, min(y, self.height() - h - 2))
    self._crop_apply_btn.setGeometry(x, y, aw.width(), h)
    self._crop_cancel_btn.setGeometry(x + aw.width() + gap, y, cw.width(), h)
    self._crop_apply_btn.setVisible(True)
    self._crop_cancel_btn.setVisible(True)
    self._crop_apply_btn.raise_()
    self._crop_cancel_btn.raise_()

def apply_crop(self):
    self._commit_pending()
    if not self.has_crop() or self.img_bgr is None:
        return False
    h, w = self.img_bgr.shape[:2]
    x0 = int(max(0, min(self._crop_a.x(), self._crop_b.x())))
    y0 = int(max(0, min(self._crop_a.y(), self._crop_b.y())))
    x1 = int(min(w, max(self._crop_a.x(), self._crop_b.x())))
    y1 = int(min(h, max(self._crop_a.y(), self._crop_b.y())))
    if x1 - x0 < 4 or y1 - y0 < 4:
        self.statusChanged.emit("Слишком маленькая область кадрирования.")
        return False
    self._push_history()
    # Вжигаем мазки кисти перед обрезкой, чтобы они попали в результат.
    self.bake_paint()
    self.img_bgr = _api._np.ascontiguousarray(self.img_bgr[y0:y1, x0:x1])
    if self._alpha is not None:                  # кадрируем и маску прозрачности
        self._alpha = _api._np.ascontiguousarray(self._alpha[y0:y1, x0:x1])
    new_ov = _api.QtGuiImage(x1 - x0, y1 - y0,
                        _api.QtGuiImage.Format.Format_ARGB32_Premultiplied)
    new_ov.fill(0)
    p = _api.QPainter(new_ov)
    p.drawImage(0, 0, self._overlay, x0, y0, x1 - x0, y1 - y0)
    p.end()
    self._overlay = new_ov
    # Слой краски уже вжат → пересоздаём пустым под новый размер.
    self._paint_layer = _api.QtGuiImage(x1 - x0, y1 - y0,
                                   _api.QtGuiImage.Format.Format_ARGB32_Premultiplied)
    self._paint_layer.fill(0)
    self._has_paint = False
    self._recompute_strokes_flag()
    self._crop_a = self._crop_b = None
    self._rebuild_base()
    self._user_zoomed = False
    self._fit()
    self._update_crop_buttons()
    self.update()
    self.statusChanged.emit(f"Кадрировано → {x1 - x0}×{y1 - y0}.")
    return True

def cancel_crop(self):
    self._crop_a = self._crop_b = None
    self._crop_drag = None
    self._update_crop_buttons()
    self.update()
