# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_CropCanvas. Public namespace: edit_tab_overlay."""
import edit_tab_overlay as _api


# ─── Диалог кадрирования картинки ────────────────────────────────────────────
class _CropCanvas(_api.QWidget):
    """Картинка с рамкой обрезки: 8 ручек по углам/сторонам + перетаскивание
    самой рамки. Тот же приём, что у кадрирования видео на холсте плеера, но по
    самой картинке (результат — доли исходника)."""

    changed = _api.pyqtSignal()

    def __init__(self, image, crop, parent=None):
        super().__init__(parent)
        self._img = image
        self._crop = _api.QRectF(crop)
        self._drag = None
        self._anchor = None
        self._start = None
        self.setMinimumSize(360, 260)
        self.setMouseTracking(True)

    def crop_norm(self):
        return _api.QRectF(self._crop).normalized()

    def reset(self):
        self._crop = _api.QRectF(0.0, 0.0, 1.0, 1.0)
        self.changed.emit()
        self.update()

    # ── геометрия ────────────────────────────────────────────────────────────
    def image_rect(self):
        """Куда вписана картинка в виджете (letterbox)."""
        if self._img is None or self._img.isNull():
            return _api.QRectF(self.rect())
        w, h = self.width(), self.height()
        k = min(w / self._img.width(), h / self._img.height())
        rw, rh = self._img.width() * k, self._img.height() * k
        return _api.QRectF((w - rw) / 2.0, (h - rh) / 2.0, rw, rh)

    def _to_norm(self, pt, clamp=True):
        r = self.image_rect()
        if r.width() <= 0 or r.height() <= 0:
            return None
        x = (pt.x() - r.left()) / r.width()
        y = (pt.y() - r.top()) / r.height()
        if clamp:
            x = max(0.0, min(1.0, x)); y = max(0.0, min(1.0, y))
        return _api.QPointF(x, y)

    def _crop_screen(self):
        r = self.image_rect()
        c = self._crop
        return _api.QRectF(r.left() + c.x() * r.width(), r.top() + c.y() * r.height(),
                      c.width() * r.width(), c.height() * r.height())

    def _handle_at(self, pt):
        r = self._crop_screen()
        m = _api.HANDLE_PX + 2
        near_l = abs(pt.x() - r.left()) <= m
        near_r = abs(pt.x() - r.right()) <= m
        near_t = abs(pt.y() - r.top()) <= m
        near_b = abs(pt.y() - r.bottom()) <= m
        inx = r.left() - m <= pt.x() <= r.right() + m
        iny = r.top() - m <= pt.y() <= r.bottom() + m
        if near_l and near_t: return 'tl'
        if near_r and near_t: return 'tr'
        if near_l and near_b: return 'bl'
        if near_r and near_b: return 'br'
        if near_l and iny: return 'l'
        if near_r and iny: return 'r'
        if near_t and inx: return 't'
        if near_b and inx: return 'b'
        if r.contains(pt): return 'move'
        return None

    @staticmethod
    def _cursor(handle):
        return {
            'tl': _api.Qt.CursorShape.SizeFDiagCursor, 'br': _api.Qt.CursorShape.SizeFDiagCursor,
            'tr': _api.Qt.CursorShape.SizeBDiagCursor, 'bl': _api.Qt.CursorShape.SizeBDiagCursor,
            'l': _api.Qt.CursorShape.SizeHorCursor, 'r': _api.Qt.CursorShape.SizeHorCursor,
            't': _api.Qt.CursorShape.SizeVerCursor, 'b': _api.Qt.CursorShape.SizeVerCursor,
            'move': _api.Qt.CursorShape.SizeAllCursor,
        }.get(handle, _api.Qt.CursorShape.CrossCursor)

    def _apply_drag(self, npt):
        d = self._drag
        s = self._start
        if d == 'move':
            dx = npt.x() - self._anchor.x()
            dy = npt.y() - self._anchor.y()
            x = max(0.0, min(1.0 - s.width(), s.x() + dx))
            y = max(0.0, min(1.0 - s.height(), s.y() + dy))
            self._crop = _api.QRectF(x, y, s.width(), s.height())
            return
        l, t = s.left(), s.top()
        r, b = s.right(), s.bottom()
        x = max(0.0, min(1.0, npt.x())); y = max(0.0, min(1.0, npt.y()))
        mn = 0.02
        if 'l' in d: l = min(x, r - mn)
        if 'r' in d: r = max(x, l + mn)
        if 't' in d: t = min(y, b - mn)
        if 'b' in d: b = max(y, t + mn)
        self._crop = _api.QRectF(l, t, r - l, b - t)

    # ── мышь ─────────────────────────────────────────────────────────────────
    def mousePressEvent(self, ev):
        if ev.button() != _api.Qt.MouseButton.LeftButton:
            return super().mousePressEvent(ev)
        h = self._handle_at(ev.position())
        n = self._to_norm(ev.position())
        if h is None:
            # Клик мимо рамки — тянем новую от этой точки.
            self._crop = _api.QRectF(n.x(), n.y(), 0.0, 0.0)
            h = 'br'
        self._drag = h
        self._anchor = n
        self._start = _api.QRectF(self._crop)
        ev.accept()

    def mouseMoveEvent(self, ev):
        if self._drag and (ev.buttons() & _api.Qt.MouseButton.LeftButton):
            n = self._to_norm(ev.position())
            if n is not None:
                self._apply_drag(n)
                self.changed.emit()
                self.update()
            ev.accept()
            return
        self.setCursor(self._cursor(self._handle_at(ev.position())))
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._drag is not None:
            self._drag = None
            c = self._crop.normalized()
            if c.width() < 0.02 or c.height() < 0.02:
                c = _api.QRectF(0.0, 0.0, 1.0, 1.0)
            self._crop = c
            self.changed.emit()
            self.update()
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def paintEvent(self, _ev):
        p = _api.QPainter(self)
        p.fillRect(self.rect(), _api.QColor(_api.C['bg']))
        if self._img is None or self._img.isNull():
            p.end(); return
        r = self.image_rect()
        p.setRenderHint(_api.QPainter.RenderHint.SmoothPixmapTransform, True)
        # «Шахматка» под картинкой — видно прозрачные места.
        p.fillRect(r, _api.QColor(_api.C['surface2']))
        p.drawImage(r, self._img)
        cr = self._crop_screen()
        p.setPen(_api.Qt.PenStyle.NoPen)
        p.setBrush(_api.QColor(0, 0, 0, 120))
        for part in (_api.QRectF(r.left(), r.top(), r.width(), cr.top() - r.top()),
                     _api.QRectF(r.left(), cr.bottom(), r.width(), r.bottom() - cr.bottom()),
                     _api.QRectF(r.left(), cr.top(), cr.left() - r.left(), cr.height()),
                     _api.QRectF(cr.right(), cr.top(), r.right() - cr.right(), cr.height())):
            if part.width() > 0 and part.height() > 0:
                p.drawRect(part)
        p.setBrush(_api.Qt.BrushStyle.NoBrush)
        p.setPen(_api.QPen(_api.QColor(_api.C['accent']), 2))
        p.drawRect(cr)
        p.setBrush(_api.QColor(_api.C['accent']))
        p.setPen(_api.Qt.PenStyle.NoPen)
        for hx, hy in ((cr.left(), cr.top()), (cr.center().x(), cr.top()),
                       (cr.right(), cr.top()), (cr.left(), cr.center().y()),
                       (cr.right(), cr.center().y()), (cr.left(), cr.bottom()),
                       (cr.center().x(), cr.bottom()), (cr.right(), cr.bottom())):
            p.drawRect(_api.QRectF(hx - _api.HANDLE_PX / 2, hy - _api.HANDLE_PX / 2,
                              _api.HANDLE_PX, _api.HANDLE_PX))
        p.end()

_CropCanvas.__module__ = _api.__name__
_api._CropCanvas = _CropCanvas

class OverlayCropDialog(_api.QDialog):
    """«Кадрировать картинку»: рамка обрезки по самой картинке. Результат —
    доли исходника (crop_norm), их и кладём в ImageOverlay.set_crop."""

    def __init__(self, overlay, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Кадрирование: {overlay.name}")
        self.resize(720, 560)
        self._ovl = overlay
        lay = _api.QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        hint = _api.QLabel("Потяните рамку за углы или стороны — в кадр попадёт "
                      "только выделенная часть картинки.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {_api.C['text3']}; font-size: 12px;")
        lay.addWidget(hint)
        self.canvas = _api._CropCanvas(overlay.source, overlay.crop, self)
        lay.addWidget(self.canvas, 1)
        self.lbl_size = _api.QLabel("")
        self.lbl_size.setStyleSheet(f"color: {_api.C['text2']}; font-size: 12px;")
        row = _api.QHBoxLayout(); row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.lbl_size, 1)
        btn_reset = _api.QPushButton("Весь кадр")
        btn_reset.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        btn_reset.clicked.connect(self.canvas.reset)
        row.addWidget(btn_reset, 0)
        lay.addLayout(row)
        box = _api.QDialogButtonBox(_api.QDialogButtonBox.StandardButton.Ok
                               | _api.QDialogButtonBox.StandardButton.Cancel)
        box.button(_api.QDialogButtonBox.StandardButton.Ok).setText("Применить")
        box.button(_api.QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.canvas.changed.connect(self._sync_label)
        self._sync_label()

    def _sync_label(self):
        c = self.canvas.crop_norm()
        src = self._ovl.source
        if src is None or src.isNull():
            return
        self.lbl_size.setText(
            f"Область: {int(round(c.width() * src.width()))}×"
            f"{int(round(c.height() * src.height()))} px")

    def crop_norm(self):
        return self.canvas.crop_norm()

OverlayCropDialog.__module__ = _api.__name__
_api.OverlayCropDialog = OverlayCropDialog
