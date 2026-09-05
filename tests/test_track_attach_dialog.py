# -*- coding: utf-8 -*-
"""Диалог «Привязать к объекту»: сборка накладки и задания для воркера.

Шрифты в CI могут не иметь нужных глифов (текст рисуется «квадратиками»), поэтому
проверяем не форму букв, а то, что реально ломается при правках: BGRA-конверсия
QImage→numpy (порядок каналов и выравнивание строк), прозрачный фон накладки,
масштаб картинки от размера рамки и содержимое values()."""
import numpy as np
import pytest

dialogs = pytest.importorskip("edit_tab_dialogs")


@pytest.fixture
def dlg(qapp):
    frame = np.zeros((360, 640, 3), np.uint8)
    d = dialogs._TrackAttachDialog(frame, None, start_s=2.0, end_s=30.0,
                                   zone_end_s=12.0)
    yield d
    d.deleteLater()


def test_text_overlay_is_bgra_with_transparent_background(dlg):
    dlg.ed_text.setText("Рука")
    dlg.sp_size.setValue(40)
    dlg.sp_outline.setValue(0)
    dlg._text_color = "#ff0000"          # чистый красный
    dlg._rebuild_overlay()
    ovl = dlg._overlay_bgra
    assert ovl is not None and ovl.dtype == np.uint8 and ovl.shape[2] == 4
    assert ovl.shape[0] > 10 and ovl.shape[1] > 10
    assert ovl[0, 0, 3] == 0             # угол — прозрачный фон, а не чёрный
    opaque = ovl[ovl[:, :, 3] > 200]
    assert len(opaque) > 0
    # Цвет текста в BGRA: B=0, G=0, R=255 — если каналы перепутать, тут будет синий.
    assert opaque[:, 2].min() == 255 and opaque[:, 0].max() == 0


def test_empty_text_gives_no_overlay(dlg):
    dlg.ed_text.setText("   ")
    dlg._rebuild_overlay()
    assert dlg._overlay_bgra is None


def test_image_overlay_scales_to_box_width(dlg):
    dlg._img_bgra = np.full((50, 100, 4), 255, np.uint8)
    dlg.rb_image.setChecked(True)
    dlg._on_kind_changed()
    dlg.canvas.set_box_px((10, 10, 200, 80))
    dlg.sp_img_pct.setValue(50)           # половина ширины рамки → 100 px
    dlg._rebuild_overlay()
    ovl = dlg._overlay_bgra
    assert ovl.shape[1] == 100
    assert ovl.shape[0] == 50             # пропорции сохранены


def test_values_carry_box_anchor_and_range(dlg):
    dlg.canvas.set_box_px((100, 50, 60, 60))
    dlg.cmb_anchor.setCurrentIndex(2)     # «Под областью»
    dlg.sp_off_x.setValue(12)
    dlg.chk_scale.setChecked(True)
    dlg.chk_smooth.setChecked(False)
    dlg._rebuild_overlay()
    v = dlg.values()
    assert v["box"] == (100.0, 50.0, 60.0, 60.0)
    assert v["anchor"] == "bottom"
    assert v["off_x"] == 12 and v["off_y"] == 0
    assert v["scale_with_box"] is True
    assert v["smooth"] == 0.0
    assert v["start_s"] == 2.0
    assert v["end_s"] == 12.0             # включена галочка «до конца зоны»
    dlg.chk_zone.setChecked(False)
    assert dlg.values()["end_s"] == 30.0  # без неё — до конца видео


def test_canvas_box_selection_requires_real_drag(qapp):
    """Одиночный клик (рамка меньше порога) не создаёт область: иначе к объекту
    привязалась бы точка и трекер сразу потерял бы цель."""
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    from edit_tab_widgets import _TrackSelectCanvas
    from photo_tab import np_bgr_to_qimage

    canvas = _TrackSelectCanvas()
    canvas.resize(320, 240)
    canvas.set_image(np_bgr_to_qimage(np.zeros((240, 320, 3), np.uint8)))

    def _ev(kind, x, y):
        return QMouseEvent(kind, QPointF(x, y), Qt.MouseButton.LeftButton,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)

    from PyQt6.QtCore import QEvent
    canvas.mousePressEvent(_ev(QEvent.Type.MouseButtonPress, 10, 10))
    canvas.mouseMoveEvent(_ev(QEvent.Type.MouseMove, 12, 12))
    canvas.mouseReleaseEvent(_ev(QEvent.Type.MouseButtonRelease, 12, 12))
    assert canvas.box_px() is None

    canvas.mousePressEvent(_ev(QEvent.Type.MouseButtonPress, 10, 10))
    canvas.mouseMoveEvent(_ev(QEvent.Type.MouseMove, 90, 70))
    canvas.mouseReleaseEvent(_ev(QEvent.Type.MouseButtonRelease, 90, 70))
    box = canvas.box_px()
    assert box is not None and box[2] > 20 and box[3] > 20
    canvas.deleteLater()
