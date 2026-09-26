# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""InpaintCanvas: _sync_scrollbars. Public namespace: photo_tab."""
import photo_tab as _api


def _sync_scrollbars(self):
    """Показывает/прячет и настраивает скроллбары под текущий зум/смещение."""
    if self.img_bgr is None:
        self._hbar.setVisible(False)
        self._vbar.setVisible(False)
        return
    self._syncing_bars = True
    try:
        cw, ch = self._content_size()
        W, H = self.width(), self.height()
        t = self._SB_THICK
        # Бар по одной оси «съедает» место у встречной — учитываем взаимно.
        need_h = cw > W
        need_v = ch > H
        need_h = cw > (W - (t if need_v else 0))
        need_v = ch > (H - (t if need_h else 0))
        vw = W - (t if need_v else 0)
        vh = H - (t if need_h else 0)
        self._clamp_off()
        if need_h:
            self._hbar.setGeometry(0, H - t, vw, t)
            self._hbar.setPageStep(max(1, int(vw)))
            self._hbar.setSingleStep(max(1, int(vw * 0.1)))
            self._hbar.setRange(0, max(0, int(round(cw - vw))))
            self._hbar.setValue(int(round(-self._off.x())))
            self._hbar.setVisible(True)
            self._hbar.raise_()
        else:
            self._hbar.setVisible(False)
        if need_v:
            self._vbar.setGeometry(W - t, 0, t, vh)
            self._vbar.setPageStep(max(1, int(vh)))
            self._vbar.setSingleStep(max(1, int(vh * 0.1)))
            self._vbar.setRange(0, max(0, int(round(ch - vh))))
            self._vbar.setValue(int(round(-self._off.y())))
            self._vbar.setVisible(True)
            self._vbar.raise_()
        else:
            self._vbar.setVisible(False)
    finally:
        self._syncing_bars = False

def _on_hbar(self, v):
    if self._syncing_bars or self.img_bgr is None:
        return
    self._off.setX(-float(v))
    self._update_crop_buttons()
    self.update()

def _on_vbar(self, v):
    if self._syncing_bars or self.img_bgr is None:
        return
    self._off.setY(-float(v))
    self._update_crop_buttons()
    self.update()

# ── Рисование штриха ─────────────────────────────────────────────────────
def _paint_to(self, img_pt):
    # «Кисть» рисует по слою краски (поверх фото), «Ластик» стирает ИМЕННО
    # этот слой (мазки кисти), а не маску удаления. TOOL_MASK — красная маска
    # удаления в отдельном оверлее.
    if self._tool == self.TOOL_BRUSH:
        self._paint_image_to(img_pt, erase=False)
        return
    if self._tool == self.TOOL_ERASE:
        self._paint_image_to(img_pt, erase=True)
        return
    if self._tool == self.TOOL_BLUR:
        self._blur_to(img_pt)
        return
    # TOOL_MASK — красная маска удаления (вход для нейросети).
    p = _api.QPainter(self._overlay)
    p.setRenderHint(_api.QPainter.RenderHint.Antialiasing, True)
    width = max(1.0, self._brush / self._scale)
    col = _api.QColor(235, 45, 45, 150)
    a = self._last_img_pt if self._last_img_pt is not None else img_pt
    if a == img_pt:
        p.setPen(_api.Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawEllipse(img_pt, width / 2.0, width / 2.0)
    else:
        pen = _api.QPen(col)
        pen.setWidthF(width)
        pen.setCapStyle(_api.Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(_api.Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawLine(a, img_pt)
    p.end()
    self._last_img_pt = img_pt
    self._has_strokes = True

def _paint_image_to(self, img_pt, erase=False):
    """«Кисть» (erase=False) кладёт непрозрачные мазки в слой краски
        _paint_layer поверх фото; «Ластик» (erase=True) стирает их из этого слоя
        (CompositionMode_Clear). Слой НЕ вживается в img_bgr сразу — только перед
        удалением объекта/кадрированием/сохранением (bake_paint), поэтому мазки
        можно свободно стирать, как в Photoshop."""
    if self._paint_layer is None:
        return
    p = _api.QPainter(self._paint_layer)
    if erase:
        # Жёсткий край без сглаживания и чуть шире штриха — иначе остаётся
        # полупрозрачная «бахрома» и кажется, что ластик не дотирает.
        p.setRenderHint(_api.QPainter.RenderHint.Antialiasing, False)
        p.setCompositionMode(_api.QPainter.CompositionMode.CompositionMode_Clear)
        width = max(1.0, (self._brush + 2) / self._scale)
        col = _api.QColor(0, 0, 0, 255)
    else:
        p.setRenderHint(_api.QPainter.RenderHint.Antialiasing, True)
        width = max(1.0, self._brush / self._scale)
        c = self._brush_color
        col = _api.QColor(c.red(), c.green(), c.blue())   # непрозрачная краска
    a = self._last_img_pt if self._last_img_pt is not None else img_pt
    if a == img_pt:
        p.setPen(_api.Qt.PenStyle.NoPen)
        p.setBrush(col)
        r = width / 2.0 + (1.5 if erase else 0.0)
        p.drawEllipse(img_pt, r, r)
    else:
        pen = _api.QPen(col)
        pen.setWidthF(width)
        pen.setCapStyle(_api.Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(_api.Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawLine(a, img_pt)
    p.end()
    self._last_img_pt = img_pt
    if not erase:
        self._has_paint = True

# ── Кисть «Размытие» ─────────────────────────────────────────────────────
def _begin_blur_stroke(self):
    """Готовит один мазок размытия: замыленная копия всей картинки + пустая
        маска штриха. Сама картинка заменяется НОВЫМ массивом (копией) — так кэш
        PNG-кодирования истории (_bgr_snap_src сравнивает по identity) не
        протухает, пока мы правим пиксели на месте."""
    if self.img_bgr is None:
        return
    sigma = float(self._blur_strength)
    self._blur_orig = self.img_bgr
    self._blur_dst = _api._cv2.GaussianBlur(self.img_bgr, (0, 0), sigma)
    h, w = self.img_bgr.shape[:2]
    self._blur_mask = _api._np.zeros((h, w), _api._np.uint8)
    self.img_bgr = self.img_bgr.copy()

def _end_blur_stroke(self):
    self._blur_orig = self._blur_dst = self._blur_mask = None

def _blur_to(self, img_pt):
    if self._blur_mask is None or self.img_bgr is None:
        return
    h, w = self.img_bgr.shape[:2]
    width = max(1, int(round(self._brush / self._scale)))
    a = self._last_img_pt if self._last_img_pt is not None else img_pt
    p0 = (int(round(a.x())), int(round(a.y())))
    p1 = (int(round(img_pt.x())), int(round(img_pt.y())))
    if p0 == p1:
        _api._cv2.circle(self._blur_mask, p1, max(1, width // 2), 255, -1,
                    _api._cv2.LINE_AA)
    else:
        _api._cv2.line(self._blur_mask, p0, p1, 255, width, _api._cv2.LINE_AA)
    # Пересчитываем только прямоугольник вокруг сегмента — иначе на крупных
    # фото каждое движение мыши пережёвывало бы весь кадр.
    pad = width // 2 + 2
    x0 = max(0, min(p0[0], p1[0]) - pad); x1 = min(w, max(p0[0], p1[0]) + pad + 1)
    y0 = max(0, min(p0[1], p1[1]) - pad); y1 = min(h, max(p0[1], p1[1]) + pad + 1)
    if x1 <= x0 or y1 <= y0:
        return
    m = (self._blur_mask[y0:y1, x0:x1].astype(_api._np.float32) / 255.0)[..., None]
    src = self._blur_orig[y0:y1, x0:x1].astype(_api._np.float32)
    dst = self._blur_dst[y0:y1, x0:x1].astype(_api._np.float32)
    self.img_bgr[y0:y1, x0:x1] = (src * (1.0 - m) + dst * m).astype(_api._np.uint8)
    self._blit_base_region(x0, y0, x1, y1)
    self._last_img_pt = img_pt

def _blit_base_region(self, x0, y0, x1, y1):
    """Обновляет в кэше-пиксмапе только изменённый прямоугольник (полный
        _rebuild_base на 4K-фото — десятки мс на каждое движение мыши)."""
    if self._base_pix is None or self._alpha is not None:
        self._rebuild_base()
        return
    qi = _api.np_bgr_to_qimage(self.img_bgr[y0:y1, x0:x1])
    p = _api.QPainter(self._base_pix)
    p.drawImage(x0, y0, qi)
    p.end()

# ── События мыши/колеса/клавиатуры ───────────────────────────────────────
def mousePressEvent(self, ev):
    if self.img_bgr is None:
        return
    if ev.button() == _api.Qt.MouseButton.MiddleButton:
        self._panning = True
        self._pan_start = ev.position()
        self._off_start = _api.QPointF(self._off)
        self.setCursor(_api.Qt.CursorShape.ClosedHandCursor)
        return
    if ev.button() != _api.Qt.MouseButton.LeftButton:
        return
    ipt = self._w2i(ev.position())
    # Плавающий объект (фигура/текст/картинка, ещё не вжатый): сначала ручки
    # размера (как free-transform в Photoshop), затем клик ВНУТРИ — перенос,
    # клик ВНЕ — закрепить (вжать). Геометрия от вжигания не меняется.
    if self._pending is not None:
        handle = self._pending_handle_at(ev.position())
        if handle in ('tl', 'tr', 'bl', 'br', 't', 'b', 'l', 'r'):
            self._pending_resize = handle
            self._pending_rs_rect0 = self._object_bbox(self._pending)
            self.setCursor(self._crop_cursor(handle))
            return
        if self._object_bbox(self._pending).contains(ipt):
            self._pending_move = True
            self._pending_anchor = ipt
            self.setCursor(_api.Qt.CursorShape.SizeAllCursor)
            if self._pending.get('kind') == 'text':
                self.textSelected.emit()
            return
        # Клик ВНЕ рамки — закрепляем слой (снимает выделение, как клик мимо
        # рамки free-transform в Photoshop). Дальше клик НЕ продолжаем в кисть
        # и т.п., чтобы не рисовать тем же кликом, которым «применили» слой.
        self._commit_pending()
        return
    if self._tool == self.TOOL_MOVE:
        # Нет плавающего объекта под курсором → «Курсор» работает как рука в
        # Photoshop: тянем — двигаем «камеру». Только при приближении (когда
        # картинка больше холста), иначе на вписанной картинке не сдвигаем.
        cw, ch = self._content_size()
        if cw > self.width() or ch > self.height():
            self._panning = True
            self._pan_start = ev.position()
            self._off_start = _api.QPointF(self._off)
            self.setCursor(_api.Qt.CursorShape.ClosedHandCursor)
        return
    # Alt + кисть = пипетка: берём цвет из изображения, не рисуя мазок.
    if (self._tool == self.TOOL_BRUSH
            and (ev.modifiers() & _api.Qt.KeyboardModifier.AltModifier)):
        self._pick_color_at(ipt)
        return
    if self._tool == self.TOOL_CROP:
        if not self.has_crop():
            h, w = self.img_bgr.shape[:2]
            self._crop_a = _api.QPointF(0, 0); self._crop_b = _api.QPointF(w, h)
            if self._crop_aspect:
                self._reshape_crop_to_aspect()
        handle = self._crop_handle_at(ev.position())
        # Клик мимо рамки — игнорируем (рамка остаётся как есть).
        self._crop_drag = handle
        self._crop_anchor = ipt
        self._crop_start = (_api.QPointF(self._crop_a), _api.QPointF(self._crop_b))
        self.update()
        return
    if self._tool == self.TOOL_TEXT:
        # Текст: клик задаёт верх-левый угол, далее спрашиваем строку.
        self._draw_text_at(ipt)
        return
    if self._tool in self._SHAPE_TOOLS:
        # Фигура: начинаем тянуть от точки клика.
        self._shape_start = ipt
        self._shape_cur = ipt
        self._shape_drawing = True
        self.update()
        return
    # Кисть/ластик/размытие — новый штрих: фиксируем состояние для отмены.
    self._push_history()
    if self._tool == self.TOOL_BLUR:
        # Мазки «Кисти» лежат отдельным слоем — вжигаем их, иначе размытие
        # ушло бы ПОД них (как и при кадрировании/удалении объекта).
        self.bake_paint()
        self._begin_blur_stroke()
    self._painting = True
    self._last_img_pt = None
    self._paint_to(ipt)
    self.update()
