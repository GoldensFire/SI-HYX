# -*- coding: utf-8 -*-
"""Custom hints must follow cells, including moves across a two-pixel border."""
import pytest

from PyQt6.QtCore import QEvent, QPoint, Qt
from PyQt6.QtGui import QCursor, QHelpEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (QHBoxLayout, QTableWidget, QTableWidgetItem,
                             QTreeWidgetItem, QWidget)

from widgets import HoverTipManager, _InfoTipPopup
from si_hyx_parts.animepack_tab import index_tooltip
from si_hyx_parts.animepack_tab.db_row_tip import RowTipWatcher


@pytest.fixture(params=["index", "row", "header"])
def source(qapp, request):
    manager = HoverTipManager(qapp)
    qapp.installEventFilter(manager)
    page = QWidget()
    page.table = table = QTableWidget(2, 2)
    table.setHorizontalHeaderLabels(["ALPHA", "BETA"])
    layout = QHBoxLayout(page)
    layout.addWidget(table)
    for row, text in enumerate(("ALPHA", "BETA")):
        for col in range(2):
            item = QTableWidgetItem(text)
            item.setData(index_tooltip.TIP_ROLE, text)
            table.setItem(row, col, item)
    if request.param == "index":
        index_tooltip.install(table)
    elif request.param == "header":
        index_tooltip.install_headers(table, {"ALPHA": "ALPHA", "BETA": "BETA"})
    else:
        page.tip_key_at = lambda pos: (
            (table.indexAt(pos).row(), table.indexAt(pos).column())
            if table.indexAt(pos).isValid() else None)
        page.explain_at = lambda pos: table.itemAt(pos).text()
        page.watcher = RowTipWatcher(page)
        table.viewport().installEventFilter(page.watcher)
    table.setMouseTracking(True)
    table.viewport().setMouseTracking(True)
    page.resize(400, 200)
    page.show()
    qapp.processEvents()
    owner = table.horizontalHeader() if request.param == "header" else table.viewport()
    if request.param == "header":
        first = QPoint(50, owner.height() // 2)
        second = QPoint(150, first.y())
        boundary = owner.sectionViewportPosition(1)
        old = QPoint(boundary - 1, first.y())
        new = QPoint(boundary + 1, first.y())
    else:
        first_rect = table.visualItemRect(table.item(0, 0))
        second_rect = table.visualItemRect(table.item(1, 0))
        first, second = first_rect.center(), second_rect.center()
        old = QPoint(first.x(), first_rect.bottom())
        new = QPoint(first.x(), second_rect.top())
    yield owner, first, second, old, new, request.param
    _InfoTipPopup.instance().hide()
    qapp.removeEventFilter(manager)
    page.close()
    page.deleteLater()
    manager.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def help_at(qapp, owner, point):
    qapp.sendEvent(owner, QHelpEvent(
        QEvent.Type.ToolTip, point, owner.mapToGlobal(point)))


def hover(qapp, owner, point):
    QCursor.setPos(owner.mapToGlobal(point))
    QTest.qWait(30)
    help_at(qapp, owner, point)
    QTest.qWait(40)


def test_leaving_custom_cell_never_retains_its_text(qapp, source):
    owner, first, second, _, _, kind = source
    hover(qapp, owner, first)
    popup = _InfoTipPopup.instance()
    assert popup.isVisible() and popup.text() == "ALPHA"
    QTest.mouseMove(owner, second)
    QTest.qWait(50)
    assert not popup.isVisible() or popup.text() == "BETA"
    if kind == "row":
        # Row hints already follow movement immediately; a global hide must
        # not turn that into waiting for another delayed ToolTip event.
        assert popup.isVisible() and popup.text() == "BETA"


def test_late_help_event_two_pixels_away_cannot_restore_old_cell(qapp, source):
    owner, _, _, old, new, _ = source
    assert (old - new).manhattanLength() <= 2
    hover(qapp, owner, new)
    popup = _InfoTipPopup.instance()
    assert popup.isVisible() and popup.text() == "BETA"
    help_at(qapp, owner, old)
    assert popup.text() == "BETA" and popup.isVisible()
    QTest.qWait(50)
    assert popup.text() == "BETA" and popup.isVisible()


def test_motion_inside_same_custom_cell_keeps_its_window(qapp, source):
    owner, first, _, _, _, _ = source
    hover(qapp, owner, first)
    popup = _InfoTipPopup.instance()
    assert popup.isVisible()
    window = int(popup.winId())
    QTest.mouseMove(owner, first + QPoint(5, 0))
    QTest.qWait(50)
    assert popup.isVisible() and popup.text() == "ALPHA"
    # Same tip: no new native window, so nothing hides and reappears.
    assert int(popup.winId()) == window


@pytest.mark.parametrize("area", ["image", "filename", "compare"])
def test_tree_cell_path_cannot_override_its_filename_or_compare_hint(qapp, area):
    from widgets import (DraggableTreeWidget, PreviewNameDelegate,
                         ITEM_COMPARE_ROLE)

    manager = HoverTipManager(qapp)
    qapp.installEventFilter(manager)
    tree = DraggableTreeWidget()
    item = QTreeWidgetItem(["DISPLAY NAME"])
    item.setToolTip(0, "FULL FILE PATH")
    item.setData(0, ITEM_COMPARE_ROLE, True)
    item.setData(0, Qt.ItemDataRole.UserRole, 1)
    tree.addTopLevelItem(item)
    delegate = PreviewNameDelegate(tree)
    tree.setItemDelegateForColumn(0, delegate)
    tree.resize(350, 240)
    tree.show()
    qapp.processEvents()
    popup = _InfoTipPopup.instance()
    try:
        rect = tree.visualItemRect(item)
        points = {
            "image": rect.topLeft() + QPoint(10, 10),
            "filename": QPoint(rect.center().x(), rect.bottom() - 4),
            "compare": delegate._badge_rect(rect, tree.fontMetrics()).center(),
        }
        expected = {"image": "FULL FILE PATH", "filename": "DISPLAY NAME",
                    "compare": "Сравнить исходник и результат"}[area]
        point = points[area]
        # ToolTipRole is populated, as it is for real media rows. It must not
        # let the application filter consume this custom viewport's event.
        assert manager._item_tip(tree.viewport(), point) == ""
        hover(qapp, tree.viewport(), point)
        assert popup.isVisible()
        assert popup.text() == expected
        assert not popup._hover_managed
    finally:
        popup.hide()
        qapp.removeEventFilter(manager)
        tree.close()
        tree.deleteLater()
        manager.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()
