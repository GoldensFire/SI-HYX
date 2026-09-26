# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""PointOnImageWidget. Public namespace: siquester.widgets_editors."""
import siquester.widgets_editors as _api


class PointOnImageWidget(_api.QWidget):
    """Interactive image where the player clicks to mark a point answer.
    Shows the correct point (and tolerance circle) after reveal, or lets
    the editor reposition it by clicking/dragging.
    Coordinates are normalised 0..1 (x=left→right, y=top→bottom).
    """

    def __init__(self, image_path: str, cx: float, cy: float, deviation: float,
                 siq=None, rnd=0, th=0, price=0, viewer=None, parent=None):
        super().__init__(parent)
        self._cx  = cx; self._cy  = cy; self._dev = deviation
        self._siq = siq; self._rnd = rnd; self._th = th; self._price = price
        self._viewer = viewer
        self._dragging_point = False
        self._revealed = True        # always show answer in editor mode

        # Load image
        self._pm: _api.QPixmap | None = None
        try:
            reader = _api.QImageReader(image_path); reader.setAutoTransform(True)
            img = reader.read()
            if not img.isNull():
                self._pm = _api.QPixmap.fromImage(img)
        except Exception:
            pass
        if self._pm is None or self._pm.isNull():
            try:
                from PIL import Image as _PI
                with _PI.open(image_path) as _pil:
                    _pil = _pil.convert("RGBA")
                    w_px, h_px = _pil.size
                    raw = _pil.tobytes("raw", "RGBA")
                qimg = _api.QImage(raw, w_px, h_px, w_px * 4,
                              _api.QImage.Format.Format_RGBA8888).copy()
                if not qimg.isNull():
                    self._pm = _api.QPixmap.fromImage(qimg)
            except Exception:
                self._pm = None

        self.setCursor(_api.Qt.CursorShape.CrossCursor)
        self.setMinimumHeight(160)
        self.setSizePolicy(_api._Expand, _api._Pref)

        # Info bar
        vl = _api.QVBoxLayout(self); vl.setContentsMargins(0,0,0,4); vl.setSpacing(2)
        self._canvas = _api._PointCanvas(self)
        vl.addWidget(self._canvas, stretch=1)
        info_row = _api.QHBoxLayout(); info_row.setContentsMargins(0, 0, 0, 0); info_row.setSpacing(8)
        self._coord_lbl = _api.QLabel(f"📍 ({cx:.3f}, {cy:.3f})  допуск ±{deviation:.3f}")
        self._coord_lbl.setStyleSheet("color:#a6adc8;font-size:10px;")
        info_row.addWidget(self._coord_lbl)
        info_row.addStretch()
        if siq:
            dev_btn = _api.QPushButton("Допуск…")
            dev_btn.setObjectName(_api._ON_BTN_COMPARE); dev_btn.setFixedHeight(20)
            dev_btn.setStyleSheet("font-size:10px;padding:0 6px;")
            dev_btn.clicked.connect(self._change_deviation)
            info_row.addWidget(dev_btn)
        vl.addLayout(info_row)
        self._canvas.update()

    def _px_to_norm(self, px: int, py: int):
        """Convert canvas pixel coords to normalised 0..1. Returns None if outside image."""
        r = self._canvas.rect()
        if not self._pm or r.width() == 0 or r.height() == 0:
            return None
        asp = self._pm.width() / self._pm.height()
        if r.width() / max(r.height(), 1) > asp:
            iw = int(r.height() * asp); ih = r.height()
        else:
            iw = r.width(); ih = int(r.width() / max(asp, 0.001))
        ox = (r.width()  - iw) // 2
        oy = (r.height() - ih) // 2
        # Only accept clicks inside the actual image rect
        if px < ox or px > ox + iw or py < oy or py > oy + ih:
            return None
        nx = max(0.0, min(1.0, (px - ox) / iw))
        ny = max(0.0, min(1.0, (py - oy) / ih))
        return nx, ny

    def mousePressEvent(self, e):
        if e.button() == _api.Qt.MouseButton.LeftButton:
            result = self._px_to_norm(int(e.position().x()), int(e.position().y()))
            if result is not None:
                self._dragging_point = True
                self._cx, self._cy = result
                self._canvas.update(); self._update_coord_lbl()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._dragging_point:
            result = self._px_to_norm(int(e.position().x()), int(e.position().y()))
            if result is not None:
                self._cx, self._cy = result
                self._canvas.update(); self._update_coord_lbl()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == _api.Qt.MouseButton.LeftButton and self._dragging_point:
            self._dragging_point = False
            # Push undo on the ResultPage before saving
            if self._viewer:
                rp = None
                try:
                    rp = self._viewer.parent()
                    while rp and not hasattr(rp, '_push_undo'):
                        rp = rp.parent()
                    if rp and hasattr(rp, '_push_undo'):
                        rp._push_undo()
                except Exception:
                    pass
            self._save_point()
        super().mouseReleaseEvent(e)

    def _update_coord_lbl(self):
        self._coord_lbl.setText(
            f"📍 ({self._cx:.3f}, {self._cy:.3f})  допуск ±{self._dev:.3f}")

    def _change_deviation(self):
        val, ok = _api.QInputDialog.getDouble(
            self, "Допуск", "Радиус допуска (0.01 – 0.5):",
            value=self._dev, min=0.01, max=0.5, decimals=3)
        if ok:
            self._dev = val; self._update_coord_lbl()
            self._canvas.update(); self._save_point()

    def _save_point(self):
        if not self._siq: return
        try:
            qs = self._siq.rounds[self._rnd]["themes"][self._th]["questions"]
            q_idx = _api._q_idx(qs, self._price)
            # Update in-memory
            qs[q_idx]["answers"] = [f"{self._cx:.4f},{self._cy:.4f}"]
            # Update XML
            root, ns_url, tag, q_el = self._siq._xml_nav_q(self._rnd, self._th, q_idx)
            # Update or create right/answer
            right_el = q_el.find(tag("right"))
            if right_el is None:
                right_el = _api.ET.SubElement(q_el, tag("right"))
            ans_els = right_el.findall(tag("answer"))
            if ans_els:
                ans_els[0].text = f"{self._cx:.4f},{self._cy:.4f}"
            else:
                a = _api.ET.SubElement(right_el, tag("answer"))
                a.text = f"{self._cx:.4f},{self._cy:.4f}"
            # Update answerDeviation
            params_el = q_el.find(tag("params"))
            if params_el is not None:
                for p in params_el.findall(tag("param")):
                    if p.get("name") == "answerDeviation":
                        p.text = f"{self._dev:.4f}"; break
                else:
                    dp = _api.ET.SubElement(params_el, tag("param"))
                    dp.set("name", "answerDeviation"); dp.text = f"{self._dev:.4f}"
            self._siq._save_xml(root, ns_url)
        except Exception as ex:
            _api._logger.warning(f"[save_point] {ex}")

PointOnImageWidget.__module__ = _api.__name__
_api.PointOnImageWidget = PointOnImageWidget

class _PointCanvas(_api.QWidget):
    """Draws the image with the answer point and tolerance circle."""

    def __init__(self, owner: '_api.PointOnImageWidget', parent=None):
        super().__init__(parent)
        self._o = owner
        self.setSizePolicy(_api._Expand, _api._Expand)
        self.setMinimumHeight(140)

    def sizeHint(self):
        pm = self._o._pm
        if pm:
            w = self.width() or 380
            return _api.QSize(w, min(400, int(w * pm.height() / max(pm.width(), 1))))
        return _api.QSize(380, 220)

    def paintEvent(self, _):
        p = _api.QPainter(self); p.setRenderHint(_api.QPainter.RenderHint.Antialiasing)
        r = self.rect()

        pm = self._o._pm
        if pm and not pm.isNull():
            asp = pm.width() / pm.height()
            if r.width() / max(r.height(), 1) > asp:
                iw = int(r.height() * asp); ih = r.height()
            else:
                iw = r.width(); ih = int(r.width() / max(asp, 0.001))
            ox = (r.width()  - iw) // 2
            oy = (r.height() - ih) // 2
            scaled = pm.scaled(iw, ih,
                                _api.Qt.AspectRatioMode.KeepAspectRatio,
                                _api.Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(ox, oy, scaled)

            # Tolerance circle
            cx_px = ox + int(self._o._cx * iw)
            cy_px = oy + int(self._o._cy * ih)
            dev_px = int(self._o._dev * min(iw, ih))

            circle_pen = p.pen()
            circle_pen.setColor(_api.QColor(88, 166, 255, 160))
            circle_pen.setWidth(2)
            p.setPen(circle_pen)
            p.setBrush(_api.QBrush(_api.QColor(88, 166, 255, 30)))
            p.drawEllipse(cx_px - dev_px, cy_px - dev_px, dev_px * 2, dev_px * 2)

            # Point marker
            p.setPen(_api.Qt.PenStyle.NoPen)
            p.setBrush(_api.QBrush(_api.QColor(_api._C_RED)))
            p.drawEllipse(cx_px - 7, cy_px - 7, 14, 14)
            p.setBrush(_api.QBrush(_api.QColor("white")))
            p.drawEllipse(cx_px - 3, cy_px - 3, 6, 6)

            # Crosshair lines
            cross_pen = p.pen()
            cross_pen.setColor(_api.QColor(248, 81, 73, 200))
            cross_pen.setWidth(1)
            p.setPen(cross_pen)
            p.drawLine(cx_px, oy, cx_px, oy + ih)
            p.drawLine(ox, cy_px, ox + iw, cy_px)
        else:
            p.fillRect(r, _api.QColor(_api._C_BG2))
            p.setPen(_api.QColor(_api._C_TEXT4))
            p.drawText(r, _api._AlignC, "Изображение не найдено")
        p.end()

_PointCanvas.__module__ = _api.__name__
_api._PointCanvas = _PointCanvas
