# -*- coding: utf-8 -*-
"""Колесо мыши над полями со значениями (widgets.WheelBlocker).

Жалоба, из-за которой правила уточнены: правая панель настроек длинная, её
крутят колесом — а числа в полях, над которыми проехал курсор, при включённой
настройке «колёсико меняет значения» молча менялись. Прокрутка панели важнее.
"""
import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import (QApplication, QScrollArea, QSpinBox, QVBoxLayout,
                             QWidget)

import widgets


def _wheel(w):
    return QWheelEvent(QPointF(2, 2), QPointF(w.mapToGlobal(QPoint(2, 2))),
                       QPoint(0, -120), QPoint(0, -120),
                       Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                       Qt.ScrollPhase.NoScrollPhase, False)


class _Spin(QSpinBox):
    """Спинбокс с управляемым «сфокусирован ли» — настоящий фокус в тестах без
    показанного активного окна не выставить."""
    focused = False

    def hasFocus(self):
        return self.focused


@pytest.fixture
def panel(qapp):
    """Спинбокс внутри области прокрутки — как в правой панели вкладки."""
    area = QScrollArea()
    inner = QWidget()
    QVBoxLayout(inner).addWidget(_Spin(inner))
    area.setWidget(inner)
    spin = inner.findChild(_Spin)
    spin.setRange(0, 100)
    spin.setValue(50)
    yield area, spin
    area.deleteLater()
    qapp.processEvents()


@pytest.fixture
def bare(qapp):
    """Тот же спинбокс, но прокручивать вокруг нечего."""
    page = QWidget()
    QVBoxLayout(page).addWidget(_Spin(page))
    spin = page.findChild(_Spin)
    spin.setRange(0, 100)
    spin.setValue(50)
    yield spin
    page.deleteLater()
    qapp.processEvents()


def _send(qapp, on, w):
    blocker = widgets.WheelBlocker(qapp, lambda: on)
    qapp.installEventFilter(blocker)
    try:
        qapp.sendEvent(w, _wheel(w))
    finally:
        qapp.removeEventFilter(blocker)


def test_off_never_changes_value(qapp, panel):
    _area, spin = panel
    _send(qapp, False, spin)
    assert spin.value() == 50


def test_on_but_unfocused_scrolls_instead(qapp, panel):
    """Ровно тот случай, на который жаловались: крутим панель, а не число."""
    _area, spin = panel
    spin.focused = False
    _send(qapp, True, spin)
    assert spin.value() == 50


def test_on_and_focused_changes_value(qapp, panel):
    """Кликнули в поле — значит работают именно с ним, настройка в силе."""
    _area, spin = panel
    spin.focused = True
    _send(qapp, True, spin)
    assert spin.value() != 50


def test_on_outside_scroll_area_changes_value(qapp, bare):
    """Прокручивать нечего — отнимать у колеса единственную работу незачем."""
    bare.focused = False
    _send(qapp, True, bare)
    assert bare.value() != 50


def test_wheel_always_is_untouched(qapp, panel):
    """Ползунок громкости и подобные помечены wheelAlways — их не трогаем."""
    _area, spin = panel
    spin.setProperty("wheelAlways", True)
    spin.focused = False
    _send(qapp, False, spin)
    assert spin.value() != 50
