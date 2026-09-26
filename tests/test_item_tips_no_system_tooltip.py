# -*- coding: utf-8 -*-
"""Подсказки ячеек списков и таблиц идут через _InfoTipPopup, а не QToolTip.

item.setToolTip(...) Qt показывает системным синим окном — пользователь его
запретил, а в списке паков оно всё равно всплывало с путём к файлу."""
from PyQt6.QtCore import QEvent, QPoint
from PyQt6.QtGui import QHelpEvent
from PyQt6.QtWidgets import (QListWidget, QListWidgetItem, QStyledItemDelegate,
                             QTableWidget)


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
        assert _manager().eventFilter(view.viewport(), _tip_event(view.viewport(), pos))
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
        assert _manager().eventFilter(head.viewport(), _tip_event(head.viewport(), pos)) \
            or _manager().eventFilter(head, _tip_event(head, pos))
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
