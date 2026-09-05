# -*- coding: utf-8 -*-
"""«Удалить чёрные полосы» во вкладке «Редактирование фото».

Кнопка обязана резать ровно тем же детектом, что и «Обрезка чёрных полос» во
вкладке «Обработка» (ProcessWorker): линия — полоса, только если ярких пикселей
в ней не больше допуска на шум. Проверяем сам рез, отсутствие полос (ничего не
трогаем), Ctrl+Z и то, что тонкая строка содержимого не срезается.
"""
import numpy as np
from PyQt6.QtCore import QPointF

from photo_tab import InpaintCanvas


def _canvas(w=200, h=120, bar_x=0, bar_y=0):
    """Картинка с белым содержимым и чёрными полями bar_x/bar_y по краям."""
    c = InpaintCanvas()
    img = np.zeros((h, w, 3), np.uint8)
    img[bar_y:h - bar_y if bar_y else h, bar_x:w - bar_x if bar_x else w] = 255
    c.set_image_bgr(img)
    c.resize(w + 100, h + 100)
    return c


def test_crops_side_bars(qapp):
    c = _canvas(bar_x=20)
    assert c.crop_black_bars() == (160, 120)
    assert c.img_bgr.shape[:2] == (120, 160)
    assert (c.img_bgr == 255).all()


def test_crops_top_and_bottom_bars(qapp):
    c = _canvas(bar_y=16)
    assert c.crop_black_bars() == (200, 88)
    assert c.img_bgr.shape[:2] == (88, 200)


def test_no_bars_leaves_image_untouched(qapp):
    c = _canvas()
    before = c.img_bgr.copy()
    assert c.crop_black_bars() is None
    assert np.array_equal(c.img_bgr, before)


def test_undo_returns_full_image(qapp):
    c = _canvas(bar_x=20)
    before = c.img_bgr.copy()
    c.crop_black_bars()
    c.undo()
    assert np.array_equal(c.img_bgr, before)


def test_thin_bright_row_is_content_not_bar(qapp):
    """Строка, чёрная везде кроме мелкого яркого элемента (край панели задач в
    записи экрана), — содержимое: её резать нельзя. Именно этим детект и
    отличается от ffmpeg cropdetect (тот смотрит на СРЕДНЮЮ яркость линии)."""
    c = _canvas(bar_y=10)
    h, w = c.img_bgr.shape[:2]
    c.img_bgr[4, :w // 8] = 255      # 25 ярких пикселей из 200 — выше допуска шума
    size = c.crop_black_bars()
    assert size is not None
    # Верхняя граница ушла к строке 4 (округление к чётности — только наружу),
    # то есть тонкая строка осталась в кадре.
    assert size[1] == h - 4 - 10


def test_crop_ignores_transparent_border(qapp):
    """После «Удалить фон» прозрачные края тоже считаются полосой: пиксели там
    могут быть любого цвета, содержимым их делает только альфа."""
    c = _canvas()
    h, w = c.img_bgr.shape[:2]
    alpha = np.zeros((h, w), np.uint8)
    alpha[:, 30:w - 30] = 255
    c.apply_cutout(alpha)
    assert c.crop_black_bars() == (w - 60, h)


def test_same_detector_as_processing_tab(qapp):
    """Рамка совпадает с той, что даёт ProcessWorker для тех же счётчиков."""
    from workers import ProcessWorker

    c = _canvas(bar_x=20, bar_y=10)
    box = c.detect_black_bars()
    gray = c.img_bgr[:, :, 0]
    bright = gray > ProcessWorker._CROP_LUMA_LIMIT
    h, w = gray.shape
    ref = ProcessWorker._crop_from_counts(bright.sum(axis=1), bright.sum(axis=0), w, h)
    rw, rh, rx, ry = ref
    assert box == (rx, ry, rx + rw, ry + rh)


def test_pending_overlay_committed_before_crop(qapp):
    """Плавающий слой (наложенная картинка) вжимается до реза — иначе он висел бы
    поверх обрезанного кадра со старыми координатами."""
    c = _canvas(bar_x=20)
    c._crop_a = QPointF(0, 0)        # мусор от прошлой рамки не должен мешать
    c._crop_b = None
    assert c.crop_black_bars() == (160, 120)
