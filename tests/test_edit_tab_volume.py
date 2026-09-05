# -*- coding: utf-8 -*-
"""Громкость в «Монтаже»: мгновенный прыжок по клику и mute кликом по динамику.

  • VolumeSlider обязан ставить значение РОВНО в точку клика (как полоса
    воспроизведения), а не подкрадываться page-step'ами;
  • клик по значку динамика (VolumeLabel) — выключение звука и возврат к
    ПРЕЖНЕМУ уровню, а не к 100 и не к нулю навсегда.

Ползунок берём настоящий и с настоящей геометрией: арифметика клика считается
по стилю (желоб/ручка), на «игрушечном» объекте её не проверить.
"""
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent

edit_tab_widgets = pytest.importorskip("edit_tab_widgets")
edit_tab = pytest.importorskip("edit_tab")
VolumeSlider = edit_tab_widgets.VolumeSlider
VolumeLabel = edit_tab_widgets.VolumeLabel


def _click(widget, x, y=None):
    """Настоящее событие мыши (press+release) в точке x внутри виджета."""
    y = widget.height() / 2 if y is None else y
    for typ in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
        ev = QMouseEvent(typ, QPointF(x, y), QPointF(x, y),
                         Qt.MouseButton.LeftButton,
                         Qt.MouseButton.LeftButton if typ == QEvent.Type.MouseButtonPress
                         else Qt.MouseButton.NoButton,
                         Qt.KeyboardModifier.NoModifier)
        widget.event(ev)


@pytest.fixture
def vol(qapp):
    sl = VolumeSlider(Qt.Orientation.Horizontal)
    sl.setRange(0, 100)
    sl.setValue(100)
    sl.resize(96, 20)          # та же ширина, что в панели плеера
    return sl


def test_click_jumps_to_point(vol):
    """Клик в середину шкалы даёт ~50%, а не «на шаг ближе к курсору»."""
    _click(vol, vol.width() / 2)
    assert 35 <= vol.value() <= 65, vol.value()


def test_click_near_start_is_not_page_step(vol):
    """Клик у левого края уводит громкость в ноль сразу, а не на 90 (page-step)."""
    _click(vol, 0)
    assert vol.value() == 0


def test_click_far_right_is_max(vol):
    vol.setValue(0)
    _click(vol, vol.width())
    assert vol.value() == 100


def test_drag_follows_cursor(vol):
    """Протяжка после клика продолжает вести ручку за курсором."""
    x0 = vol.width() * 0.2
    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(x0, 10), QPointF(x0, 10),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    vol.event(press)
    low = vol.value()
    x1 = vol.width() * 0.8
    move = QMouseEvent(QEvent.Type.MouseMove, QPointF(x1, 10), QPointF(x1, 10),
                       Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier)
    vol.event(move)
    assert vol.value() > low + 30


def test_wheel_still_steps_by_5(vol, qapp):
    """Колёсико не сломано новым обработчиком мыши."""
    from PyQt6.QtGui import QWheelEvent
    from PyQt6.QtCore import QPoint
    ev = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 120),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    vol.setValue(50)
    vol.event(ev)
    assert vol.value() == 55


# ── mute кликом по динамику ─────────────────────────────────────────────────
def test_label_click_emits(qapp):
    lbl = VolumeLabel(lambda: None)
    got = []
    lbl.clicked.connect(lambda: got.append(1))
    _click(lbl, 5, 5)
    assert got == [1]


def _tab_stub(value=70):
    """Минимальный «self» для EditTab.toggle_mute: только ползунок."""
    box = {'v': value}
    sl = SimpleNamespace(value=lambda: box['v'],
                         setValue=lambda v: box.__setitem__('v', int(v)))
    return SimpleNamespace(vol_slider=sl, _vol_before_mute=100), box


def test_toggle_mute_restores_previous_level():
    st, box = _tab_stub(70)
    edit_tab.EditTab.toggle_mute(st)
    assert box['v'] == 0
    edit_tab.EditTab.toggle_mute(st)
    assert box['v'] == 70          # именно прежний уровень, не 100


def test_toggle_mute_from_manual_zero_gives_sound():
    """Ползунок утащили в 0 руками — клик по динамику обязан дать звук."""
    st, box = _tab_stub(0)
    st._vol_before_mute = 0
    edit_tab.EditTab.toggle_mute(st)
    assert box['v'] == 100


def test_toggle_mute_without_slider_is_noop():
    st = SimpleNamespace(vol_slider=None)
    edit_tab.EditTab.toggle_mute(st)   # не должно падать
