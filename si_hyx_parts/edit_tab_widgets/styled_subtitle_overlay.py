# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_StyledSubtitleOverlay. Public namespace: edit_tab_widgets."""
import edit_tab_widgets as _api


class _StyledSubtitleOverlay(_api.QWidget):
    """Прозрачный оверлей поверх _SubtitlePreview.canvas — рисует ТЕКУЩУЮ реплику
    выбранным пользователем стилем (_paint_subtitle_styled), а не фиксированным
    VLC-стилем основного приложения (_paint_subtitle, его не трогаем)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(_api.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._text = ""
        self._style = None

    def set_content(self, text, style):
        self._text = text or ""
        self._style = style
        self.update()

    def paintEvent(self, ev):
        p = _api.QPainter(self)
        _api._paint_subtitle_styled(p, self.rect(), self._text, self._style)
        p.end()

_StyledSubtitleOverlay.__module__ = _api.__name__
_api._StyledSubtitleOverlay = _StyledSubtitleOverlay

class _TrackSelectCanvas(_api.QWidget):
    """Холст выбора области для отслеживания: показывает кадр видео и позволяет
    обвести объект рамкой (протяжкой мыши), а также сразу показывает, как рядом
    с рамкой ляжет накладка (текст/картинка).

    Рамка хранится в ПИКСЕЛЯХ ИСХОДНОГО кадра (не в координатах виджета) — она
    уходит в трекер как есть, поэтому не зависит от размера окна."""

    boxChanged = _api.pyqtSignal()

    _MIN_SIDE = 8            # меньше — случайный клик, а не рамка

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(260)
        self.setCursor(_api.Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self._img = None          # QImage кадра (полное разрешение)
        self._box = None          # QRectF в пикселях кадра
        self._overlay = None      # QImage накладки (BGRA→QImage), уже отрисованная
        self._anchor = "center"
        self._off = (0, 0)
        self._drag_start = None   # точка начала протяжки (координаты кадра)
        self._move_from = None    # для перетаскивания готовой рамки

    # ── данные ────────────────────────────────────────────────────────────────
    def set_image(self, qimg):
        self._img = qimg
        self._box = None
        self.update()

    def set_overlay(self, qimg, anchor="center", off=(0, 0)):
        """Накладка для превью (может быть None — тогда рисуется только рамка)."""
        self._overlay = qimg
        self._anchor = anchor
        self._off = (int(off[0]), int(off[1]))
        self.update()

    def box_px(self):
        """Выбранная область как (x, y, w, h) в пикселях кадра или None."""
        if self._box is None:
            return None
        r = self._box
        return (float(r.x()), float(r.y()), float(r.width()), float(r.height()))

    def set_box_px(self, box):
        self._box = _api.QRectF(*box) if box else None
        self.update()

    # ── геометрия «кадр ↔ виджет» ─────────────────────────────────────────────
    def _fit(self):
        """(scale, dx, dy) для вписывания кадра в виджет с сохранением пропорций."""
        if self._img is None or self._img.isNull():
            return 1.0, 0.0, 0.0
        iw, ih = self._img.width(), self._img.height()
        if iw <= 0 or ih <= 0:
            return 1.0, 0.0, 0.0
        s = min(self.width() / iw, self.height() / ih)
        return s, (self.width() - iw * s) / 2.0, (self.height() - ih * s) / 2.0

    def _to_img(self, pt):
        s, dx, dy = self._fit()
        if s <= 0:
            return _api.QPointF(0, 0)
        x = (pt.x() - dx) / s
        y = (pt.y() - dy) / s
        if self._img is not None:
            x = max(0.0, min(float(self._img.width()), x))
            y = max(0.0, min(float(self._img.height()), y))
        return _api.QPointF(x, y)

    def _to_widget_rect(self, r):
        s, dx, dy = self._fit()
        return _api.QRectF(dx + r.x() * s, dy + r.y() * s, r.width() * s, r.height() * s)

    # ── мышь ──────────────────────────────────────────────────────────────────
    def mousePressEvent(self, ev):
        if self._img is None or ev.button() != _api.Qt.MouseButton.LeftButton:
            return
        p = self._to_img(ev.position())
        if self._box is not None and self._box.contains(p):
            self._move_from = (p, _api.QRectF(self._box))
        else:
            self._drag_start = p
            self._box = _api.QRectF(p, p)
        self.update()

    def mouseMoveEvent(self, ev):
        if self._img is None:
            return
        p = self._to_img(ev.position())
        if self._drag_start is not None:
            self._box = _api.QRectF(self._drag_start, p).normalized()
            self.update()
        elif self._move_from is not None:
            start, rect0 = self._move_from
            r = _api.QRectF(rect0)
            r.translate(p.x() - start.x(), p.y() - start.y())
            # Не выпускаем рамку за пределы кадра.
            r.moveLeft(max(0.0, min(self._img.width() - r.width(), r.x())))
            r.moveTop(max(0.0, min(self._img.height() - r.height(), r.y())))
            self._box = r
            self.update()
        else:
            inside = self._box is not None and self._box.contains(p)
            self.setCursor(_api.Qt.CursorShape.SizeAllCursor if inside
                           else _api.Qt.CursorShape.CrossCursor)

    def mouseReleaseEvent(self, ev):
        if self._drag_start is not None:
            self._drag_start = None
            if self._box is not None and (self._box.width() < self._MIN_SIDE
                                          or self._box.height() < self._MIN_SIDE):
                self._box = None       # случайный клик — рамку не создаём
        self._move_from = None
        self.update()
        self.boxChanged.emit()

    # ── отрисовка ─────────────────────────────────────────────────────────────
    def paintEvent(self, ev):
        p = _api.QPainter(self)
        p.fillRect(self.rect(), _api.QColor(_api.C["bg"]))
        if self._img is None or self._img.isNull():
            p.setPen(_api.QColor(_api.C["text3"]))
            p.drawText(self.rect(), _api.Qt.AlignmentFlag.AlignCenter, "Нет кадра")
            return
        p.setRenderHint(_api.QPainter.RenderHint.SmoothPixmapTransform, True)
        s, dx, dy = self._fit()
        target = _api.QRectF(dx, dy, self._img.width() * s, self._img.height() * s)
        p.drawImage(target, self._img)

        if self._box is None:
            p.setPen(_api.QColor(_api.C["text2"]))
            p.drawText(target, _api.Qt.AlignmentFlag.AlignHCenter | _api.Qt.AlignmentFlag.AlignTop,
                       "\nОбведите объект рамкой")
            return

        wr = self._to_widget_rect(self._box)
        # Превью накладки — ровно там, где её положит воркер (та же геометрия,
        # что в overlay_top_left, только в масштабе превью).
        if self._overlay is not None and not self._overlay.isNull():
            ow, oh = self._overlay.width(), self._overlay.height()
            ox, oy = _api.overlay_top_left(self.box_px(), ow, oh, self._anchor, *self._off)
            p.drawImage(_api.QRectF(dx + ox * s, dy + oy * s, ow * s, oh * s), self._overlay)

        pen = _api.QPen(_api.QColor(_api.C["accent"]))
        pen.setWidth(2)
        p.setPen(pen)
        p.setBrush(_api.Qt.BrushStyle.NoBrush)
        p.drawRect(wr)
        # Уголки рамки — чтобы её было видно на пёстром кадре.
        pen2 = _api.QPen(_api.QColor("#ffffff")); pen2.setWidth(1)
        p.setPen(pen2)
        for cx, cy in ((wr.left(), wr.top()), (wr.right(), wr.top()),
                       (wr.left(), wr.bottom()), (wr.right(), wr.bottom())):
            p.drawRect(_api.QRectF(cx - 3, cy - 3, 6, 6))

_TrackSelectCanvas.__module__ = _api.__name__
_api._TrackSelectCanvas = _TrackSelectCanvas
