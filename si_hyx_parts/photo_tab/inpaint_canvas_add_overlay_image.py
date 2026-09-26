# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""InpaintCanvas: add_overlay_image. Public namespace: photo_tab."""
import photo_tab as _api


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
