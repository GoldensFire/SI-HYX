# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""InpaintCanvas: paintEvent. Public namespace: photo_tab."""
import photo_tab as _api


# ── Отрисовка ────────────────────────────────────────────────────────────
def paintEvent(self, ev):
    self._sync_overlay_buttons()
    self._sync_scrollbars()
    painter = _api.QPainter(self)
    painter.fillRect(self.rect(), _api.QColor("#11111b"))
    if self.img_bgr is None or self._base_pix is None:
        painter.setPen(_api.QColor("#585b70"))
        f = painter.font(); f.setPointSize(11); painter.setFont(f)
        painter.drawText(self.rect(), _api.Qt.AlignmentFlag.AlignCenter,
                         "Откройте изображение для удаления объектов\n"
                         "(кнопка «Открыть» сверху или перетащите файл)")
        return
    painter.setRenderHint(_api.QPainter.RenderHint.SmoothPixmapTransform, True)
    ih, iw = self.img_bgr.shape[:2]
    target = self._img_rect_w()
    src = _api.QRectF(0, 0, iw, ih)
    painter.drawPixmap(target, self._base_pix, src)
    # Слой краски «Кисти» поверх фото (ещё не вжатый — чтобы Ластик мог стирать).
    if self._paint_layer is not None:
        painter.drawImage(target, self._paint_layer, src)
    painter.drawImage(target, self._overlay, src)

    # Рамка кадрирования (стиль Paint/Photoshop): затемняем всё ВНЕ рамки,
    # рисуем границу, сетку третей и квадратные ручки на углах/серединах сторон.
    if self._tool == self.TOOL_CROP and self.has_crop():
        r = self._crop_rect_w().intersected(target)
        # 4 затемняющих полосы вокруг рамки (в пределах изображения).
        painter.setPen(_api.Qt.PenStyle.NoPen)
        painter.setBrush(_api.QColor(0, 0, 0, 120))
        painter.drawRect(_api.QRectF(target.left(), target.top(),
                                target.width(), r.top() - target.top()))
        painter.drawRect(_api.QRectF(target.left(), r.bottom(),
                                target.width(), target.bottom() - r.bottom()))
        painter.drawRect(_api.QRectF(target.left(), r.top(),
                                r.left() - target.left(), r.height()))
        painter.drawRect(_api.QRectF(r.right(), r.top(),
                                target.right() - r.right(), r.height()))
        # Сетка третей.
        painter.setBrush(_api.Qt.BrushStyle.NoBrush)
        painter.setPen(_api.QPen(_api.QColor(255, 255, 255, 80), 1))
        for i in (1, 2):
            gx = r.left() + r.width() * i / 3.0
            gy = r.top() + r.height() * i / 3.0
            painter.drawLine(_api.QPointF(gx, r.top()), _api.QPointF(gx, r.bottom()))
            painter.drawLine(_api.QPointF(r.left(), gy), _api.QPointF(r.right(), gy))
        # Граница рамки.
        painter.setPen(_api.QPen(_api.QColor("#cdd6f4"), 1.5))
        painter.drawRect(r)
        # Квадратные ручки.
        painter.setPen(_api.QPen(_api.QColor("#1e1e2e"), 1))
        painter.setBrush(_api.QColor("#cdd6f4"))
        hs = 4.0
        cx, cy = r.center().x(), r.center().y()
        for p in (r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight(),
                  _api.QPointF(cx, r.top()), _api.QPointF(cx, r.bottom()),
                  _api.QPointF(r.left(), cy), _api.QPointF(r.right(), cy)):
            painter.drawRect(_api.QRectF(p.x() - hs, p.y() - hs, 2 * hs, 2 * hs))

    # Предпросмотр тянущейся фигуры (в экранных координатах поверх картинки).
    if (self._shape_drawing and self._shape_start is not None
            and self._shape_cur is not None):
        painter.save()
        painter.setClipRect(target)
        painter.translate(self._off)
        painter.scale(self._scale, self._scale)
        self._draw_shape(painter, self._shape_start, self._shape_cur, self._tool)
        painter.restore()

    # Плавающий объект (фигура/текст) + пунктирная рамка выделения вокруг него —
    # видно, что его ещё можно перетащить (как выделенный слой в Photoshop).
    if self._pending is not None:
        painter.save()
        painter.setClipRect(target)
        painter.translate(self._off)
        painter.scale(self._scale, self._scale)
        self._draw_object(painter, self._pending)
        painter.restore()
        bb = self._object_bbox(self._pending)
        sel = _api.QRectF(self._i2w(bb.topLeft()), self._i2w(bb.bottomRight())).normalized()
        painter.setBrush(_api.Qt.BrushStyle.NoBrush)
        painter.setPen(_api.QPen(_api.QColor(0, 0, 0, 160), 2, _api.Qt.PenStyle.DashLine))
        painter.drawRect(sel)
        painter.setPen(_api.QPen(_api.QColor("#89b4fa"), 1, _api.Qt.PenStyle.DashLine))
        painter.drawRect(sel)
        # Квадратные ручки размера (только у картинки — её можно ресайзить).
        if self._pending_resizable():
            painter.setPen(_api.QPen(_api.QColor("#1e1e2e"), 1))
            painter.setBrush(_api.QColor("#89b4fa"))
            hs = 4.0
            cx, cy = sel.center().x(), sel.center().y()
            for p in (sel.topLeft(), sel.topRight(), sel.bottomLeft(),
                      sel.bottomRight(), _api.QPointF(cx, sel.top()),
                      _api.QPointF(cx, sel.bottom()), _api.QPointF(sel.left(), cy),
                      _api.QPointF(sel.right(), cy)):
                painter.drawRect(_api.QRectF(p.x() - hs, p.y() - hs, 2 * hs, 2 * hs))

    # Кольцо-курсор кисти/ластика (не показываем под Alt-пипеткой).
    if (self._mouse_w is not None and not self._panning and not self._alt
            and self._tool in (self.TOOL_BRUSH, self.TOOL_MASK,
                               self.TOOL_ERASE, self.TOOL_BLUR)):
        rad = self._brush / 2.0
        painter.setBrush(_api.Qt.BrushStyle.NoBrush)
        painter.setPen(_api.QPen(_api.QColor(0, 0, 0, 160), 2))
        painter.drawEllipse(self._mouse_w, rad, rad)
        painter.setPen(_api.QPen(_api.QColor(255, 255, 255, 220), 1))
        painter.drawEllipse(self._mouse_w, rad, rad)
