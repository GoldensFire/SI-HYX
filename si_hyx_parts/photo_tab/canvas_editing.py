# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Холст фото: слои и альфа, история правок, поворот и отражение, кадрирование, чёрные полосы и пересчёт координат."""
import photo_tab as _api


class InpaintCanvasEditingMixin:
    """Холст фото: слои и альфа, история правок, поворот и отражение, кадрирование, чёрные полосы и пересчёт координат."""

    def add_overlay_image(self, arr):
        """Кладёт изображение arr (BGR H×W×3 или BGRA H×W×4) как плавающий слой
        поверх текущего — центрированно. Прозрачность PNG/WEBP сохраняется.
        Пользователь перетаскивает его мышью до вжигания (Enter, клик вне, смена
        инструмента). Предыдущий незакреплённый объект вжигается."""
        if self.img_bgr is None or arr is None:
            return
        self._commit_pending()
        arr = _api._np.ascontiguousarray(arr)
        has_alpha = (arr.ndim == 3 and arr.shape[2] == 4)
        if has_alpha:
            qimg = _api.np_bgra_to_qimage(arr)
        else:
            qimg = _api.np_bgr_to_qimage(arr)
        h, w = arr.shape[:2]
        bh, bw = self.img_bgr.shape[:2]
        pix = _api.QPixmap.fromImage(qimg)
        # Если картинка крупнее холста — вписываем её в ~85% кадра (иначе слой
        # вылезал бы за границы и его углы-ручки были бы недосягаемы).
        dw, dh = float(w), float(h)
        fit = min(1.0, 0.85 * bw / dw, 0.85 * bh / dh)
        dw *= fit; dh *= fit
        cx = (bw - dw) / 2.0
        cy = (bh - dh) / 2.0
        self._pending = {'kind': 'image', 'pix': pix,
                         'pos': _api.QPointF(cx, cy), 'w': dw, 'h': dh}
        self._pending_move = False
        self._pending_resize = None
        self.update()
        self.statusChanged.emit(
            "Курсор: тяните за уголки — размер, внутри — перенос. "
            "Enter/клик вне — вжать, Esc — убрать.")

    def _rebuild_base(self):
        if self.img_bgr is None:
            self._base_pix = None
            return
        # После «Удалить фон» — рисуем объект на шахматке (как в Photoshop), чтобы
        # прозрачные области были видны. Иначе — обычное непрозрачное изображение.
        if self._alpha is not None:
            h, w = self.img_bgr.shape[:2]
            bgra = _api._np.dstack([self.img_bgr, self._alpha])
            rgba = _api.np_bgra_to_qimage(_api._np.ascontiguousarray(bgra))
            pm = _api.QPixmap(w, h)
            pm.fill(_api.Qt.GlobalColor.transparent)
            p = _api.QPainter(pm)
            self._draw_checker(p, w, h)
            p.drawImage(0, 0, rgba)
            p.end()
            self._base_pix = pm
        else:
            self._base_pix = _api.QPixmap.fromImage(_api.np_bgr_to_qimage(self.img_bgr))

    @staticmethod
    def _draw_checker(painter, w, h, cell=16):
        """Шахматка прозрачности (два серых тона) — фон под вырезанным объектом."""
        painter.fillRect(0, 0, w, h, _api.QColor(120, 120, 128))
        painter.setPen(_api.Qt.PenStyle.NoPen)
        painter.setBrush(_api.QColor(150, 150, 158))
        for y in range(0, h, cell):
            for x in range(0, w, cell):
                if ((x // cell) + (y // cell)) % 2 == 0:
                    painter.drawRect(x, y, cell, cell)

    def has_alpha(self) -> bool:
        return self._alpha is not None

    def apply_cutout(self, alpha):
        """Применяет маску переднего плана (RMBG): фон становится прозрачным.
        alpha — numpy (H,W) uint8 [0..255]. Историю НЕ трогаем (её снял вызывающий)."""
        if self.img_bgr is None or alpha is None:
            return
        h, w = self.img_bgr.shape[:2]
        alpha = _api._np.ascontiguousarray(alpha)
        if alpha.shape[:2] != (h, w):
            alpha = _api._cv2.resize(alpha, (w, h), interpolation=_api._cv2.INTER_LINEAR)
        self._alpha = alpha.astype(_api._np.uint8)
        self._rebuild_base()
        self.update()

    def composited_bgra(self):
        """Картинка для СОХРАНЕНИЯ: вжатые мазки кисти + альфа прозрачности.
        Возвращает BGRA (H,W,4), если фон удалён, иначе BGR (H,W,3)."""
        if self.img_bgr is None:
            return None
        bgr = self.composited_bgr()
        if self._alpha is None:
            return bgr
        alpha = self._alpha.copy()
        # Мазки «Кисти» поверх прозрачного фона должны быть видимы → делаем их
        # непрозрачными в альфе (иначе пользователь рисует «в пустоту»).
        if self._paint_layer is not None:
            pa = self._layer_alpha(self._paint_layer)
            alpha = _api._np.maximum(alpha, (pa > 10).astype(_api._np.uint8) * 255)
        return _api._np.ascontiguousarray(_api._np.dstack([bgr, alpha]))

    # ── История / отмена / возврат ──────────────────────────────────────────
    @staticmethod
    def _encode_layer(obj):
        """Сжимает слой истории в PNG (lossless) вместо хранения сырого буфера —
        маски/слой кисти по большей части прозрачны/однородны и жмутся в разы
        (при _HISTORY_MAX=8 и 4 слоях на шаг сырые копии на 4K-фото легко уходят
        в сотни МБ)."""
        if obj is None:
            return None
        if isinstance(obj, _api._np.ndarray):
            ok, buf = _api._cv2.imencode('.png', obj)
            return ('np', buf.tobytes()) if ok else ('raw', obj)
        from PyQt6.QtCore import QBuffer
        ba = _api.QByteArray()
        qbuf = QBuffer(ba)
        qbuf.open(QBuffer.OpenModeFlag.WriteOnly)
        obj.save(qbuf, 'PNG')
        qbuf.close()
        return ('qimg', bytes(ba))

    @staticmethod
    def _decode_layer(enc):
        if enc is None:
            return None
        kind, raw = enc
        if kind == 'raw':
            return raw
        if kind == 'np':
            return _api._cv2.imdecode(_api._np.frombuffer(raw, _api._np.uint8), _api._cv2.IMREAD_UNCHANGED)
        img = _api.QtGuiImage.fromData(raw, 'PNG')
        if img.format() != _api.QtGuiImage.Format.Format_ARGB32_Premultiplied:
            img = img.convertToFormat(_api.QtGuiImage.Format.Format_ARGB32_Premultiplied)
        return img

    def _snapshot(self):
        """Текущее состояние для истории: картинка + маска удаления + слой краски.
        Хранится в сжатом (PNG) виде — см. _encode_layer; любой слой может быть
        None (напр. после очистки)."""
        ov = self._encode_layer(self._overlay)
        pl = self._encode_layer(self._paint_layer)
        al = self._encode_layer(self._alpha)
        if self.img_bgr is self._bgr_snap_src:
            bgr = self._bgr_snap_enc
        else:
            bgr = self._encode_layer(self.img_bgr)
            self._bgr_snap_src = self.img_bgr
            self._bgr_snap_enc = bgr
        return (bgr, ov, pl, al)

    def _push_history(self):
        if self.img_bgr is None:
            return
        self._history.append(self._snapshot())
        if len(self._history) > self._HISTORY_MAX:
            self._history.pop(0)
        # Любое новое действие обнуляет «возврат» — классическое поведение undo/redo.
        self._redo.clear()

    def _restore_state(self, snap, msg):
        img_enc, ov_enc, pl_enc, al_enc = snap
        img = self._decode_layer(img_enc)
        ov = self._decode_layer(ov_enc)
        pl = self._decode_layer(pl_enc)
        al = self._decode_layer(al_enc)
        # Восстановление в «очищенный» холст (img is None) — напр. отмена «Очистить».
        if img is None:
            self.img_bgr = None
            self._overlay = None
            self._paint_layer = None
            self._alpha = None
            self._base_pix = None
            self._has_strokes = False
            self._has_paint = False
            self._crop_a = self._crop_b = None
            self._update_crop_buttons()
            self.update()
            self.statusChanged.emit(msg)
            self.imageChanged.emit()
            return
        same_size = (self.img_bgr is not None
                     and img.shape[:2] == self.img_bgr.shape[:2])
        self.img_bgr = img
        self._overlay = ov
        self._paint_layer = pl
        self._alpha = al
        self._recompute_strokes_flag()
        self._recompute_paint_flag()
        self._rebuild_base()
        if not same_size:
            self._user_zoomed = False
            self._fit()
        self._update_crop_buttons()
        self.update()
        self.statusChanged.emit(msg)
        self.imageChanged.emit()

    def undo(self):
        # Незакреплённый объект сперва вжигаем, чтобы история была согласованной.
        self._commit_pending()
        if not self._history:
            return
        self._redo.append(self._snapshot())
        if len(self._redo) > self._HISTORY_MAX:
            self._redo.pop(0)
        self._restore_state(self._history.pop(), "Отменено.")

    def redo(self):
        self._commit_pending()
        if not self._redo:
            return
        self._history.append(self._snapshot())
        if len(self._history) > self._HISTORY_MAX:
            self._history.pop(0)
        self._restore_state(self._redo.pop(), "Возвращено.")

    # ── Поворот / отражение ─────────────────────────────────────────────────
    def _transform_qimage(self, img, transform):
        """Применяет QTransform к ARGB-слою (маска удаления / краска), сохраняя
        формат premultiplied и точные новые размеры. None → None."""
        if img is None:
            return None
        out = img.transformed(transform, _api.Qt.TransformationMode.FastTransformation)
        if out.format() != _api.QtGuiImage.Format.Format_ARGB32_Premultiplied:
            out = out.convertToFormat(_api.QtGuiImage.Format.Format_ARGB32_Premultiplied)
        return out

    def _after_orient_change(self, msg):
        """Общий хвост поворота/отражения: рамка кадрирования сбрасывается,
        флаги/база/масштаб пересчитываются, история уже снята вызывающим."""
        self._crop_a = self._crop_b = None
        self._recompute_strokes_flag()
        self._recompute_paint_flag()
        self._rebuild_base()
        self._user_zoomed = False
        self._fit()
        self._update_crop_buttons()
        self.update()
        self.statusChanged.emit(msg)
        self.imageChanged.emit()

    def rotate_image(self, clockwise=True):
        """Поворот картинки на 90° (меняет местами ширину/высоту). Согласованно
        поворачивает альфу (numpy) и ARGB-слои (через QTransform)."""
        if self.img_bgr is None:
            return
        self._commit_pending()
        if self.has_crop():
            self.cancel_crop()
        self._push_history()
        from PyQt6.QtGui import QTransform
        # np.rot90: k=-1 = по часовой; QTransform.rotate(+90) тоже по часовой —
        # оба слоя поворачиваются в одну сторону и остаются пиксель-в-пиксель.
        k = -1 if clockwise else 1
        self.img_bgr = _api._np.ascontiguousarray(_api._np.rot90(self.img_bgr, k))
        if self._alpha is not None:
            self._alpha = _api._np.ascontiguousarray(_api._np.rot90(self._alpha, k))
        t = QTransform().rotate(90 if clockwise else -90)
        self._overlay = self._transform_qimage(self._overlay, t)
        self._paint_layer = self._transform_qimage(self._paint_layer, t)
        self._after_orient_change("Повёрнуто.")

    def flip_image(self, horizontal=True):
        """Зеркальное отражение по горизонтали (horizontal=True) или вертикали."""
        if self.img_bgr is None:
            return
        self._commit_pending()
        if self.has_crop():
            self.cancel_crop()
        self._push_history()
        from PyQt6.QtGui import QTransform
        if horizontal:
            self.img_bgr = _api._np.ascontiguousarray(self.img_bgr[:, ::-1])
            if self._alpha is not None:
                self._alpha = _api._np.ascontiguousarray(self._alpha[:, ::-1])
            t = QTransform().scale(-1, 1)
        else:
            self.img_bgr = _api._np.ascontiguousarray(self.img_bgr[::-1])
            if self._alpha is not None:
                self._alpha = _api._np.ascontiguousarray(self._alpha[::-1])
            t = QTransform().scale(1, -1)
        self._overlay = self._transform_qimage(self._overlay, t)
        self._paint_layer = self._transform_qimage(self._paint_layer, t)
        self._after_orient_change("Отражено.")

    def _recompute_strokes_flag(self):
        try:
            self._has_strokes = self._mask_alpha().max() > 10
        except Exception:
            self._has_strokes = False

    def _layer_alpha(self, img):
        """Альфа-канал произвольного ARGB-оверлея как numpy (H,W) uint8."""
        a = img.convertToFormat(_api.QtGuiImage.Format.Format_ARGB32)
        w, h = a.width(), a.height()
        bpl = a.bytesPerLine()
        ptr = a.constBits(); ptr.setsize(bpl * h)
        buf = _api._np.frombuffer(ptr, _api._np.uint8).reshape(h, bpl)
        return _api._np.ascontiguousarray(buf[:, :w * 4].reshape(h, w, 4)[..., 3])

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

    # ── Чёрные полосы ────────────────────────────────────────────────────────
    def detect_black_bars(self):
        """(x0, y0, x1, y1) содержимого без чёрных полос по краям или None, если
        полос нет. Логика ТА ЖЕ, что во вкладке «Обработка» (ProcessWorker):
        линия — полоса, только если ярких (> порога) пикселей в ней не больше
        допуска на шум. Считаем по одному кадру-картинке, поэтому нужен лишь
        разбор счётчиков — сам подсчёт кадров видео здесь не при чём."""
        if self.img_bgr is None or _api._np is None or _api._cv2 is None:
            return None
        from workers import ProcessWorker
        gray = _api._cv2.cvtColor(self.composited_bgr(), _api._cv2.COLOR_BGR2GRAY)
        bright = gray > ProcessWorker._CROP_LUMA_LIMIT
        if self._alpha is not None:
            # Фон уже удалён: прозрачное — не содержимое, иначе «полосой» не
            # считался бы даже полностью пустой край.
            bright &= self._alpha > 10
        ih, iw = gray.shape[:2]
        box = ProcessWorker._crop_from_counts(bright.sum(axis=1),
                                              bright.sum(axis=0), iw, ih)
        if box is None:
            return None
        w, h, x, y = box
        return x, y, x + w, y + h

    def crop_black_bars(self):
        """Убирает чёрные полосы по краям (тот же детект, что в «Обработке»).
        Возвращает (ширина, высота) результата или None, если полос нет."""
        box = self.detect_black_bars()
        if box is None:
            self.statusChanged.emit("Чёрные полосы не обнаружены.")
            return None
        x0, y0, x1, y1 = box
        self._crop_a = _api.QPointF(x0, y0)
        self._crop_b = _api.QPointF(x1, y1)
        # Дальше всё делает обычное кадрирование: снимок для Ctrl+Z, вжигание
        # мазков кисти, обрезка альфы/слоёв, вписывание в окно.
        if not self.apply_crop():
            self.cancel_crop()
            return None
        return x1 - x0, y1 - y0

    def _crop_rect_w(self):
        """Текущая рамка кадрирования в ЭКРАННЫХ координатах (нормализованная)."""
        a = self._i2w(self._crop_a)
        b = self._i2w(self._crop_b)
        return _api.QRectF(a, b).normalized()

    def _crop_handle_at(self, wpt):
        """Какую «ручку» рамки задевает курсор (коорд. виджета). Возвращает один
        из 'tl','tr','bl','br','t','b','l','r','move' или None."""
        if not self.has_crop():
            return None
        r = self._crop_rect_w()
        tol = 10.0
        mx, my = wpt.x(), wpt.y()
        if not (r.left() - tol <= mx <= r.right() + tol
                and r.top() - tol <= my <= r.bottom() + tol):
            return None
        near_l = abs(mx - r.left()) <= tol
        near_r = abs(mx - r.right()) <= tol
        near_t = abs(my - r.top()) <= tol
        near_b = abs(my - r.bottom()) <= tol
        if near_t and near_l: return 'tl'
        if near_t and near_r: return 'tr'
        if near_b and near_l: return 'bl'
        if near_b and near_r: return 'br'
        if near_t: return 't'
        if near_b: return 'b'
        if near_l: return 'l'
        if near_r: return 'r'
        if r.left() < mx < r.right() and r.top() < my < r.bottom():
            return 'move'
        return None

    @staticmethod
    def _crop_cursor(handle):
        cur = {
            'tl': _api.Qt.CursorShape.SizeFDiagCursor, 'br': _api.Qt.CursorShape.SizeFDiagCursor,
            'tr': _api.Qt.CursorShape.SizeBDiagCursor, 'bl': _api.Qt.CursorShape.SizeBDiagCursor,
            't': _api.Qt.CursorShape.SizeVerCursor,  'b': _api.Qt.CursorShape.SizeVerCursor,
            'l': _api.Qt.CursorShape.SizeHorCursor,  'r': _api.Qt.CursorShape.SizeHorCursor,
            'move': _api.Qt.CursorShape.SizeAllCursor,
        }
        return cur.get(handle, _api.Qt.CursorShape.CrossCursor)

    def _drag_crop(self, ipt):
        """Двигает активную ручку рамки. ipt — позиция мыши в коорд. изображения."""
        h, w = self.img_bgr.shape[:2]
        d = self._crop_drag
        a, b = self._crop_start
        l, t = min(a.x(), b.x()), min(a.y(), b.y())
        r, bo = max(a.x(), b.x()), max(a.y(), b.y())
        minsz = 8.0
        if d == 'move':
            bw, bh = r - l, bo - t
            dx = ipt.x() - self._crop_anchor.x()
            dy = ipt.y() - self._crop_anchor.y()
            nl = min(max(l + dx, 0.0), w - bw)
            nt = min(max(t + dy, 0.0), h - bh)
            self._crop_a = _api.QPointF(nl, nt)
            self._crop_b = _api.QPointF(nl + bw, nt + bh)
            return
        x = min(max(ipt.x(), 0.0), float(w))
        y = min(max(ipt.y(), 0.0), float(h))
        if 'l' in d: l = min(x, r - minsz)
        if 'r' in d: r = max(x, l + minsz)
        if 't' in d: t = min(y, bo - minsz)
        if 'b' in d: bo = max(y, t + minsz)
        if self._crop_aspect:
            l, t, r, bo = self._apply_aspect(d, l, t, r, bo, w, h)
        self._crop_a = _api.QPointF(l, t)
        self._crop_b = _api.QPointF(r, bo)

    # ── Пропорции рамки кадрирования (1:1 / 4:3 / 16:9 … на холсте) ───────────
    def _on_crop_aspect_changed(self, idx):
        if idx < 0 or idx >= len(self._crop_aspect_items):
            return
        _, val = self._crop_aspect_items[idx]
        if val is None:
            self._crop_aspect = None
        elif val == 'orig':
            if self.img_bgr is not None:
                h, w = self.img_bgr.shape[:2]
                self._crop_aspect = (w / h) if h else None
            else:
                self._crop_aspect = None
        else:
            self._crop_aspect = float(val)
        # Сразу подгоняем текущую рамку под выбранную пропорцию.
        if self._crop_aspect and self.has_crop():
            self._reshape_crop_to_aspect()
        self._update_crop_buttons()
        self.update()

    def _reshape_crop_to_aspect(self):
        """Подгоняет текущую рамку под self._crop_aspect, сохраняя центр и вписывая
        в границы изображения."""
        if self.img_bgr is None or not self.has_crop():
            return
        h, w = self.img_bgr.shape[:2]
        ratio = self._crop_aspect
        l = min(self._crop_a.x(), self._crop_b.x())
        r = max(self._crop_a.x(), self._crop_b.x())
        t = min(self._crop_a.y(), self._crop_b.y())
        bo = max(self._crop_a.y(), self._crop_b.y())
        cw, ch = r - l, bo - t
        cx, cy = (l + r) / 2.0, (t + bo) / 2.0
        if cw / max(ch, 1e-6) > ratio:
            cw = ch * ratio
        else:
            ch = cw / ratio
        if cw > w:
            cw = w; ch = cw / ratio
        if ch > h:
            ch = h; cw = ch * ratio
        l, r = cx - cw / 2.0, cx + cw / 2.0
        t, bo = cy - ch / 2.0, cy + ch / 2.0
        if l < 0: r -= l; l = 0.0
        if t < 0: bo -= t; t = 0.0
        if r > w: l -= (r - w); r = float(w)
        if bo > h: t -= (bo - h); bo = float(h)
        self._crop_a = _api.QPointF(l, t)
        self._crop_b = _api.QPointF(r, bo)

    def _apply_aspect(self, d, l, t, r, bo, w, h):
        """Возвращает рамку с зафиксированной пропорцией self._crop_aspect под
        активную ручку d (угол — якорь в противоположном углу; сторона — растим
        перпендикуляр симметрично от центра)."""
        ratio = self._crop_aspect
        minsz = 8.0
        if d in ('tl', 'tr', 'bl', 'br'):
            ax = r if 'l' in d else l            # якорь — противоположная сторона
            ay = bo if 't' in d else t
            sx = -1.0 if 'l' in d else 1.0       # направление растяжения от якоря
            sy = -1.0 if 't' in d else 1.0
            width = max(minsz, abs((l if 'l' in d else r) - ax))
            height = max(minsz, abs((t if 't' in d else bo) - ay))
            if width / height > ratio:
                height = width / ratio
            else:
                width = height * ratio
            avail_w = ax if sx < 0 else (w - ax)
            avail_h = ay if sy < 0 else (h - ay)
            if width > avail_w:
                width = avail_w; height = width / ratio
            if height > avail_h:
                height = avail_h; width = height * ratio
            nx = ax + sx * width
            ny = ay + sy * height
            l, r = sorted((ax, nx))
            t, bo = sorted((ay, ny))
        elif 'l' in d or 'r' in d:
            width = max(minsz, r - l)
            height = min(float(h), width / ratio)
            width = height * ratio
            cy = (t + bo) / 2.0
            t, bo = cy - height / 2.0, cy + height / 2.0
            if t < 0: bo -= t; t = 0.0
            if bo > h: t -= (bo - h); bo = float(h)
        else:
            height = max(minsz, bo - t)
            width = min(float(w), height * ratio)
            height = width / ratio
            cx = (l + r) / 2.0
            l, r = cx - width / 2.0, cx + width / 2.0
            if l < 0: r -= l; l = 0.0
            if r > w: l -= (r - w); r = float(w)
        return l, t, r, bo

    # ── Маска для инференса / применение результата ──────────────────────────
    def _mask_alpha(self):
        """Альфа-канал оверлея как numpy (H,W) uint8."""
        a = self._overlay.convertToFormat(_api.QtGuiImage.Format.Format_ARGB32)
        w, h = a.width(), a.height()
        bpl = a.bytesPerLine()
        ptr = a.constBits(); ptr.setsize(bpl * h)
        buf = _api._np.frombuffer(ptr, _api._np.uint8).reshape(h, bpl)
        bgra = buf[:, :w * 4].reshape(h, w, 4)
        return _api._np.ascontiguousarray(bgra[..., 3])

    def get_mask(self):
        """Бинарная маска (H,W) uint8 {0,255}: 255 — где закрашено пользователем."""
        return (self._mask_alpha() > 10).astype(_api._np.uint8) * 255

    # ── Преобразования координат ─────────────────────────────────────────────
    def _fit(self):
        if self.img_bgr is None:
            return
        aw, ah = self.width(), self.height()
        ih, iw = self.img_bgr.shape[:2]
        if iw <= 0 or ih <= 0:
            return
        s = min(aw / iw, ah / ih)
        self._scale = s if s > 0 else 1.0
        self._off = _api.QPointF((aw - iw * self._scale) / 2.0,
                            (ah - ih * self._scale) / 2.0)

    def _w2i(self, pt):
        return _api.QPointF((pt.x() - self._off.x()) / self._scale,
                       (pt.y() - self._off.y()) / self._scale)

    def _i2w(self, pt):
        return _api.QPointF(self._off.x() + pt.x() * self._scale,
                       self._off.y() + pt.y() * self._scale)

    def _img_rect_w(self):
        ih, iw = self.img_bgr.shape[:2]
        return _api.QRectF(self._off.x(), self._off.y(), iw * self._scale, ih * self._scale)

    # ── Скроллбары при сильном приближении ───────────────────────────────────
    def _content_size(self):
        ih, iw = self.img_bgr.shape[:2]
        return iw * self._scale, ih * self._scale

    def _clamp_off(self):
        """Зажимает смещение по той оси, где картинка больше холста, чтобы её
        нельзя было увести за край (как при прокрутке). Где картинка меньше —
        смещение не трогаем (свободное панорамирование/центрирование)."""
        if self.img_bgr is None:
            return
        cw, ch = self._content_size()
        W, H = self.width(), self.height()
        if cw > W:
            self._off.setX(min(0.0, max(self._off.x(), W - cw)))
        if ch > H:
            self._off.setY(min(0.0, max(self._off.y(), H - ch)))
