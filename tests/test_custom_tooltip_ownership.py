# -*- coding: utf-8 -*-
"""Delayed custom table hints must not overwrite a button under the cursor."""
import pytest

from PyQt6.QtCore import QEvent, QPoint, Qt
from PyQt6.QtGui import QCursor, QHelpEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem,
    QTreeWidgetItem, QWidget,
)


def _source(window, kind):
    from widgets import DraggableTreeWidget
    from si_hyx_parts.animepack_tab import index_tooltip
    from si_hyx_parts.animepack_tab.db_row_tip import RowTipWatcher

    if kind == "tree":
        table = DraggableTreeWidget()
        item = QTreeWidgetItem(["OLD TABLE TEXT"])
        table.addTopLevelItem(item)
        # The compare badge has its own tooltip, independent of ToolTipRole.
        table._badge_iid_at = lambda pos: (
            1 if table.visualItemRect(item).contains(pos) else None)
        return table, table.viewport(), item, None

    table = QTableWidget(1, 1)
    table.setHorizontalHeaderLabels(["Index"])
    item = QTableWidgetItem("row")
    table.setItem(0, 0, item)
    if kind == "index":
        item.setData(index_tooltip.TIP_ROLE, "OLD TABLE TEXT")
        index_tooltip.install(table)
    elif kind == "header":
        index_tooltip.install_headers(table, {"Index": "OLD TABLE TEXT"})
        return table, table.horizontalHeader(), item, None
    elif kind == "row":
        window.table = table
        window.tip_key_at = lambda pos: (
            0 if table.visualItemRect(item).contains(pos) else None)
        window.explain_at = lambda pos: "OLD TABLE TEXT"
        window.watcher = RowTipWatcher(window)
        table.viewport().installEventFilter(window.watcher)
    elif kind == "delegate":
        import shikimori_tab
        window._index_tooltip_for = lambda aid: "OLD TABLE TEXT"
        delegate = shikimori_tab._ViewsBadgeDelegate(window)
        item.setData(Qt.ItemDataRole.UserRole + 1, 1)
        return table, table.viewport(), item, delegate
    return table, table.viewport(), item, None


@pytest.mark.parametrize("kind", ["index", "header", "row", "tree", "delegate"])
@pytest.mark.parametrize("has_text", [True, False])
def test_stale_custom_tip_cannot_change_current_button(qapp, kind, has_text):
    from widgets import _InfoTipPopup, install_hover_tips

    if not hasattr(qapp, "_hover_tip_mgr"):
        install_hover_tips(qapp)
    window = QWidget()
    layout = QHBoxLayout(window)
    table, source, item, delegate = _source(window, kind)
    button = QPushButton("Current button")
    button.setToolTip("CURRENT BUTTON TEXT")
    layout.addWidget(table)
    layout.addWidget(button)
    window.resize(560, 230)
    window.show()
    qapp.processEvents()
    popup = _InfoTipPopup.instance()
    try:
        if kind == "header":
            old_pos = QPoint(15, source.height() // 2)
        else:
            old_pos = table.visualItemRect(item).center()
        if delegate is not None:
            delegate._index_rects[1] = table.visualItemRect(item)
        # Populate provider state just as a real prior hover would.
        QCursor.setPos(source.mapToGlobal(old_pos))
        qapp.processEvents()
        initial = QHelpEvent(QEvent.Type.ToolTip, old_pos,
                             source.mapToGlobal(old_pos))
        if delegate is None:
            qapp.sendEvent(source, initial)
        else:
            delegate.helpEvent(initial, table, None, table.model().index(0, 0))
        assert popup.isVisible()
        assert popup.text() == ("Сравнить исходник и результат"
                                if kind == "tree" else "OLD TABLE TEXT")

        QCursor.setPos(button.mapToGlobal(button.rect().center()))
        QTest.qWait(60)
        assert QApplication.widgetAt(QCursor.pos()) is button
        assert popup.isVisible() and popup.text() == "CURRENT BUTTON TEXT"
        if not has_text:
            old_pos = QPoint(source.width() - 3, source.height() - 3)
        event = QHelpEvent(QEvent.Type.ToolTip, old_pos,
                           source.mapToGlobal(old_pos))
        if delegate is None:
            qapp.sendEvent(source, event)
        else:
            delegate.helpEvent(event, table, None, table.model().index(0, 0))
        # Check immediately: the wrong text must never flash before a timer
        # restores the current hint on a later event-loop turn.
        assert popup.isVisible() and popup.text() == "CURRENT BUTTON TEXT"
        qapp.processEvents()
        assert popup.isVisible() and popup.text() == "CURRENT BUTTON TEXT"
    finally:
        popup.hide()
        window.close()
        window.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()


def test_late_row_event_preserves_cache_and_next_row_hint(qapp):
    from widgets import _InfoTipPopup, install_hover_tips
    from si_hyx_parts.animepack_tab.db_row_tip import RowTipWatcher

    if not hasattr(qapp, "_hover_tip_mgr"):
        install_hover_tips(qapp)
    page = QWidget()
    layout = QHBoxLayout(page)
    page.table = table = QTableWidget(3, 1)
    for row, text in enumerate(("FIRST", "SECOND", "THIRD")):
        table.setItem(row, 0, QTableWidgetItem(text))
    page.tip_key_at = lambda pos: (
        table.rowAt(pos.y()) if table.itemAt(pos) is not None else None)
    page.explain_at = lambda pos: table.itemAt(pos).text()
    watcher = RowTipWatcher(page)
    table.viewport().installEventFilter(watcher)
    layout.addWidget(table)
    page.show()
    qapp.processEvents()
    popup = _InfoTipPopup.instance()
    source = table.viewport()

    def hover(row):
        pos = table.visualItemRect(table.item(row, 0)).center()
        QCursor.setPos(source.mapToGlobal(pos))
        qapp.processEvents()
        qapp.sendEvent(source, QHelpEvent(
            QEvent.Type.ToolTip, pos, source.mapToGlobal(pos)))
        return pos

    try:
        first_pos = hover(0)
        hover(1)
        assert popup.text() == "SECOND" and popup.isVisible()
        qapp.sendEvent(source, QHelpEvent(
            QEvent.Type.ToolTip, first_pos, source.mapToGlobal(first_pos)))
        assert watcher._key == 1
        assert popup.text() == "SECOND" and popup.isVisible()
        empty_pos = QPoint(source.width() - 3, source.height() - 3)
        qapp.sendEvent(source, QHelpEvent(
            QEvent.Type.ToolTip, empty_pos, source.mapToGlobal(empty_pos)))
        assert watcher._key == 1
        assert popup.text() == "SECOND" and popup.isVisible()
        hover(2)
        assert watcher._key == 2
        assert popup.text() == "THIRD" and popup.isVisible()
        hover(0)
        assert watcher._key == 0
        assert popup.text() == "FIRST" and popup.isVisible()
    finally:
        popup.hide()
        page.close()
        page.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()
