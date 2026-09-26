# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""InpaintCanvas: detect_black_bars. Public namespace: photo_tab."""
import photo_tab as _api


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
