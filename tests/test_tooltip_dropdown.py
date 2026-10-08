# -*- coding: utf-8 -*-
"""Open choices must remain visible even when delayed hover events arrive."""
import pytest
from PyQt6.QtCore import QEvent, QPoint, Qt
from PyQt6.QtGui import QCursor, QHelpEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QComboBox

from widgets import _InfoTipPopup, install_hover_tips


@pytest.fixture
def combo(qapp):
    if not hasattr(qapp, "_hover_tip_mgr"):
        install_hover_tips(qapp)
    widget = QComboBox()
    widget.addItems(["Low", "Medium", "High"])
    widget.setToolTip("Explanation that must not obscure the options")
    widget.resize(240, 35)
    widget.move(100, 100)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.hidePopup()
    _InfoTipPopup.instance().hide()
    widget.close()
    widget.deleteLater()
    qapp.processEvents()


def hover(widget, qapp):
    point = widget.mapToGlobal(widget.rect().center())
    QCursor.setPos(point)
    qapp.processEvents()
    event = QHelpEvent(QEvent.Type.ToolTip, widget.rect().center(), point)
    qapp.sendEvent(widget, event)
    QTest.qWait(80)


@pytest.mark.parametrize("editable", [True, False])
@pytest.mark.parametrize("opening", ["mouse", "keyboard", "programmatic"])
def test_dropdown_hides_tip_and_rejects_delayed_help(combo, qapp, editable, opening):
    combo.setEditable(editable)
    hover(combo, qapp)
    popup = _InfoTipPopup.instance()
    assert popup.isVisible()
    if opening == "mouse":
        QTest.mouseClick(combo, Qt.MouseButton.LeftButton,
                         pos=QPoint(combo.width() - 8, combo.height() // 2))
    elif opening == "keyboard":
        combo.setFocus()
        QTest.keyClick(combo, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
    else:
        combo.showPopup()
    qapp.processEvents()
    assert QApplication.activePopupWidget() is not None
    assert not popup.isVisible()
    # Moving within the choices must not redisplay the combo's inherited tip.
    viewport = combo.view().viewport()
    point = viewport.mapToGlobal(viewport.rect().center())
    QCursor.setPos(point)
    hover(viewport, qapp)
    qapp.sendEvent(combo, QHelpEvent(QEvent.Type.ToolTip,
                                    combo.rect().center(), point))
    popup.show_for(combo, combo.toolTip())
    popup.show_at(point, "Delayed custom hint")
    QTest.qWait(80)
    assert not popup.isVisible()
    combo.hidePopup()
    hover(combo, qapp)
    assert popup.isVisible() and popup.text() == combo.toolTip()


def test_opening_dropdown_hides_a_just_shown_tip(combo, qapp):
    popup = _InfoTipPopup.instance()
    QCursor.setPos(combo.mapToGlobal(combo.rect().center()))
    popup.show_for(combo, combo.toolTip())
    assert popup.isVisible()
    combo.showPopup()
    QTest.qWait(80)
    assert not popup.isVisible()
