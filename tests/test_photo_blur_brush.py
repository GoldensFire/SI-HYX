# -*- coding: utf-8 -*-
"""Кисть «Размытие» во вкладке «Редактирование фото».

Проверяем главное: мазок замыливает картинку ТОЛЬКО под кистью (пересчитывается
прямоугольник вокруг сегмента, а не весь кадр), сила берётся из ползунка, а
Ctrl+Z возвращает исходные пиксели (штрих кладётся в историю на нажатии ЛКМ).
"""
import numpy as np
import pytest
from PyQt6.QtCore import QPointF

import photo_tab
from photo_tab import InpaintCanvas


def _canvas(qapp, w=300, h=200):
    c = InpaintCanvas()
    img = np.zeros((h, w, 3), np.uint8)
    img[:, w // 2:] = 255            # резкая вертикальная граница чёрное|белое
    c.set_image_bgr(img)
    c.resize(w + 100, h + 100)
    c._scale = 1.0                   # 1 экранный px = 1 px изображения
    c.set_tool(InpaintCanvas.TOOL_BLUR)
    return c


def _stroke(canvas, pts):
    """Полный цикл мазка так же, как его ведут события мыши."""
    canvas._push_history()
    canvas.bake_paint()
    canvas._begin_blur_stroke()
    canvas._last_img_pt = None
    for p in pts:
        canvas._paint_to(p)
    canvas._end_blur_stroke()


def test_blur_stroke_smudges_only_under_brush(qapp):
    c = _canvas(qapp)
    c.set_brush(40)
    c.set_blur_strength(15)
    before = c.img_bgr.copy()

    _stroke(c, [QPointF(150, 50), QPointF(150, 150)])

    diff = np.abs(c.img_bgr.astype(int) - before.astype(int)).sum(axis=2)
    # Граница под мазком размылась: чистое чёрное/белое стало серым.
    assert 0 < c.img_bgr[100, 150][0] < 255
    # Вне мазка — ни одного тронутого пикселя (по вертикали и по горизонтали).
    assert diff[:20].sum() == 0 and diff[180:].sum() == 0
    assert diff[:, :100].sum() == 0 and diff[:, 200:].sum() == 0


def test_blur_strength_changes_result(qapp):
    weak, strong = _canvas(qapp), _canvas(qapp)
    for c, s in ((weak, 2), (strong, 40)):
        c.set_brush(60)
        c.set_blur_strength(s)
        _stroke(c, [QPointF(150, 100)])
    # Чем больше степень, тем дальше от границы «уползает» серое пятно.
    spread = lambda c: int((np.abs(c.img_bgr[100].astype(int) - [0, 0, 0]).sum(1) > 0).sum())
    assert spread(strong) > spread(weak)


def test_blur_stroke_is_undoable(qapp):
    c = _canvas(qapp)
    c.set_brush(30)
    before = c.img_bgr.copy()
    _stroke(c, [QPointF(150, 40), QPointF(150, 120)])
    assert not np.array_equal(c.img_bgr, before)

    c.undo()
    assert np.array_equal(c.img_bgr, before)


def test_blur_history_snapshot_not_stale(qapp):
    """Пиксели правятся на месте, поэтому мазок обязан работать по НОВОМУ массиву:
    иначе кэш PNG-кодирования истории (сравнение по identity) вернул бы для
    следующего шага уже размытую картинку и отмена сломалась бы."""
    c = _canvas(qapp)
    c.set_brush(30)
    start = c.img_bgr.copy()
    _stroke(c, [QPointF(150, 60)])
    after_first = c.img_bgr.copy()
    _stroke(c, [QPointF(80, 60)])

    c.undo()
    assert np.array_equal(c.img_bgr, after_first)
    c.undo()
    assert np.array_equal(c.img_bgr, start)


def test_blur_button_selects_tool(qapp):
    tab = photo_tab.InpaintTab(None)
    tab.canvas.set_image_bgr(np.zeros((60, 60, 3), np.uint8))
    tab.btn_blur.click()
    assert tab.canvas._tool == InpaintCanvas.TOOL_BLUR

    tab.sld_blur.setValue(33)
    assert tab.lbl_blur.text() == "33"
    assert tab.canvas._blur_strength == 33
