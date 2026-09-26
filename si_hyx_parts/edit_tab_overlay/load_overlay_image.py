# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""load_overlay_image. Public namespace: edit_tab_overlay."""
import edit_tab_overlay as _api


def load_overlay_image(path):
    """Читает картинку с диска в QImage (ARGB32, с альфой). None — не вышло."""
    img = _api.QImage(str(path))
    if img.isNull():
        return None
    if img.format() != _api.QImage.Format.Format_ARGB32:
        img = img.convertToFormat(_api.QImage.Format.Format_ARGB32)
    return img

load_overlay_image.__module__ = _api.__name__
_api.load_overlay_image = load_overlay_image

def qimage_to_bgra(img):
    """QImage → numpy BGRA (для воркеров, которые правят кадры через OpenCV).

    Format_ARGB32 на little-endian лежит в памяти как B,G,R,A. .copy() обязателен:
    без него numpy остаётся видом на буфер QImage (см. _TrackAttachDialog)."""
    import numpy as np
    if img is None or img.isNull():
        return None
    if img.format() != _api.QImage.Format.Format_ARGB32:
        img = img.convertToFormat(_api.QImage.Format.Format_ARGB32)
    bpl = img.bytesPerLine()
    ptr = img.constBits()
    ptr.setsize(bpl * img.height())
    buf = np.frombuffer(ptr, np.uint8).reshape(img.height(), bpl)
    return buf[:, :img.width() * 4].reshape(img.height(), img.width(), 4).copy()

qimage_to_bgra.__module__ = _api.__name__
_api.qimage_to_bgra = qimage_to_bgra

def fit_rect_norm(img_w, img_h, frame_w, frame_h, width_frac=0.28,
                  margin=0.04):
    """Стартовое место картинки на кадре: ширина — доля кадра, высота — по
    пропорциям картинки, левый верхний угол с отступом от края. Всё в долях
    кадра (0..1), поэтому не зависит ни от прокси, ни от разрешения."""
    img_w = max(1, int(img_w)); img_h = max(1, int(img_h))
    frame_w = max(1, int(frame_w)); frame_h = max(1, int(frame_h))
    w = max(_api.MIN_SIZE_NORM, min(1.0, float(width_frac)))
    # Пиксели картинки → доли кадра: px_h = px_w * (img_h / img_w).
    h = w * (frame_w / float(frame_h)) * (img_h / float(img_w))
    if h > 1.0:                       # очень «высокая» картинка — вписываем по высоте
        w *= 1.0 / h
        h = 1.0
    x = min(margin, max(0.0, 1.0 - w))
    y = min(margin, max(0.0, 1.0 - h))
    return _api.QRectF(x, y, w, h)

fit_rect_norm.__module__ = _api.__name__
_api.fit_rect_norm = fit_rect_norm

class ImageOverlay:
    """Одна картинка поверх видео.

    crop  — рамка кадрирования В ДОЛЯХ САМОЙ КАРТИНКИ (QRectF 0..1);
    rect  — место на кадре В ДОЛЯХ КАДРА (QRectF 0..1, может частично выходить);
    angle — поворот в градусах (по часовой), вокруг центра rect;
    opacity — 0..1.
    """

    def __init__(self, path, image, frame_w, frame_h, rect=None, crop=None,
                 opacity=1.0, angle=0.0):
        self.path = str(path) if path else ""
        self.source = image
        self.frame_w = max(1, int(frame_w))
        self.frame_h = max(1, int(frame_h))
        self.crop = _api.QRectF(crop) if crop is not None else _api.QRectF(0.0, 0.0, 1.0, 1.0)
        self.opacity = max(0.05, min(1.0, float(opacity)))
        self.angle = float(angle)
        self._cropped = None
        cw, ch = self.cropped_size()
        self.rect = (_api.QRectF(rect) if rect is not None
                     else _api.fit_rect_norm(cw, ch, self.frame_w, self.frame_h))

    # ── имя/размеры ──────────────────────────────────────────────────────────
    @property
    def name(self):
        return _api.os.path.basename(self.path) or "картинка"

    def cropped_size(self):
        """Размер видимой (кадрированной) части картинки в пикселях исходника."""
        if self.source is None or self.source.isNull():
            return (1, 1)
        w = max(1, int(round(self.crop.width() * self.source.width())))
        h = max(1, int(round(self.crop.height() * self.source.height())))
        return (w, h)

    def cropped(self):
        """QImage видимой части (кэшируется до смены рамки кадрирования)."""
        if self._cropped is not None:
            return self._cropped
        img = self.source
        if img is None or img.isNull():
            return None
        r = self.crop
        if r.width() >= 0.999 and r.height() >= 0.999 \
                and r.x() <= 0.001 and r.y() <= 0.001:
            self._cropped = img
        else:
            x = int(round(r.x() * img.width()))
            y = int(round(r.y() * img.height()))
            w, h = self.cropped_size()
            x = max(0, min(img.width() - 1, x))
            y = max(0, min(img.height() - 1, y))
            w = max(1, min(img.width() - x, w))
            h = max(1, min(img.height() - y, h))
            self._cropped = img.copy(x, y, w, h)
        return self._cropped

    # ── правка ───────────────────────────────────────────────────────────────
    def set_crop(self, crop_norm, keep_width=True):
        """Меняет рамку кадрирования. Высота места на кадре пересчитывается по
        новым пропорциям (иначе картинка растянулась бы после обрезки)."""
        r = _api.QRectF(crop_norm).normalized()
        r = _api.QRectF(max(0.0, r.x()), max(0.0, r.y()),
                   min(1.0, r.width()), min(1.0, r.height()))
        if r.width() < 0.01 or r.height() < 0.01:
            return False
        if r.right() > 1.0:
            r.moveRight(1.0)
        if r.bottom() > 1.0:
            r.moveBottom(1.0)
        self.crop = r
        self._cropped = None
        if keep_width:
            self.fix_aspect()
        return True

    def fix_aspect(self):
        """Подгоняет высоту места на кадре под пропорции кадрированной картинки
        (ширину не трогаем — её задаёт пользователь)."""
        cw, ch = self.cropped_size()
        h = self.rect.width() * (self.frame_w / float(self.frame_h)) * (ch / float(cw))
        self.rect = _api.QRectF(self.rect.x(), self.rect.y(),
                           self.rect.width(), max(_api.MIN_SIZE_NORM, h))

    def set_rect(self, rect_norm):
        r = _api.QRectF(rect_norm).normalized()
        self.rect = _api.QRectF(r.x(), r.y(),
                           max(_api.MIN_SIZE_NORM, r.width()),
                           max(_api.MIN_SIZE_NORM, r.height()))

    def move_by(self, dx, dy):
        self.rect = _api.QRectF(self.rect.x() + float(dx), self.rect.y() + float(dy),
                           self.rect.width(), self.rect.height())

    def aspect(self):
        cw, ch = self.cropped_size()
        return cw / float(ch)

    # ── геометрия/рендер под КАДР ────────────────────────────────────────────
    def pixel_rect(self, frame_w=None, frame_h=None):
        """Место накладки в пикселях кадра: (x, y, w, h), без учёта поворота."""
        fw = int(frame_w or self.frame_w)
        fh = int(frame_h or self.frame_h)
        w = max(1, int(round(self.rect.width() * fw)))
        h = max(1, int(round(self.rect.height() * fh)))
        x = int(round(self.rect.x() * fw))
        y = int(round(self.rect.y() * fh))
        return (x, y, w, h)

    def rendered(self, frame_w=None, frame_h=None):
        """Готовая накладка ДЛЯ КАДРА: картинка обрезана, отмасштабирована,
        повёрнута, прозрачность вжата в альфу. Возвращает (QImage, x, y), где
        x/y — левый верхний угол в пикселях кадра (у повёрнутой — угол её
        описанного прямоугольника)."""
        src = self.cropped()
        if src is None or src.isNull():
            return (None, 0, 0)
        x, y, w, h = self.pixel_rect(frame_w, frame_h)
        img = src.scaled(w, h, _api.Qt.AspectRatioMode.IgnoreAspectRatio,
                         _api.Qt.TransformationMode.SmoothTransformation)
        if self.opacity < 0.999:
            faded = _api.QImage(img.width(), img.height(), _api.QImage.Format.Format_ARGB32)
            faded.fill(_api.QColor(0, 0, 0, 0))
            p = _api.QPainter(faded)
            p.setOpacity(self.opacity)
            p.drawImage(0, 0, img)
            p.end()
            img = faded
        if abs(self.angle) > 0.01:
            cx, cy = x + w / 2.0, y + h / 2.0
            img = img.transformed(_api.QTransform().rotate(self.angle),
                                  _api.Qt.TransformationMode.SmoothTransformation)
            x = int(round(cx - img.width() / 2.0))
            y = int(round(cy - img.height() / 2.0))
        return (img, x, y)

    def save_png(self, out_path, frame_w=None, frame_h=None):
        """Пишет готовую накладку в PNG (RGBA). Возвращает (путь, x, y) или None."""
        img, x, y = self.rendered(frame_w, frame_h)
        if img is None:
            return None
        if not img.save(str(out_path), "PNG"):
            return None
        return (str(out_path), x, y)

ImageOverlay.__module__ = _api.__name__
_api.ImageOverlay = ImageOverlay

# ─── ffmpeg ───────────────────────────────────────────────────────────────────
def render_overlays(items, out_dir, frame_w=None, frame_h=None):
    """Пишет PNG всех видимых накладок в out_dir. → список (путь, x, y)."""
    out = []
    for i, it in enumerate(items or []):
        png = _api.os.path.join(str(out_dir), f"sihyx_overlay_{i}.png")
        got = it.save_png(png, frame_w, frame_h)
        if got is not None:
            out.append(got)
    return out

render_overlays.__module__ = _api.__name__
_api.render_overlays = render_overlays
