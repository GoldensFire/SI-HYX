# -*- coding: utf-8 -*-
"""Alt + колесо больше не гоняет горизонтальный скроллбар.

Qt по Alt+колесо прокручивает область ПО ГОРИЗОНТАЛИ, и списки/таблицы уезжали
вбок от случайно зажатого Alt. Глобальный HoverTipManager съедает такое колесо
до того, как оно дойдёт до области прокрутки (просьба пользователя), а обычную
прокрутку и виджеты со своей обработкой колеса не трогает.
"""
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import (QLabel, QListWidget, QScrollArea, QVBoxLayout,
                             QWidget)

import widgets


def _wheel(alt: bool) -> QWheelEvent:
    mods = (Qt.KeyboardModifier.AltModifier if alt
            else Qt.KeyboardModifier.NoModifier)
    return QWheelEvent(QPointF(10.0, 10.0), QPointF(10.0, 10.0),
                       QPoint(0, 0), QPoint(0, -120),
                       Qt.MouseButton.NoButton, mods,
                       Qt.ScrollPhase.NoScrollPhase, False)


def _filter(obj, alt: bool) -> bool:
    return widgets.HoverTipManager().eventFilter(obj, _wheel(alt))


def test_alt_wheel_is_eaten_for_scroll_areas(qapp):
    area = QScrollArea()
    lst = QListWidget()
    assert _filter(area, True) is True
    assert _filter(area.viewport(), True) is True
    assert _filter(lst, True) is True
    assert _filter(lst.verticalScrollBar(), True) is True


def test_plain_wheel_still_scrolls(qapp):
    """Без Alt колесо проходит как обычно — прокрутку мы не ломаем."""
    area = QScrollArea()
    assert _filter(area, False) is False
    assert _filter(area.viewport(), False) is False


def test_alt_wheel_does_not_move_the_bar_on_a_live_widget(qapp):
    """Проверено на живом виджете, а не только на возврате фильтра.

    Alt+колесо на Windows приходит уже ГОРИЗОНТАЛЬНЫМ: дельту в X кладёт сам
    виндовый плагин Qt (qwindowsmousehandler), модификатор при этом остаётся —
    по нему фильтр событие и ловит. Без фильтра список уезжает вбок."""
    lst = QListWidget()
    for _ in range(50):
        lst.addItem("строка " + "y" * 80)
    lst.resize(200, 100)
    lst.show()
    qapp.processEvents()
    bar = lst.horizontalScrollBar()
    assert bar.maximum() > 0                      # ехать есть куда

    event = QWheelEvent(QPointF(50.0, 50.0),
                        lst.viewport().mapToGlobal(QPoint(50, 50)).toPointF(),
                        QPoint(-120, 0), QPoint(-120, 0),
                        Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.AltModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    mgr = widgets.HoverTipManager()
    qapp.installEventFilter(mgr)
    try:
        bar.setValue(0)
        qapp.sendEvent(lst.viewport(), event)
        qapp.processEvents()
        assert bar.value() == 0
    finally:
        qapp.removeEventFilter(mgr)
        lst.close()


def test_alt_wheel_left_alone_for_ordinary_widgets(qapp):
    """Холсты и прочие виджеты со своей обработкой колеса не задеты."""
    page = QWidget()
    lay = QVBoxLayout(page)
    canvas = QLabel("холст", page)
    lay.addWidget(canvas)
    assert _filter(canvas, True) is False
    assert _filter(page, True) is False
