# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_paint_checkerboard. Public namespace: widgets."""
import widgets as _api


# ─────────────────────────────────────────────────────────────
#  Полноэкранный просмотр изображений (одиночный + сравнение)
# ─────────────────────────────────────────────────────────────
def _paint_checkerboard(painter, rect, cell=11):
    """Рисует «шахматку» в прямоугольнике rect — фон под картинкой с
    прозрачностью, чтобы прозрачные области были ВИДНЫ (как в Photoshop/GIMP),
    а не сливались с тёмным фоном окна (иначе кажется, что прозрачность
    потеряна). Под непрозрачной картинкой шахматка полностью скрыта — для них
    визуально ничего не меняется."""
    r = rect.toRect() if hasattr(rect, 'toRect') else rect
    painter.save()
    painter.setClipRect(r)
    painter.fillRect(r, _api.QColor(0x53, 0x55, 0x60))   # светлая клетка
    dark = _api.QColor(0x3a, 0x3c, 0x46)                  # тёмная клетка
    x0, y0 = r.left(), r.top()
    rows = (r.height() // cell) + 2
    cols = (r.width() // cell) + 2
    for iy in range(rows):
        for ix in range(cols):
            if (ix + iy) & 1:
                painter.fillRect(x0 + ix * cell, y0 + iy * cell, cell, cell, dark)
    painter.restore()

_paint_checkerboard.__module__ = _api.__name__
_api._paint_checkerboard = _paint_checkerboard

class _ZoomImageLabel(_api.QLabel):
    """QLabel, который рисует QPixmap, вписанный в свой размер с сохранением
    пропорций. Сам перерисовывается при изменении размера — так картинка
    масштабируется под окно без растяжения. Под прозрачными картинками рисует
    шахматку, чтобы прозрачность была видна."""
    def __init__(self, pixmap, parent=None):
        super().__init__(parent)
        self._src = pixmap if (pixmap is not None and not pixmap.isNull()) else None
        self._has_alpha = bool(self._src is not None and self._src.hasAlphaChannel())
        self.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background:transparent;")
        self.setMinimumSize(1, 1)
        self.setSizePolicy(_api.QSizePolicy.Policy.Expanding, _api.QSizePolicy.Policy.Expanding)
        if self._src is None:
            self.setText("Не удалось загрузить изображение")
            self.setStyleSheet("background:transparent;color:#a6adc8;font-size:14px;")

    def _scaled(self):
        if self._src is None:
            return None
        return self._src.scaled(
            self.size(), _api.Qt.AspectRatioMode.KeepAspectRatio,
            _api.Qt.TransformationMode.SmoothTransformation)

    def paintEvent(self, e):
        if self._src is None:
            super().paintEvent(e)
            return
        pm = self._scaled()
        if pm is None or pm.isNull():
            super().paintEvent(e)
            return
        dpr = pm.devicePixelRatio() or 1.0
        w = int(round(pm.width() / dpr)); h = int(round(pm.height() / dpr))
        x = (self.width() - w) // 2; y = (self.height() - h) // 2
        p = _api.QPainter(self)
        if self._has_alpha:
            _api._paint_checkerboard(p, _api.QRect(x, y, w, h))
        p.drawPixmap(_api.QRect(x, y, w, h), pm)
        p.end()

    def resizeEvent(self, e):
        self.update()
        super().resizeEvent(e)

_ZoomImageLabel.__module__ = _api.__name__
_api._ZoomImageLabel = _ZoomImageLabel

class ImageFullscreenViewer(_api.QDialog):
    """Полноэкранный просмотр одного изображения. Esc или двойной клик — закрыть."""
    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_api.os.path.basename(path))
        self.setStyleSheet("QDialog{background:#0e0e16;}")
        self.setAttribute(_api.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        lay = _api.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        pix = _api.load_pixmap_any(path, max_dim=4096)
        lay.addWidget(_api._ZoomImageLabel(pix, self), 1)
        _api._add_close_hint(self, lay)

    def keyPressEvent(self, e):
        if e.key() == _api.Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    def mouseDoubleClickEvent(self, e):
        self.close()

ImageFullscreenViewer.__module__ = _api.__name__
_api.ImageFullscreenViewer = ImageFullscreenViewer

class _CompareView(_api.QWidget):
    """Картинка с синхронным зумом (колесо) и панорамированием. Подпись
    (исходник/результат · формат · размер) рисуется ПОВЕРХ изображения в углу,
    а не отдельной строкой — так картинки занимают всю площадь панели. Зум/панораму
    маршрутизируем через owner (диалог), чтобы ОБА вида всегда двигались вместе."""

    def __init__(self, pixmap, caption, owner=None, parent=None, placeholder=None):
        super().__init__(parent)
        self._src = pixmap if (pixmap is not None and not pixmap.isNull()) else None
        self._has_alpha = bool(self._src is not None and self._src.hasAlphaChannel())
        self._caption = caption
        self._placeholder = placeholder or "Не удалось загрузить изображение"
        self._owner = owner             # ImageCompareViewer — синхронизирует виды
        self._zoom = 1.0
        self._off = _api.QPointF(0.0, 0.0)   # смещение центра картинки в пикселях экрана
        self._drag_last = None
        self.setMinimumSize(1, 1)
        self.setSizePolicy(_api.QSizePolicy.Policy.Expanding, _api.QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setStyleSheet("background:#0e0e16;")

    def _fit_scale(self):
        if self._src is None:
            return 1.0
        w = self._src.width(); h = self._src.height()
        if w <= 0 or h <= 0:
            return 1.0
        return min(self.width() / w, self.height() / h)

    def set_view(self, zoom, off):
        self._zoom = zoom
        self._off = _api.QPointF(off)
        self._clamp()
        self.update()

    def set_pixmap_caption(self, pixmap, caption):
        """Подменяет картинку и подпись на лету (замена исходника из проводника) —
        без пересоздания виджета, чтобы не терять зум/панораму парного вида."""
        self._src = pixmap if (pixmap is not None and not pixmap.isNull()) else None
        self._has_alpha = bool(self._src is not None and self._src.hasAlphaChannel())
        self._caption = caption
        self.update()

    def _clamp(self):
        if self._src is None or self._zoom <= 1.0:
            self._off = _api.QPointF(0.0, 0.0)
            return
        scale = self._fit_scale() * self._zoom
        dw = self._src.width() * scale
        dh = self._src.height() * scale
        max_x = max(0.0, (dw - self.width()) / 2.0)
        max_y = max(0.0, (dh - self.height()) / 2.0)
        self._off = _api.QPointF(
            max(-max_x, min(max_x, self._off.x())),
            max(-max_y, min(max_y, self._off.y())))

    def paintEvent(self, e):
        p = _api.QPainter(self)
        p.fillRect(self.rect(), _api.QColor(14, 14, 22))
        if self._src is not None:
            p.setRenderHint(_api.QPainter.RenderHint.SmoothPixmapTransform)
            scale = self._fit_scale() * self._zoom
            dw = self._src.width() * scale
            dh = self._src.height() * scale
            x = (self.width() - dw) / 2.0 + self._off.x()
            y = (self.height() - dh) / 2.0 + self._off.y()
            # Под прозрачной картинкой — шахматка, чтобы было видно, что
            # прозрачность сохранена (а не «потеряна» на тёмном фоне окна).
            if self._has_alpha:
                _api._paint_checkerboard(p, _api.QRectF(x, y, dw, dh).toRect())
            p.drawPixmap(_api.QRectF(x, y, dw, dh), self._src, _api.QRectF(self._src.rect()))
        else:
            p.setPen(_api.QColor("#a6adc8"))
            p.drawText(self.rect().adjusted(20, 20, -20, -20),
                       _api.Qt.AlignmentFlag.AlignCenter | _api.Qt.TextFlag.TextWordWrap,
                       self._placeholder)
        self._paint_caption(p)

    def _paint_caption(self, p):
        if not self._caption:
            return
        f = p.font(); f.setPointSize(11); f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(self._caption)
        th = fm.height()
        pad = 7
        rect = _api.QRectF(10, 10, tw + pad * 2, th + pad)
        p.setRenderHint(_api.QPainter.RenderHint.Antialiasing)
        p.setPen(_api.Qt.PenStyle.NoPen)
        p.setBrush(_api.QColor(0, 0, 0, 160))
        p.drawRoundedRect(rect, 5, 5)
        p.setPen(_api.QColor("#ffffff"))
        p.drawText(rect, _api.Qt.AlignmentFlag.AlignCenter, self._caption)

    def _broadcast(self, zoom, off):
        """Применяет зум/смещение к ОБОИМ видам через owner. Если owner нет —
        двигаем только себя (запасной вариант)."""
        if self._owner is not None and hasattr(self._owner, "_apply_view"):
            self._owner._apply_view(zoom, off)
        else:
            self.set_view(zoom, off)

    def wheelEvent(self, e):
        # Колесо (без модификаторов) зумит ОБА вида одновременно — синхронизацию
        # делает owner._apply_view. Ctrl не требуется: в полноэкранном сравнении
        # прокручивать нечего, поэтому колесо = зум.
        delta = e.angleDelta().y()
        if delta == 0:
            return
        factor = 1.2 if delta > 0 else (1.0 / 1.2)
        new_zoom = max(1.0, min(8.0, self._zoom * factor))
        new_off = self._off
        if self._zoom > 0:
            r = new_zoom / self._zoom            # зум от центра — масштабируем смещение
            new_off = _api.QPointF(self._off.x() * r, self._off.y() * r)
        self._broadcast(new_zoom, new_off)
        e.accept()

    def mousePressEvent(self, e):
        if e.button() == _api.Qt.MouseButton.LeftButton and self._zoom > 1.0:
            self._drag_last = e.position()
            self.setCursor(_api.Qt.CursorShape.ClosedHandCursor)
        else:
            e.ignore()   # без зума — отдаём клик диалогу (двойной клик закрывает)

    def mouseMoveEvent(self, e):
        if self._drag_last is not None:
            d = e.position() - self._drag_last
            self._drag_last = e.position()
            new_off = _api.QPointF(self._off.x() + d.x(), self._off.y() + d.y())
            self._broadcast(self._zoom, new_off)   # панорама — тоже на оба вида

    def mouseReleaseEvent(self, e):
        self._drag_last = None
        self.unsetCursor()

_CompareView.__module__ = _api.__name__
_api._CompareView = _CompareView
