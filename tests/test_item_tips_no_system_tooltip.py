# -*- coding: utf-8 -*-
"""Подсказки ячеек списков и таблиц идут через _InfoTipPopup, а не QToolTip.

item.setToolTip(...) Qt показывает системным синим окном — пользователь его
запретил, а в списке паков оно всё равно всплывало с путём к файлу."""
from PyQt6.QtCore import QEvent, QPoint, QPointF
from PyQt6.QtGui import QEnterEvent, QHelpEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (QListWidget, QListWidgetItem, QStyledItemDelegate,
                             QTableWidget, QPushButton, QHBoxLayout, QWidget,
                             QToolTip)
from PyQt6.QtGui import QCursor


def _tip_event(widget, pos):
    return QHelpEvent(QEvent.Type.ToolTip, pos, widget.mapToGlobal(pos))


def _manager():
    from widgets import HoverTipManager
    return HoverTipManager()


def test_list_item_tooltip_uses_the_custom_popup(qapp):
    from widgets import _InfoTipPopup
    view = QListWidget()
    item = QListWidgetItem("Пак (80).siq")
    item.setToolTip("C:/Downloads/Пак (80).siq")
    view.addItem(item)
    view.resize(300, 200)
    view.show()
    pos = view.visualItemRect(item).center()
    try:
        QCursor.setPos(view.viewport().mapToGlobal(pos))
        qapp.processEvents()
        assert _manager().eventFilter(view.viewport(), _tip_event(view.viewport(), pos))
        qapp.processEvents()
        popup = _InfoTipPopup.instance()
        assert popup.isVisible() and popup.text() == "C:/Downloads/Пак (80).siq"
    finally:
        _InfoTipPopup.instance().hide()
        view.close()


def test_header_tooltip_uses_the_custom_popup(qapp):
    from widgets import _InfoTipPopup
    table = QTableWidget(1, 1)
    head = table.horizontalHeader()
    table.setHorizontalHeaderLabels(["Цена"])
    table.horizontalHeaderItem(0).setToolTip("Из чего сложилась цена")
    table.show()
    try:
        pos = QPoint(head.sectionViewportPosition(0) + 5, 5)
        QCursor.setPos(head.viewport().mapToGlobal(pos))
        qapp.processEvents()
        assert _manager().eventFilter(head.viewport(), _tip_event(head.viewport(), pos)) \
            or _manager().eventFilter(head, _tip_event(head, pos))
        qapp.processEvents()
        assert _InfoTipPopup.instance().text() == "Из чего сложилась цена"
    finally:
        _InfoTipPopup.instance().hide()
        table.close()


def test_a_delegate_with_its_own_help_event_is_left_alone(qapp):
    class Own(QStyledItemDelegate):
        def helpEvent(self, *args):
            return True

    view = QListWidget()
    view.setItemDelegate(Own(view))
    item = QListWidgetItem("x")
    item.setToolTip("своё")
    view.addItem(item)
    view.show()
    try:
        pos = view.visualItemRect(item).center()
        assert not _manager().eventFilter(view.viewport(),
                                          _tip_event(view.viewport(), pos))
    finally:
        view.close()


def test_delayed_tip_from_previous_button_is_ignored(qapp):
    from widgets import _InfoTipPopup
    first = QPushButton("Первый")
    second = QPushButton("Второй")
    first.setToolTip("Старая подсказка")
    second.setToolTip("Правильная подсказка")
    first.move(100, 100)
    second.move(250, 100)
    first.show()
    second.show()
    try:
        QCursor.setPos(second.mapToGlobal(second.rect().center()))
        qapp.processEvents()
        pos = first.rect().center()
        assert _manager().eventFilter(first, _tip_event(first, pos))
        qapp.processEvents()
        assert _InfoTipPopup.instance().text() != "Старая подсказка"
    finally:
        _InfoTipPopup.instance().hide()
        first.close()
        second.close()


def test_delayed_item_tip_uses_the_row_under_cursor(qapp):
    from widgets import _InfoTipPopup
    view = QListWidget()
    for name in ("FIRST", "SECOND"):
        item = QListWidgetItem(name)
        item.setToolTip(name)
        view.addItem(item)
    view.resize(250, 120)
    view.show()
    qapp.processEvents()
    try:
        old_pos = view.visualItemRect(view.item(0)).center()
        current_pos = view.visualItemRect(view.item(1)).center()
        QCursor.setPos(view.viewport().mapToGlobal(current_pos))
        qapp.processEvents()
        assert _manager().eventFilter(
            view.viewport(), _tip_event(view.viewport(), old_pos))
        qapp.processEvents()
        assert _InfoTipPopup.instance().text() == "SECOND"
        assert not QToolTip.isVisible()
    finally:
        _InfoTipPopup.instance().hide()
        view.close()


def test_delayed_parent_tip_keeps_child_button_tip(qapp):
    from widgets import _InfoTipPopup
    panel = QWidget()
    panel.setToolTip("PARENT")
    panel.resize(200, 100)
    button = QPushButton("CHILD", panel)
    button.setToolTip("CHILD")
    button.move(50, 20)
    panel.show()
    qapp.processEvents()
    try:
        QCursor.setPos(button.mapToGlobal(button.rect().center()))
        qapp.processEvents()
        manager = _manager()
        assert manager.eventFilter(button, _tip_event(button, button.rect().center()))
        assert manager.eventFilter(panel, _tip_event(panel, QPoint(5, 5)))
        qapp.processEvents()
        assert _InfoTipPopup.instance().text() == "CHILD"
        assert not QToolTip.isVisible()
    finally:
        _InfoTipPopup.instance().hide()
        panel.close()


def test_item_tip_takes_priority_over_container_tip(qapp):
    from widgets import _InfoTipPopup

    panel = QWidget()
    panel.setToolTip("PARENT")
    view = QListWidget(panel)
    view.resize(240, 100)
    item = QListWidgetItem("Row")
    item.setToolTip("ROW")
    view.addItem(item)
    panel.resize(260, 130)
    panel.show()
    qapp.processEvents()
    try:
        pos = view.visualItemRect(item).center()
        QCursor.setPos(view.viewport().mapToGlobal(pos))
        qapp.processEvents()
        assert _manager().eventFilter(
            view.viewport(), _tip_event(view.viewport(), pos))
        qapp.processEvents()
        assert _InfoTipPopup.instance().text() == "ROW"
    finally:
        _InfoTipPopup.instance().hide()
        panel.close()


def test_custom_popup_survives_mousemove_without_managed_tip(qapp):
    from widgets import _InfoTipPopup, HoverTipManager

    manager = HoverTipManager(qapp)
    qapp.installEventFilter(manager)
    widget = QWidget()
    widget.resize(200, 80)
    widget.show()
    qapp.processEvents()
    popup = _InfoTipPopup.instance()
    try:
        point = widget.mapToGlobal(widget.rect().center())
        QCursor.setPos(point)
        qapp.processEvents()
        popup.show_at(point, "CUSTOM")
        QTest.mouseMove(widget, widget.rect().center())
        qapp.processEvents()
        assert popup.isVisible() and popup.text() == "CUSTOM"
    finally:
        popup.hide()
        widget.close()
        qapp.removeEventFilter(manager)


def test_hovering_adjacent_buttons_and_badges_shows_only_current_tip(qapp):
    from widgets import _InfoTipPopup, HoverTipManager, info_badge

    manager = HoverTipManager(qapp)
    qapp.installEventFilter(manager)
    panel = QWidget()
    row = QHBoxLayout(panel)
    badges = [info_badge("Значок 1"), info_badge("Значок 2")]
    buttons = [QPushButton("Кнопка 1"), QPushButton("Кнопка 2")]
    for button in buttons:
        button.setToolTip(button.text())
    for widget in badges + buttons:
        row.addWidget(widget)
    panel.resize(600, 70)
    panel.show()
    qapp.processEvents()
    popup = _InfoTipPopup.instance()
    try:
        for widget, expected in zip(badges + buttons,
                                    ("Значок 1", "Значок 2",
                                     "Кнопка 1", "Кнопка 2")):
            QTest.mouseMove(widget, widget.rect().center())
            QTest.qWait(800)
            assert popup.isVisible() and popup.text() == expected
            assert not QToolTip.isVisible()

        QTest.mouseMove(badges[1], badges[1].rect().center())
        qapp.processEvents()
        assert popup.isVisible() and popup.text() == "Значок 2"
        stale = badges[0]
        pos = stale.rect().center()
        stale_enter = QEnterEvent(QPointF(pos), QPointF(pos),
                                  QPointF(stale.mapToGlobal(pos)))
        qapp.sendEvent(stale, stale_enter)
        qapp.sendEvent(stale, QEvent(QEvent.Type.Leave))
        QTest.qWait(60)
        assert popup.isVisible() and popup.text() == "Значок 2"

        QTest.mouseMove(buttons[1], buttons[1].rect().center())
        QTest.qWait(800)
        old = buttons[0]
        qapp.sendEvent(old, _tip_event(old, old.rect().center()))
        qapp.sendEvent(old, QEvent(QEvent.Type.Leave))
        qapp.processEvents()
        assert popup.isVisible() and popup.text() == "Кнопка 2"
        assert not QToolTip.isVisible()
    finally:
        popup.hide()
        panel.close()
        qapp.removeEventFilter(manager)


def test_late_button_tip_never_shows_after_entering_neighbor(qapp, monkeypatch):
    """Qt can deliver Enter B before updating QCursor and then deliver Tip A."""
    from widgets import _InfoTipPopup, HoverTipManager

    manager = HoverTipManager(qapp)
    qapp.installEventFilter(manager)
    panel = QWidget()
    row = QHBoxLayout(panel)
    first = QPushButton("A")
    second = QPushButton("B")
    first.setToolTip("ALPHA")
    second.setToolTip("BETA")
    row.addWidget(first)
    row.addWidget(second)
    panel.resize(360, 80)
    panel.show()
    qapp.processEvents()
    popup = _InfoTipPopup.instance()
    try:
        QCursor.setPos(first.mapToGlobal(first.rect().center()))
        qapp.processEvents()
        popup.hide()
        show_calls = []
        original_show = _InfoTipPopup.show_for

        def trace_show(self, widget, text):
            show_calls.append(text)
            return original_show(self, widget, text)

        monkeypatch.setattr(_InfoTipPopup, "show_for", trace_show)

        center = second.rect().center()
        qapp.sendEvent(second, QEnterEvent(
            QPointF(center), QPointF(center),
            QPointF(second.mapToGlobal(center))))
        assert not popup.isVisible()

        qapp.sendEvent(first, _tip_event(first, first.rect().center()))
        assert not popup.isVisible(), "Late Tip A flashed after Enter B"
        assert "ALPHA" not in show_calls

        QCursor.setPos(second.mapToGlobal(center))
        assert not popup.isVisible(), "Old tip remained visible over B"
        qapp.sendEvent(first, _tip_event(first, first.rect().center()))
        assert not popup.isVisible(), "Late Tip A appeared over B"
        qapp.sendEvent(second, _tip_event(second, center))
        qapp.processEvents()
        assert popup.isVisible() and popup.text() == "BETA"
        assert "ALPHA" not in show_calls
        assert not QToolTip.isVisible()
    finally:
        popup.hide()
        panel.close()
        qapp.removeEventFilter(manager)


def test_visible_button_tip_closes_before_late_event(qapp, monkeypatch):
    """The prior button's text must disappear as soon as Enter reaches B."""
    from widgets import _InfoTipPopup, HoverTipManager

    manager = HoverTipManager(qapp)
    qapp.installEventFilter(manager)
    panel = QWidget()
    row = QHBoxLayout(panel)
    first, second = QPushButton("A"), QPushButton("B")
    first.setToolTip("ALPHA")
    second.setToolTip("BETA")
    row.addWidget(first)
    row.addWidget(second)
    panel.resize(360, 80)
    panel.show()
    qapp.processEvents()
    popup = _InfoTipPopup.instance()
    try:
        QCursor.setPos(first.mapToGlobal(first.rect().center()))
        qapp.processEvents()
        popup.show_for(first, "ALPHA")
        shown = []
        original = _InfoTipPopup.show_for

        def trace_show(self, widget, text):
            shown.append(text)
            return original(self, widget, text)

        monkeypatch.setattr(_InfoTipPopup, "show_for", trace_show)
        center = second.rect().center()
        qapp.sendEvent(second, QEnterEvent(
            QPointF(center), QPointF(center),
            QPointF(second.mapToGlobal(center))))
        assert not popup.isVisible()
        qapp.sendEvent(first, _tip_event(first, first.rect().center()))
        qapp.processEvents()
        assert not popup.isVisible()
        assert "ALPHA" not in shown

        QCursor.setPos(second.mapToGlobal(center))
        qapp.sendEvent(second, _tip_event(second, center))
        QTest.qWait(50)
        assert popup.isVisible() and popup.text() == "BETA"
        assert "ALPHA" not in shown
        assert not QToolTip.isVisible()
    finally:
        popup.hide()
        panel.close()
        qapp.removeEventFilter(manager)
