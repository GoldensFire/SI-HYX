# -*- coding: utf-8 -*-
"""One native tooltip window never paints two different texts.

Windows keeps the last image of a hidden window and shows it on the next
show() a frame BEFORE the new paint reaches the screen: the reused tooltip
window flashed the previous tip (seen frame by frame on a real screen). Every
new tip therefore gets a fresh native window. These tests record which text
each native window has painted — a window painting a second text is exactly
what reached the screen as "the wrong tip for a split second"."""
from collections import defaultdict

import pytest
from PyQt6.QtCore import QEvent, QPoint
from PyQt6.QtGui import QCursor, QHelpEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (QHBoxLayout, QPushButton, QTabBar, QTabWidget,
                             QToolTip, QVBoxLayout, QWidget)

from widgets import _InfoTipPopup


class PaintedTip(_InfoTipPopup):
    def __init__(self):
        self.painted = []          # (native window, painted text, tip under cursor)
        self.under_cursor = None
        super().__init__()

    def paintEvent(self, event):
        super().paintEvent(event)
        current = self.under_cursor() if self.under_cursor else None
        self.painted.append((int(self.winId()), self.text(), current))

    def texts_per_window(self):
        windows = defaultdict(set)
        for window, text, _ in self.painted:
            windows[window].add(text)
        return windows


@pytest.fixture
def popup(qapp):
    tip = PaintedTip()
    yield tip
    tip.close()
    tip.deleteLater()
    qapp.processEvents()


def settle(popup, expected):
    QTest.qWait(80)
    assert popup.isVisible() and popup.text() == expected
    assert popup.painted and popup.painted[-1][1] == expected


def assert_one_text_per_window(popup):
    shared = {window: texts for window, texts in popup.texts_per_window().items()
              if len(texts) > 1}
    assert not shared, shared


@pytest.mark.parametrize("hide_first", [True, False])
def test_next_tip_never_reuses_the_previous_native_window(popup, hide_first):
    popup.show_at(QPoint(80, 80), "DOWNLOADER: Download video and audio")
    settle(popup, "DOWNLOADER: Download video and audio")
    first = popup.painted[-1][0]
    if hide_first:
        popup.hide()
    popup.show_at(QPoint(250, 80), "PROCESSING: Process video and audio")
    settle(popup, "PROCESSING: Process video and audio")
    assert popup.painted[-1][0] != first
    assert_one_text_per_window(popup)


def test_fast_changes_never_paint_two_texts_into_one_window(popup):
    popup.show_at(QPoint(80, 80), "FIRST")
    settle(popup, "FIRST")
    first = popup.painted[-1][0]
    popup.hide()
    popup.show_at(QPoint(150, 80), "SECOND")
    popup.show_at(QPoint(250, 80), "THIRD")
    settle(popup, "THIRD")
    assert popup.painted[-1][0] != first
    assert_one_text_per_window(popup)


def test_repeated_events_for_the_same_tip_keep_its_window(popup, qapp):
    button = QPushButton("A")
    button.setToolTip("ALPHA")
    button.move(100, 150)
    button.show()
    qapp.processEvents()
    try:
        QCursor.setPos(button.mapToGlobal(button.rect().center()))
        popup.show_for(button, "ALPHA")
        settle(popup, "ALPHA")
        window = int(popup.winId())
        # Rebuilt lists repeat ToolTip events with the same text: the tip must
        # stay put instead of hiding and reappearing in a new window.
        popup.show_for(button, "ALPHA")
        QTest.qWait(40)
        assert popup.isVisible() and int(popup.winId()) == window
    finally:
        button.close()


def test_every_painted_frame_belongs_to_the_widget_under_cursor(
        popup, qapp, monkeypatch):
    """Repeat the reported tab transition and ordinary buttons, frame by frame."""
    from widgets import HoverTipManager, info_badge

    monkeypatch.setattr(_InfoTipPopup, "_instance", popup)
    manager = HoverTipManager(qapp)
    qapp.installEventFilter(manager)
    popup.under_cursor = lambda: manager._tip_at(QCursor.pos())[1]
    window = QWidget()
    window.setWindowTitle("SI-HYX tooltip frame verification")
    layout = QVBoxLayout(window)
    tabs = QTabWidget()
    layout.addWidget(tabs)
    targets = []
    for title, text in (
            ("Обработка", "Обработка видео и аудио"),
            ("Загрузчик", "Скачивание видео/аудио с YouTube и других платформ")):
        index = tabs.addTab(QWidget(), title)
        badge = info_badge(text)
        tabs.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, badge)
        targets.append(badge)
    buttons = QHBoxLayout()
    layout.addLayout(buttons)
    for name in ("Открыть", "Сохранить", "Очистить"):
        button = QPushButton(name)
        button.setToolTip(name + " — подсказка кнопки")
        buttons.addWidget(button)
        targets.append(button)
    window.resize(600, 220)
    window.show()
    window.raise_()
    window.activateWindow()
    assert QTest.qWaitForWindowExposed(window)
    if qapp.platformName() == "windows":
        assert QTest.qWaitForWindowActive(window, 30000)
    qapp.processEvents()
    try:
        previous = targets[0]
        # Start from Downloader and move back to Processing, as in the report.
        for target in [targets[1], targets[0], *targets[2:]] * 4:
            QCursor.setPos(target.mapToGlobal(target.rect().center()))
            QTest.mouseMove(target, target.rect().center())
            old_pos = previous.rect().center()
            qapp.sendEvent(previous, QHelpEvent(
                QEvent.Type.ToolTip, old_pos, previous.mapToGlobal(old_pos)))
            QTest.qWait(80)
            expected = target.property("infoTipText") or target.toolTip()
            assert popup.isVisible() and popup.text() == expected, (
                expected, popup.text(), QCursor.pos(), manager._tip_at(QCursor.pos()))
            assert popup.painted[-1][1] == expected
            assert not QToolTip.isVisible()
            previous = target
        assert len(popup.texts_per_window()) >= 20
        assert_one_text_per_window(popup)
        assert all(text == current for _, text, current in popup.painted)
    finally:
        popup.hide()
        qapp.removeEventFilter(manager)
        window.close()
        window.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
