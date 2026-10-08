"""A queued pointer event may reach the custom hint before QCursor updates."""
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QCursor, QMouseEvent, QEnterEvent
from PyQt6.QtTest import QTest
import pytest

from widgets import _InfoTipPopup
from test_custom_tooltip_regions import source, hover  # noqa: F401 - reuse parametrized fixture


@pytest.mark.parametrize("source", ["row"], indirect=True)
def test_row_hint_follows_pointer_after_delayed_cursor_update(qapp, source):
    owner, first, second, _, _, kind = source
    assert kind == "row"
    hover(qapp, owner, first)
    popup = _InfoTipPopup.instance()
    assert popup.isVisible() and popup.text() == "ALPHA"
    popup.hide()  # The global application filter hides the previous cell first.
    global_pos = owner.mapToGlobal(second)
    qapp.sendEvent(owner, QMouseEvent(QEvent.Type.MouseMove, QPointF(second),
        QPointF(global_pos), Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier))
    QCursor.setPos(global_pos)
    QTest.qWait(60)
    assert popup.isVisible() and popup.text() == "BETA"


@pytest.mark.parametrize("source", ["row"], indirect=True)
def test_reentering_viewport_refreshes_row_without_mouse_move(qapp, source):
    owner, first, second, _, _, _ = source
    hover(qapp, owner, first)
    popup = _InfoTipPopup.instance()
    assert popup.text() == "ALPHA"
    QCursor.setPos(owner.mapToGlobal(second))
    popup.hide()
    qapp.sendEvent(owner, QEnterEvent(QPointF(second), QPointF(second),
                                    QPointF(owner.mapToGlobal(second))))
    QTest.qWait(60)
    assert popup.isVisible() and popup.text() == "BETA"


def test_late_enter_from_previous_cell_keeps_current_custom_hint(qapp, source):
    owner, first, second, _, _, _ = source
    hover(qapp, owner, second)
    popup = _InfoTipPopup.instance()
    assert popup.isVisible() and popup.text() == "BETA"
    qapp.sendEvent(owner, QEnterEvent(QPointF(first), QPointF(first),
                                    QPointF(owner.mapToGlobal(first))))
    assert popup.isVisible() and popup.text() == "BETA"
    QTest.qWait(60)
    assert popup.isVisible() and popup.text() == "BETA"
