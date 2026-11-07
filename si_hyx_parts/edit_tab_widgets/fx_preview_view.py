# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""FxPreviewView — экран просмотра проекта с эффектами. Public namespace:
edit_tab_widgets.

Обычный ЦП-виджет: кадр (QImage от FxPreview) вписан в виджет с полями,
поверх — короткая подпись состояния (рендер кадра, готовность кэша). На время
режима «просмотр с эффектами» он стоит в контейнере видео вместо холста
плеера (холст — нативное окно Qt Quick, поверх него обычный виджет не
нарисовать)."""
import edit_tab_widgets as _api


class FxPreviewView(_api.QWidget):
    """Кадр просмотра с эффектами и подпись состояния."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._img = None
        self._note = ""
        self.setSizePolicy(_api.QSizePolicy.Policy.Expanding, _api.QSizePolicy.Policy.Expanding)
        self.setMinimumSize(160, 90)

    def set_image(self, img):
        self._img = img
        self.update()

    def set_note(self, text):
        text = text or ""
        if text != self._note:
            self._note = text
            self.update()

    def has_image(self):
        return self._img is not None and not self._img.isNull()

    def clear(self):
        self._img = None
        self.update()

    def image_rect(self):
        img = self._img
        if img is None or img.isNull() or img.width() <= 0 or img.height() <= 0:
            return _api.QRectF(self.rect())
        k = min(self.width() / img.width(), self.height() / img.height())
        w, h = img.width() * k, img.height() * k
        return _api.QRectF((self.width() - w) / 2.0, (self.height() - h) / 2.0, w, h)

    def paintEvent(self, ev):
        p = _api.QPainter(self)
        p.fillRect(self.rect(), _api.QColor(_api.C['bg']))
        if self.has_image():
            p.setRenderHint(_api.QPainter.RenderHint.SmoothPixmapTransform, True)
            p.drawImage(self.image_rect(), self._img)
        if self._note:
            font = _api.QFont(self.font())
            font.setPixelSize(11)
            p.setFont(font)
            fm = _api.QFontMetrics(font)
            tw = fm.horizontalAdvance(self._note) + 12
            box = _api.QRectF(8, 8, tw, 18)
            p.setPen(_api.Qt.PenStyle.NoPen)
            p.setBrush(_api.QColor(0, 0, 0, 150))
            p.drawRoundedRect(box, 4, 4)
            p.setPen(_api.QColor("#ffffff"))
            p.drawText(box, int(_api.Qt.AlignmentFlag.AlignCenter), self._note)
        p.end()


FxPreviewView.__module__ = _api.__name__
