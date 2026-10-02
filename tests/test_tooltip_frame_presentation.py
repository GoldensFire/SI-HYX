# -*- coding: utf-8 -*-
"""Check the first presented frame, not just QLabel.text after settling."""
import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QCursor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QPushButton

from widgets import _InfoTipPopup


class PaintedTip(_InfoTipPopup):
    def __init__(self):
        self.painted = []
        self.presented = []
        super().__init__()

    def paintEvent(self, event):
        super().paintEvent(event)
        self.painted.append(self.text())

    def setWindowOpacity(self, opacity):
        if opacity > 0 and self.isVisible():
            self.presented.append((self.text(), self.painted[-1:]))
        super().setWindowOpacity(opacity)


@pytest.fixture
def popup(qapp):
    tip = PaintedTip()
    yield tip
    tip.close()
    tip.deleteLater()
    qapp.processEvents()


def settle(popup, expected):
    QTest.qWait(80)
    assert popup.isVisible()
    assert popup.windowOpacity() == 1
    assert popup.painted[-1] == expected


@pytest.mark.parametrize("hide_first", [True, False])
def test_reused_window_is_invisible_until_new_text_is_painted(popup, hide_first):
    popup.show_at(QPoint(80, 80), "DOWNLOADER: Download video and audio")
    settle(popup, "DOWNLOADER: Download video and audio")
    if hide_first:
        popup.hide()
    popup.show_at(QPoint(250, 80), "PROCESSING: Process video and audio")
    # On Windows show/raise/move can expose the old native backing store
    # before Qt delivers Paint. Reading popup.text() misses this interval.
    assert popup.windowOpacity() == 0
    settle(popup, "PROCESSING: Process video and audio")
    assert popup.presented
    assert all(text == painted[0] for text, painted in popup.presented)


def test_fast_changes_never_present_an_unpainted_intermediate_tip(popup):
    popup.show_at(QPoint(80, 80), "FIRST")
    settle(popup, "FIRST")
    popup.hide()
    popup.show_at(QPoint(150, 80), "SECOND")
    popup.show_at(QPoint(250, 80), "THIRD")
    assert popup.windowOpacity() == 0
    settle(popup, "THIRD")
    assert [text for text, _ in popup.presented] == ["FIRST", "THIRD"]


def test_hiding_before_queued_reveal_does_not_restore_opacity(popup, qapp):
    popup.show_at(QPoint(80, 80), "FIRST")
    # An actual Qt PaintEvent queues the reveal; hide before the timer runs.
    qapp.processEvents()
    assert popup.painted == ["FIRST"]
    popup.hide()
    QTest.qWait(80)
    assert not popup.isVisible()
    assert popup.windowOpacity() == 0
    assert popup.presented == []


def test_reveal_rechecks_the_hover_target(popup, qapp):
    button = QPushButton("A")
    button.setToolTip("ALPHA")
    button.move(100, 150)
    button.show()
    qapp.processEvents()
    try:
        QCursor.setPos(button.mapToGlobal(button.rect().center()))
        qapp.processEvents()
        popup.show_for(button, "ALPHA")
        QCursor.setPos(button.mapToGlobal(QPoint(-20, -20)))
        QTest.qWait(80)
        assert not popup.isVisible()
        assert popup.presented == []
    finally:
        button.close()


def test_reveal_rechecks_dynamic_text_on_the_same_button(popup, qapp):
    button = QPushButton("A")
    button.setToolTip("OLD")
    button.move(100, 150)
    button.show()
    qapp.processEvents()
    try:
        QCursor.setPos(button.mapToGlobal(button.rect().center()))
        qapp.processEvents()
        popup.show_for(button, "OLD")
        button.setToolTip("CURRENT")
        QTest.qWait(80)
        assert not popup.isVisible()
        assert popup.presented == []
    finally:
        button.close()
