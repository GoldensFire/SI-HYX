# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""FxPreviewView — экран просмотра проекта с эффектами. Public namespace:
edit_tab_widgets.

Обычный ЦП-виджет: кадр (QImage от FxPreview) вписан в виджет с полями,
поверх — короткая подпись состояния (рендер кадра, готовность кэша). На время
режима «просмотр с эффектами» он стоит в контейнере видео вместо холста
плеера (холст — нативное окно Qt Quick, поверх него обычный виджет не
нарисовать). Рамка выбранного клипа (ClipFrameEditor) — та же, что у
холста плеера, и с теми же сигналами.

Перенос рамки — вживую: кадр с эффектами рендерит ffmpeg, поэтому на время
переноса клип вырезается из показанного кадра и едет за курсором поверх
фона — того же кадра без этого клипа (set_ghost, рендер заранее). После
отпускания слой держится, пока не придёт новый кадр, — картинка не прыгает
назад. Фона ещё нет — клип едет поверх старого кадра."""
import math

import numpy as np

import edit_tab_widgets as _api

_DIFF = 24      # отличие от фона (0…255 по каналу), с которого пиксель — клипа


def _argb_array(img):
    """Копия QImage как массив (h, w, 4) uint8 в порядке ARGB32 (B, G, R, A)."""
    img = img.convertToFormat(_api.QImage.Format.Format_ARGB32)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    ptr = img.constBits()
    ptr.setsize(bpl * h)
    buf = np.frombuffer(ptr, np.uint8).reshape(h, bpl)
    return buf[:, :w * 4].reshape(h, w, 4).copy()


class FxPreviewView(_api.QWidget):
    """Кадр просмотра с эффектами и подпись состояния."""

    clipFrameEdited = _api.pyqtSignal(_api.QRectF, _api.QRectF)
    clipFramePicked = _api.pyqtSignal(_api.QPointF)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._img = None
        self._note = ""
        self._clip_frame = _api.ClipFrameEditor()
        self._ghost = None      # см. set_ghost
        self._layer = None      # слой клипа на время переноса (_build_layer)
        self._hold = False      # перенос отпущен — слой держится до нового кадра
        self.setMouseTracking(True)
        self.setSizePolicy(_api.QSizePolicy.Policy.Expanding, _api.QSizePolicy.Policy.Expanding)
        self.setMinimumSize(160, 90)

    def set_image(self, img):
        self._img = img
        self._hold = False
        if not self._clip_frame.dragging():
            self._layer = None
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
        self._ghost = self._layer = None
        self._hold = False
        self.update()

    def image_rect(self):
        img = self._img
        if img is None or img.isNull() or img.width() <= 0 or img.height() <= 0:
            return _api.QRectF(self.rect())
        k = min(self.width() / img.width(), self.height() / img.height())
        w, h = img.width() * k, img.height() * k
        return _api.QRectF((self.width() - w) / 2.0, (self.height() - h) / 2.0, w, h)

    # ── Рамка клипа проекта ───────────────────────────────────────────────────
    def set_clip_frame(self, rect):
        if self._clip_frame.set_rect(rect):
            self.update()

    def clip_frame_dragging(self):
        return self._clip_frame.dragging()

    # ── Живой перенос ────────────────────────────────────────────────────────
    def set_ghost(self, ghost):
        """Что нужно для переноса рамки вживую или None: {'clip' — рамка
        клипа, 'pad' — она же с обводкой и тенью (доли кадра), 'bg' — кадр
        без клипа (QImage) или None, 'opaque' — клип непрозрачен в своей
        рамке}. Фон пришёл посреди переноса — слой пересобирается с ним."""
        self._ghost = ghost
        lay = self._layer
        if (ghost is not None and ghost.get('bg') is not None and lay is not None
                and lay['bg'] is None and self._clip_frame.dragging()
                and self._same_rect(ghost['clip'], lay['clip'])):
            self._layer = self._build_layer(ghost) or lay
            self.update()

    @staticmethod
    def _same_rect(a, b):
        return (abs(a.x() - b.x()) < 1e-4 and abs(a.y() - b.y()) < 1e-4
                and abs(a.width() - b.width()) < 1e-4 and abs(a.height() - b.height()) < 1e-4)

    def _build_layer(self, g):
        """Слой клипа из показанного кадра: {'img', 'rect' (доли кадра),
        'clip' — рамка клипа на старте, 'bg'} или None. С фоном пиксели
        клипа (и его обводки, тени, прозрачных краёв) — те, что отличаются от
        фона; без фона — просто прямоугольник рамки."""
        img = self._img
        if img is None or img.isNull():
            return None
        W, H = img.width(), img.height()
        bg = g.get('bg')
        if bg is not None and (bg.isNull() or bg.size() != img.size()):
            bg = None
        clip = _api.QRectF(g['clip'])
        outer = _api.QRectF(g['pad']) if bg is not None else clip

        def px(r):
            x0 = max(0, int(math.floor(r.left() * W)))
            y0 = max(0, int(math.floor(r.top() * H)))
            x1 = min(W, int(math.ceil(r.right() * W)))
            y1 = min(H, int(math.ceil(r.bottom() * H)))
            return x0, y0, x1, y1

        x0, y0, x1, y1 = px(outer)
        if x1 - x0 < 2 or y1 - y0 < 2:
            return None
        crop = img.copy(x0, y0, x1 - x0, y1 - y0)
        if bg is not None:
            a = _argb_array(crop)
            b = _argb_array(bg.copy(x0, y0, x1 - x0, y1 - y0))
            diff = np.abs(a[..., :3].astype(np.int16) - b[..., :3].astype(np.int16)).max(axis=2)
            alpha = np.where(diff > _DIFF, 255, 0).astype(np.uint8)
            if g.get('opaque'):
                ix0, iy0, ix1, iy1 = px(clip)
                alpha[max(0, iy0 - y0):max(0, iy1 - y0), max(0, ix0 - x0):max(0, ix1 - x0)] = 255
            a[..., 3] = alpha
            a = np.ascontiguousarray(a)
            h, w = a.shape[:2]
            crop = _api.QImage(a.data, w, h, 4 * w, _api.QImage.Format.Format_ARGB32).copy()
        return {'img': crop, 'rect': _api.QRectF(x0 / W, y0 / H, (x1 - x0) / W, (y1 - y0) / H),
                'clip': clip, 'bg': bg}

    def _layer_live(self):
        return (self._layer is not None and self._clip_frame.rect is not None
                and (self._clip_frame.dragging() or self._hold))

    def _paint_layer(self, p, area):
        """Фон (или старый кадр) и слой клипа в рамке, где она сейчас."""
        lay = self._layer
        p.drawImage(area, lay['bg'] if lay['bg'] is not None else self._img)
        r0, r1, lr = lay['clip'], self._clip_frame.rect, lay['rect']
        kx = r1.width() / max(1e-9, r0.width())
        ky = r1.height() / max(1e-9, r0.height())
        tgt = _api.QRectF(r1.x() + (lr.x() - r0.x()) * kx, r1.y() + (lr.y() - r0.y()) * ky,
                          lr.width() * kx, lr.height() * ky)
        p.drawImage(self._clip_frame.screen_rect(tgt, area), lay['img'])

    def mousePressEvent(self, ev):
        if ev.button() == _api.Qt.MouseButton.LeftButton and self.has_image():
            area = self.image_rect()
            pos = ev.position()
            if not self._clip_frame.press(pos, area):
                self.clipFramePicked.emit(_api.QPointF(
                    (pos.x() - area.left()) / max(1.0, area.width()),
                    (pos.y() - area.top()) / max(1.0, area.height())))
                self._clip_frame.press(pos, area)
            if self._clip_frame.dragging():
                self._hold = False
                g = self._ghost
                self._layer = (self._build_layer(g) if g is not None and self._clip_frame.rect
                               is not None and self._same_rect(g['clip'], self._clip_frame.rect)
                               else None)
                self.setCursor(self._clip_frame.cursor(self._clip_frame.hit(pos, area)))
                self.update()
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        area = self.image_rect()
        if self._clip_frame.dragging():
            if (ev.buttons() & _api.Qt.MouseButton.LeftButton
                    and self._clip_frame.move(ev.position(), area, ev.modifiers())):
                self.update()
            ev.accept()
            return
        handle = self._clip_frame.hit(ev.position(), area) if self.has_image() else None
        if handle is not None:
            self.setCursor(self._clip_frame.cursor(handle))
        else:
            self.unsetCursor()
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._clip_frame.dragging() and ev.button() == _api.Qt.MouseButton.LeftButton:
            change = self._clip_frame.release()
            self._hold = change is not None and self._layer is not None
            if not self._hold:
                self._layer = None
            self.update()
            if change is not None:
                self.clipFrameEdited.emit(*change)
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def paintEvent(self, ev):
        p = _api.QPainter(self)
        # В окне полного экрана поля вокруг кадра — чёрные, как у плеера.
        p.fillRect(self.rect(), _api.QColor(0, 0, 0) if self.window().isFullScreen()
                   else _api.QColor(_api.C['bg']))
        if self.has_image():
            p.setRenderHint(_api.QPainter.RenderHint.SmoothPixmapTransform, True)
            if self._layer_live():
                self._paint_layer(p, self.image_rect())
            else:
                p.drawImage(self.image_rect(), self._img)
            self._clip_frame.paint(p, self.image_rect())
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
