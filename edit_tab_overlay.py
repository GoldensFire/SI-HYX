# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
# edit_tab_overlay.py — наложение НЕПОДВИЖНОЙ картинки (логотип, водяной знак,
# рамка) поверх видео во вкладке «Монтаж».
#
# Слой стоит между edit_tab_base и edit_tab_widgets: холст (VideoCanvas) рисует
# и правит накладки, EditTab собирает по ним ffmpeg-фильтр экспорта, а список
# слоёв (OverlayLayersPanel) даёт удалить/кадрировать/подкрутить прозрачность.
#
# Одна накладка = ImageOverlay: исходная картинка + рамка кадрирования (в долях
# самой картинки) + прямоугольник на кадре (в долях КАДРА) + прозрачность и
# поворот. Доли, а не пиксели, потому что в плеере может идти прокси меньшего
# разрешения (см. ProxyWorker), а в файл пишется полный кадр — одни и те же
# доли одинаково ложатся и туда, и туда.
#
# ВАЖНО про порядок фильтров: накладка подмешивается ДО кадрирования видео
# (crop=…) и до вшивания субтитров — ровно как её видно в плеере, где рамка
# кадрирования лежит поверх кадра с картинкой. Значит, кадрирование может
# «отрезать» часть накладки — это и есть WYSIWYG, а не ошибка.

import os

from config import (
    QColor, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPainter, QPen, QPointF, QRectF, QSize, QSlider, QVBoxLayout,
    QWidget, Qt, get_icon, pyqtSignal
)
from edit_tab_base import C, make_icon_btn
from PyQt6.QtGui import QIcon, QImage, QPixmap, QTransform
from PyQt6.QtWidgets import QDialogButtonBox, QPushButton, QSizePolicy
# Сам ffmpeg-граф накладок живёт в utils: его собирает не только Монтаж, но и
# ProcessWorker (режим обрезки «Перекодировать настройками «Обработки»»), а тому
# нельзя тянуть за собой edit_tab_base — тот выставляет env Qt-бэкендов и обязан
# импортироваться ДО создания QApplication.
from utils import (  # noqa: F401  (re-export: исторический адрес функции)
    overlay_chroma_format, overlay_filter_graph
)

# Минимальный размер накладки на кадре (доля кадра) — иначе её не поймать мышью.
MIN_SIZE_NORM = 0.02
# Ручки рамки (в пикселях экрана).
HANDLE_PX = 8


def load_overlay_image(path):
    """Читает картинку с диска в QImage (ARGB32, с альфой). None — не вышло."""
    img = QImage(str(path))
    if img.isNull():
        return None
    if img.format() != QImage.Format.Format_ARGB32:
        img = img.convertToFormat(QImage.Format.Format_ARGB32)
    return img


def qimage_to_bgra(img):
    """QImage → numpy BGRA (для воркеров, которые правят кадры через OpenCV).

    Format_ARGB32 на little-endian лежит в памяти как B,G,R,A. .copy() обязателен:
    без него numpy остаётся видом на буфер QImage (см. _TrackAttachDialog)."""
    import numpy as np
    if img is None or img.isNull():
        return None
    if img.format() != QImage.Format.Format_ARGB32:
        img = img.convertToFormat(QImage.Format.Format_ARGB32)
    bpl = img.bytesPerLine()
    ptr = img.constBits()
    ptr.setsize(bpl * img.height())
    buf = np.frombuffer(ptr, np.uint8).reshape(img.height(), bpl)
    return buf[:, :img.width() * 4].reshape(img.height(), img.width(), 4).copy()


def fit_rect_norm(img_w, img_h, frame_w, frame_h, width_frac=0.28,
                  margin=0.04):
    """Стартовое место картинки на кадре: ширина — доля кадра, высота — по
    пропорциям картинки, левый верхний угол с отступом от края. Всё в долях
    кадра (0..1), поэтому не зависит ни от прокси, ни от разрешения."""
    img_w = max(1, int(img_w)); img_h = max(1, int(img_h))
    frame_w = max(1, int(frame_w)); frame_h = max(1, int(frame_h))
    w = max(MIN_SIZE_NORM, min(1.0, float(width_frac)))
    # Пиксели картинки → доли кадра: px_h = px_w * (img_h / img_w).
    h = w * (frame_w / float(frame_h)) * (img_h / float(img_w))
    if h > 1.0:                       # очень «высокая» картинка — вписываем по высоте
        w *= 1.0 / h
        h = 1.0
    x = min(margin, max(0.0, 1.0 - w))
    y = min(margin, max(0.0, 1.0 - h))
    return QRectF(x, y, w, h)


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
        self.crop = QRectF(crop) if crop is not None else QRectF(0.0, 0.0, 1.0, 1.0)
        self.opacity = max(0.05, min(1.0, float(opacity)))
        self.angle = float(angle)
        self._cropped = None
        cw, ch = self.cropped_size()
        self.rect = (QRectF(rect) if rect is not None
                     else fit_rect_norm(cw, ch, self.frame_w, self.frame_h))

    # ── имя/размеры ──────────────────────────────────────────────────────────
    @property
    def name(self):
        return os.path.basename(self.path) or "картинка"

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
        r = QRectF(crop_norm).normalized()
        r = QRectF(max(0.0, r.x()), max(0.0, r.y()),
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
        self.rect = QRectF(self.rect.x(), self.rect.y(),
                           self.rect.width(), max(MIN_SIZE_NORM, h))

    def set_rect(self, rect_norm):
        r = QRectF(rect_norm).normalized()
        self.rect = QRectF(r.x(), r.y(),
                           max(MIN_SIZE_NORM, r.width()),
                           max(MIN_SIZE_NORM, r.height()))

    def move_by(self, dx, dy):
        self.rect = QRectF(self.rect.x() + float(dx), self.rect.y() + float(dy),
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
        img = src.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
        if self.opacity < 0.999:
            faded = QImage(img.width(), img.height(), QImage.Format.Format_ARGB32)
            faded.fill(QColor(0, 0, 0, 0))
            p = QPainter(faded)
            p.setOpacity(self.opacity)
            p.drawImage(0, 0, img)
            p.end()
            img = faded
        if abs(self.angle) > 0.01:
            cx, cy = x + w / 2.0, y + h / 2.0
            img = img.transformed(QTransform().rotate(self.angle),
                                  Qt.TransformationMode.SmoothTransformation)
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


# ─── ffmpeg ───────────────────────────────────────────────────────────────────
def render_overlays(items, out_dir, frame_w=None, frame_h=None):
    """Пишет PNG всех видимых накладок в out_dir. → список (путь, x, y)."""
    out = []
    for i, it in enumerate(items or []):
        png = os.path.join(str(out_dir), f"sihyx_overlay_{i}.png")
        got = it.save_png(png, frame_w, frame_h)
        if got is not None:
            out.append(got)
    return out


# ─── Диалог кадрирования картинки ────────────────────────────────────────────
class _CropCanvas(QWidget):
    """Картинка с рамкой обрезки: 8 ручек по углам/сторонам + перетаскивание
    самой рамки. Тот же приём, что у кадрирования видео на холсте плеера, но по
    самой картинке (результат — доли исходника)."""

    changed = pyqtSignal()

    def __init__(self, image, crop, parent=None):
        super().__init__(parent)
        self._img = image
        self._crop = QRectF(crop)
        self._drag = None
        self._anchor = None
        self._start = None
        self.setMinimumSize(360, 260)
        self.setMouseTracking(True)

    def crop_norm(self):
        return QRectF(self._crop).normalized()

    def reset(self):
        self._crop = QRectF(0.0, 0.0, 1.0, 1.0)
        self.changed.emit()
        self.update()

    # ── геометрия ────────────────────────────────────────────────────────────
    def image_rect(self):
        """Куда вписана картинка в виджете (letterbox)."""
        if self._img is None or self._img.isNull():
            return QRectF(self.rect())
        w, h = self.width(), self.height()
        k = min(w / self._img.width(), h / self._img.height())
        rw, rh = self._img.width() * k, self._img.height() * k
        return QRectF((w - rw) / 2.0, (h - rh) / 2.0, rw, rh)

    def _to_norm(self, pt, clamp=True):
        r = self.image_rect()
        if r.width() <= 0 or r.height() <= 0:
            return None
        x = (pt.x() - r.left()) / r.width()
        y = (pt.y() - r.top()) / r.height()
        if clamp:
            x = max(0.0, min(1.0, x)); y = max(0.0, min(1.0, y))
        return QPointF(x, y)

    def _crop_screen(self):
        r = self.image_rect()
        c = self._crop
        return QRectF(r.left() + c.x() * r.width(), r.top() + c.y() * r.height(),
                      c.width() * r.width(), c.height() * r.height())

    def _handle_at(self, pt):
        r = self._crop_screen()
        m = HANDLE_PX + 2
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
            'tl': Qt.CursorShape.SizeFDiagCursor, 'br': Qt.CursorShape.SizeFDiagCursor,
            'tr': Qt.CursorShape.SizeBDiagCursor, 'bl': Qt.CursorShape.SizeBDiagCursor,
            'l': Qt.CursorShape.SizeHorCursor, 'r': Qt.CursorShape.SizeHorCursor,
            't': Qt.CursorShape.SizeVerCursor, 'b': Qt.CursorShape.SizeVerCursor,
            'move': Qt.CursorShape.SizeAllCursor,
        }.get(handle, Qt.CursorShape.CrossCursor)

    def _apply_drag(self, npt):
        d = self._drag
        s = self._start
        if d == 'move':
            dx = npt.x() - self._anchor.x()
            dy = npt.y() - self._anchor.y()
            x = max(0.0, min(1.0 - s.width(), s.x() + dx))
            y = max(0.0, min(1.0 - s.height(), s.y() + dy))
            self._crop = QRectF(x, y, s.width(), s.height())
            return
        l, t = s.left(), s.top()
        r, b = s.right(), s.bottom()
        x = max(0.0, min(1.0, npt.x())); y = max(0.0, min(1.0, npt.y()))
        mn = 0.02
        if 'l' in d: l = min(x, r - mn)
        if 'r' in d: r = max(x, l + mn)
        if 't' in d: t = min(y, b - mn)
        if 'b' in d: b = max(y, t + mn)
        self._crop = QRectF(l, t, r - l, b - t)

    # ── мышь ─────────────────────────────────────────────────────────────────
    def mousePressEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(ev)
        h = self._handle_at(ev.position())
        n = self._to_norm(ev.position())
        if h is None:
            # Клик мимо рамки — тянем новую от этой точки.
            self._crop = QRectF(n.x(), n.y(), 0.0, 0.0)
            h = 'br'
        self._drag = h
        self._anchor = n
        self._start = QRectF(self._crop)
        ev.accept()

    def mouseMoveEvent(self, ev):
        if self._drag and (ev.buttons() & Qt.MouseButton.LeftButton):
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
                c = QRectF(0.0, 0.0, 1.0, 1.0)
            self._crop = c
            self.changed.emit()
            self.update()
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(C['bg']))
        if self._img is None or self._img.isNull():
            p.end(); return
        r = self.image_rect()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        # «Шахматка» под картинкой — видно прозрачные места.
        p.fillRect(r, QColor(C['surface2']))
        p.drawImage(r, self._img)
        cr = self._crop_screen()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 120))
        for part in (QRectF(r.left(), r.top(), r.width(), cr.top() - r.top()),
                     QRectF(r.left(), cr.bottom(), r.width(), r.bottom() - cr.bottom()),
                     QRectF(r.left(), cr.top(), cr.left() - r.left(), cr.height()),
                     QRectF(cr.right(), cr.top(), r.right() - cr.right(), cr.height())):
            if part.width() > 0 and part.height() > 0:
                p.drawRect(part)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(C['accent']), 2))
        p.drawRect(cr)
        p.setBrush(QColor(C['accent']))
        p.setPen(Qt.PenStyle.NoPen)
        for hx, hy in ((cr.left(), cr.top()), (cr.center().x(), cr.top()),
                       (cr.right(), cr.top()), (cr.left(), cr.center().y()),
                       (cr.right(), cr.center().y()), (cr.left(), cr.bottom()),
                       (cr.center().x(), cr.bottom()), (cr.right(), cr.bottom())):
            p.drawRect(QRectF(hx - HANDLE_PX / 2, hy - HANDLE_PX / 2,
                              HANDLE_PX, HANDLE_PX))
        p.end()


class OverlayCropDialog(QDialog):
    """«Кадрировать картинку»: рамка обрезки по самой картинке. Результат —
    доли исходника (crop_norm), их и кладём в ImageOverlay.set_crop."""

    def __init__(self, overlay, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Кадрирование: {overlay.name}")
        self.resize(720, 560)
        self._ovl = overlay
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        hint = QLabel("Потяните рамку за углы или стороны — в кадр попадёт "
                      "только выделенная часть картинки.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {C['text3']}; font-size: 12px;")
        lay.addWidget(hint)
        self.canvas = _CropCanvas(overlay.source, overlay.crop, self)
        lay.addWidget(self.canvas, 1)
        self.lbl_size = QLabel("")
        self.lbl_size.setStyleSheet(f"color: {C['text2']}; font-size: 12px;")
        row = QHBoxLayout(); row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.lbl_size, 1)
        btn_reset = QPushButton("Весь кадр")
        btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_reset.clicked.connect(self.canvas.reset)
        row.addWidget(btn_reset, 0)
        lay.addLayout(row)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Ok).setText("Применить")
        box.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
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


# ─── Список слоёв ────────────────────────────────────────────────────────────
class OverlayLayersPanel(QWidget):
    """Список наложенных картинок: выбор слоя, кадрирование, сброс, удаление и
    прозрачность выбранного. Панель прячется целиком, когда слоёв нет.

    Панель живёт в узкой (196 px) боковой панели Монтажа, поэтому у всего здесь
    задан ЯВНЫЙ минимальный размер, а строки прокручиваются: раньше при нехватке
    высоты Qt ужимал список до полоски в одну плашку выделения (её и принимали
    за прогресс-бар), а подпись «Прозрачность» наезжала на кнопки слоя.
    Прозрачность разведена на две строки (подпись + процент, под ними ползунок) —
    в одну строку на такой ширине она не помещалась.
    """

    selected = pyqtSignal(int)
    cropRequested = pyqtSignal(int)
    deleteRequested = pyqtSignal(int)
    opacityChanged = pyqtSignal(int, float)
    resetRequested = pyqtSignal(int)

    # Высота списка: одна строка ~22 px. Показываем минимум две (видно, что
    # слоёв может быть несколько), максимум четыре — дальше прокрутка, чтобы
    # панель не выдавливала кнопки и шкалу уровня звука.
    ROW_PX = 22
    MIN_ROWS = 2
    MAX_ROWS = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self._syncing = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)

        # Заголовок + счётчик слоёв (сразу видно, сколько картинок наложено).
        head = QHBoxLayout(); head.setContentsMargins(0, 0, 0, 0); head.setSpacing(4)
        title = QLabel("Слои (картинки)")
        title.setStyleSheet(f"color: {C['text3']}; font-size: 11px; font-weight: 700;")
        head.addWidget(title, 0)
        head.addStretch(1)
        self.lbl_count = QLabel("0")
        self.lbl_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_count.setMinimumWidth(18)
        self.lbl_count.setStyleSheet(
            f"color: {C['accent']}; background: {C['surface3']};"
            f"border: 1px solid {C['border2']}; border-radius: 7px;"
            "font-size: 10px; font-weight: 700; padding: 0 4px;")
        head.addWidget(self.lbl_count, 0)
        lay.addLayout(head)

        self.list = QListWidget()
        self.list.setIconSize(QSize(24, 16))
        self.list.setUniformItemSizes(True)
        self.list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.setMinimumHeight(self.MIN_ROWS * self.ROW_PX + 8)
        # Выделение — не сплошная заливка акцентом (на сплюснутом списке она и
        # выглядела «полоской прогресса»), а мягкая подложка с акцентной чертой
        # слева. Прозрачная черта у невыбранных строк держит текст на месте.
        self.list.setStyleSheet(f"""
            QListWidget {{ background: {C['surface3']}; color: {C['text2']};
                border: 1px solid {C['border2']}; border-radius: 5px;
                font-size: 11px; outline: none; padding: 2px; }}
            QListWidget::item {{ padding: 2px 4px; border-radius: 3px;
                border-left: 3px solid transparent; }}
            QListWidget::item:hover {{ background: {C['surface2']}; }}
            QListWidget::item:selected {{ background: {C['surface2']};
                color: {C['accent']}; border-left: 3px solid {C['accent']}; }}
        """)
        self.list.currentRowChanged.connect(self._on_row)
        lay.addWidget(self.list)

        row = QHBoxLayout(); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(4)
        self.btn_crop = self._mini('fa5s.crop-alt', "Кадрировать картинку")
        self.btn_crop.clicked.connect(
            lambda: self.cropRequested.emit(self.list.currentRow()))
        self.btn_reset = self._mini('fa5s.undo', "Сбросить поворот и размер")
        self.btn_reset.clicked.connect(
            lambda: self.resetRequested.emit(self.list.currentRow()))
        self.btn_del = self._mini('fa5s.trash-alt', "Удалить слой", danger=True)
        self.btn_del.clicked.connect(
            lambda: self.deleteRequested.emit(self.list.currentRow()))
        row.addWidget(self.btn_crop); row.addWidget(self.btn_reset)
        row.addWidget(self.btn_del); row.addStretch(1)
        lay.addLayout(row)

        lay.addSpacing(2)
        op_head = QHBoxLayout(); op_head.setContentsMargins(0, 0, 0, 0)
        op_head.setSpacing(4)
        lbl = QLabel("Прозрачность")
        lbl.setStyleSheet(f"color: {C['text3']}; font-size: 11px;")
        op_head.addWidget(lbl, 0)
        op_head.addStretch(1)
        self.lbl_opacity = QLabel("100%")
        self.lbl_opacity.setStyleSheet(
            f"color: {C['text2']}; font-size: 11px; font-weight: 700;")
        op_head.addWidget(self.lbl_opacity, 0)
        lay.addLayout(op_head)

        self.sld_opacity = QSlider(Qt.Orientation.Horizontal)
        self.sld_opacity.setRange(5, 100)
        self.sld_opacity.setValue(100)
        self.sld_opacity.setFixedHeight(18)
        self.sld_opacity.setToolTip("Прозрачность выбранного слоя")
        self.sld_opacity.valueChanged.connect(self._on_opacity)
        lay.addWidget(self.sld_opacity)

        # Панель никогда не сжимается ниже суммы собственных минимумов — именно
        # это раньше и рождало наложение подписей друг на друга.
        self.setSizePolicy(self.sizePolicy().horizontalPolicy(),
                           QSizePolicy.Policy.Minimum)
        self.setVisible(False)

    def _mini(self, icon, tip, danger=False):
        b = make_icon_btn("")
        b.setIcon(get_icon(icon, color=C['red']) if danger else get_icon(icon))
        b.setIconSize(QSize(14, 14))
        b.setFixedSize(28, 24)
        b.setToolTip(tip)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        if danger:
            b.setStyleSheet(b.styleSheet() + f"""
                QPushButton:hover {{ background: {C['red']}; color: #11111b;
                    border-color: {C['red']}; }}
            """)
        return b

    def _on_row(self, row):
        self._sync_opacity(row)
        self.selected.emit(row)

    def _on_opacity(self, v):
        self.lbl_opacity.setText(f"{int(v)}%")
        row = self.list.currentRow()
        if row >= 0 and not self._syncing:
            self.opacityChanged.emit(row, v / 100.0)

    def _sync_opacity(self, row):
        if 0 <= row < len(self._items):
            self._syncing = True
            self.sld_opacity.setValue(int(round(self._items[row].opacity * 100)))
            self._syncing = False
        self.lbl_opacity.setText(f"{int(self.sld_opacity.value())}%")

    @staticmethod
    def _thumb(item):
        """Значок строки — сама накладка (кадрированная), вписанная в 24×16.
        По нему слой узнаётся быстрее, чем по имени файла."""
        img = item.cropped()
        if img is None or img.isNull():
            return None
        return QIcon(QPixmap.fromImage(
            img.scaled(24, 16, Qt.AspectRatioMode.KeepAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)))

    def refresh(self, items, current=-1):
        """Перестраивает список по актуальным накладкам."""
        self._items = list(items or [])
        self.list.blockSignals(True)
        self.list.clear()
        for it in self._items:
            label = it.name
            if it.crop.width() < 0.999 or it.crop.height() < 0.999:
                label += " (кадр.)"
            row = QListWidgetItem(label)
            row.setToolTip(it.path or label)
            row.setSizeHint(QSize(0, self.ROW_PX))
            icon = self._thumb(it)
            if icon is not None:
                row.setIcon(icon)
            self.list.addItem(row)
        if self._items:
            row = current if 0 <= current < len(self._items) else len(self._items) - 1
            self.list.setCurrentRow(row)
        self.list.blockSignals(False)
        self._sync_opacity(self.list.currentRow())
        has = bool(self._items)
        self.lbl_count.setText(str(len(self._items)))
        # Список ровно под содержимое (но в пределах MIN/MAX строк): одна
        # картинка не должна занимать высоту четырёх, пятая — уезжает в прокрутку.
        rows = max(self.MIN_ROWS, min(self.MAX_ROWS, len(self._items)))
        self.list.setFixedHeight(rows * self.ROW_PX + 8)
        self.setVisible(has)
        for b in (self.btn_crop, self.btn_del, self.btn_reset):
            b.setEnabled(has)
        self.sld_opacity.setEnabled(has)
