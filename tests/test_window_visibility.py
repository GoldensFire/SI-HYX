# -*- coding: utf-8 -*-
"""A restored window must never keep Windows' minimized coordinates."""
import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QWidget

from si_hyx_parts.main import window_visibility as visibility


@pytest.fixture
def guarded(qapp, monkeypatch):
    monkeypatch.setattr(visibility, "native_minimized", lambda _window: False)
    window = QWidget()
    window.setGeometry(100, 100, 400, 300)
    guard = visibility.WindowVisibilityGuard(window)
    window.show()
    qapp.processEvents()
    yield window, guard
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_restore_recovers_last_visible_position(guarded, qapp):
    window, guard = guarded
    previous = QRect(window.geometry())
    window.setGeometry(-25593, -25570, 720, 480)
    qapp.processEvents()
    assert window.geometry() == previous
    assert guard.last_visible == previous


def test_minimizing_does_not_reopen_window(guarded, qapp):
    window, guard = guarded
    previous = QRect(guard.last_visible)
    window.showMinimized()
    window.setGeometry(-25593, -25570, 720, 480)
    qapp.processEvents()
    assert window.isMinimized()
    assert guard.last_visible == previous
    assert guard.recover() is False
    window.showNormal()
    qapp.processEvents()
    assert window.geometry() == previous


def test_native_minimize_does_not_poison_remembered_position(
        guarded, qapp, monkeypatch):
    window, guard = guarded
    previous = QRect(guard.last_visible)
    monkeypatch.setattr(visibility, "native_minimized", lambda _window: True)
    window.setGeometry(-25593, -25570, 720, 480)
    qapp.processEvents()
    assert guard.last_visible == previous
    assert window.geometry().x() < -25000
    monkeypatch.setattr(visibility, "native_minimized", lambda _window: False)
    guard.schedule()
    qapp.processEvents()
    assert window.geometry() == previous


def test_negative_coordinates_on_another_monitor_are_valid(guarded, qapp):
    window, guard = guarded
    guard.areas = lambda: [QRect(0, 0, 1600, 1000), QRect(-1600, 0, 1600, 1000)]
    window.setGeometry(-1400, 100, 600, 400)
    qapp.processEvents()
    assert window.geometry().x() < -1000
    assert guard.last_visible == window.geometry()


def test_disconnected_monitor_recovers_on_remaining_screen(guarded, qapp):
    window, guard = guarded
    guard.areas = lambda: [QRect(-1600, 0, 1600, 1000)]
    window.setGeometry(-1400, 100, 600, 400)
    qapp.processEvents()
    guard.areas = lambda: [QRect(0, 0, 1600, 1000)]
    guard.schedule()
    qapp.processEvents()
    assert visibility.titlebar_visible(window.geometry(), guard.areas())
