# -*- coding: utf-8 -*-
"""Tab badges must never briefly display another tab's delayed hint."""
from types import MethodType, SimpleNamespace

from PyQt6.QtCore import QEvent, QPointF
from PyQt6.QtGui import QCursor, QEnterEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QLabel, QTabBar, QTabWidget, QToolTip, QWidget


def test_badge_hint_uses_current_cursor_not_previous_tab_event(qapp):
    import main  # публичный модуль первым загружает свои части
    from widgets import _InfoTipPopup
    _update_tab_tip = main.UnifiedWindow._update_tab_tip

    tabs = QTabWidget()
    bar = tabs.tabBar()
    badges = []
    for key in ("ytdlp", "animepack_upgrade"):
        page = QWidget()
        page.setObjectName("tab::" + key)
        index = tabs.addTab(page, key)
        badge = QLabel("ⓘ")
        badge.setFixedSize(16, 16)
        bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, badge)
        badges.append(badge)
    tabs.resize(640, 120)
    tabs.show()
    qapp.processEvents()
    target = SimpleNamespace(
        tabs=tabs, _tab_tip_idx=-1,
        _tab_info={"ytdlp": ("", "", "Скачивание видео"),
                   "animepack_upgrade": ("", "", "Апгрейд пака")},
        _hide_tab_tip=lambda: _InfoTipPopup.instance().hide())
    try:
        QCursor.setPos(badges[1].mapToGlobal(badges[1].rect().center()))
        qapp.processEvents()
        _update_tab_tip(target, badges[0].geometry().center())
        assert _InfoTipPopup.instance().text() == "Апгрейд пака"
    finally:
        _InfoTipPopup.instance().hide()
        tabs.close()


def test_real_badge_hover_ignores_late_enter_and_leave(qapp):
    """Переход курсора и запоздавшие Qt-события не меняют соседний текст."""
    from widgets import _InfoTipPopup, info_badge, install_hover_tips

    if not hasattr(qapp, "_hover_tip_mgr"):
        install_hover_tips(qapp)
    tabs = QTabWidget()
    bar = tabs.tabBar()
    badges = []
    for i in range(2):
        index = tabs.addTab(QWidget(), f"Вкладка {i}")
        badge = info_badge(f"Подсказка {i}")
        badge.setProperty("tabTipManaged", True)
        bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, badge)
        badges.append(badge)
    tabs.resize(640, 120)
    tabs.show()
    qapp.processEvents()
    first, second = badges
    popup = _InfoTipPopup.instance()
    try:
        for badge, expected in ((first, "Подсказка 0"),
                                (second, "Подсказка 1")):
            QTest.mouseMove(badge, badge.rect().center())
            qapp.processEvents()
            target = SimpleNamespace(
                tabs=tabs, _tab_tip_idx=-1,
                _tab_info={"first": ("", "", "Подсказка 0"),
                           "second": ("", "", "Подсказка 1")},
                _hide_tab_tip=lambda: popup.hide())
            tabs.widget(0).setObjectName("tab::first")
            tabs.widget(1).setObjectName("tab::second")
            from main import UnifiedWindow
            _update_tab_tip = UnifiedWindow._update_tab_tip
            _update_tab_tip(target, bar.mapFromGlobal(QCursor.pos()))
            assert popup.isVisible() and popup.text() == expected
            assert not QToolTip.isVisible()

        center = first.rect().center()
        stale_enter = QEnterEvent(QPointF(center), QPointF(center),
                                  QPointF(first.mapToGlobal(center)))
        qapp.sendEvent(first, stale_enter)
        QTest.qWait(60)
        assert popup.isVisible() and popup.text() == "Подсказка 1"
        qapp.sendEvent(first, QEvent(QEvent.Type.Leave))
        qapp.processEvents()
        assert popup.isVisible() and popup.text() == "Подсказка 1"
        assert not QToolTip.isVisible()
    finally:
        popup.hide()
        tabs.close()


def test_scrolled_or_removed_badge_does_not_keep_old_tip(qapp):
    import main
    from widgets import _InfoTipPopup
    _hide_tab_tip = main.UnifiedWindow._hide_tab_tip
    _update_tab_tip = main.UnifiedWindow._update_tab_tip

    tabs = QTabWidget()
    tabs.resize(220, 120)
    bar = tabs.tabBar()
    tips = {}
    for number in range(12):
        key = f"tab{number}"
        page = QWidget()
        page.setObjectName(f"tab::{key}")
        index = tabs.addTab(page, f"Вкладка {number}")
        badge = QLabel("ⓘ")
        badge.setFixedSize(16, 16)
        bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, badge)
        tips[key] = ("", "", f"Подсказка {number}")
    target = SimpleNamespace(tabs=tabs, _tab_info=tips,
                             _tab_tip_idx=-1, _tab_tip_badge=None)
    target._hide_tab_tip = MethodType(_hide_tab_tip, target)
    tabs.show()
    qapp.processEvents()
    popup = _InfoTipPopup.instance()
    try:
        first = bar.tabButton(0, QTabBar.ButtonPosition.RightSide)
        QTest.mouseMove(first, first.rect().center())
        _update_tab_tip(target)
        assert popup.isVisible() and popup.text() == "Подсказка 0"
        tabs.setCurrentIndex(11)
        qapp.processEvents()
        _update_tab_tip(target)
        assert not popup.isVisible() or popup.text() != "Подсказка 0"

        tabs.setCurrentIndex(0)
        qapp.processEvents()
        QTest.mouseMove(first, first.rect().center())
        _update_tab_tip(target)
        assert popup.isVisible() and popup.text() == "Подсказка 0"
        tabs.removeTab(0)
        target._hide_tab_tip()
        assert not popup.isVisible()
    finally:
        popup.hide()
        tabs.close()


def test_managed_tab_badge_tip_tracks_scroll_and_removal(qapp):
    from widgets import _InfoTipPopup, info_badge, install_hover_tips

    if not hasattr(qapp, "_hover_tip_mgr"):
        install_hover_tips(qapp)
    tabs = QTabWidget()
    tabs.resize(220, 120)
    bar = tabs.tabBar()
    for number in range(12):
        index = tabs.addTab(QWidget(), f"Вкладка {number}")
        badge = info_badge(f"Подсказка {number}")
        badge.setProperty("tabTipManaged", True)
        bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, badge)
    tabs.show()
    qapp.processEvents()
    popup = _InfoTipPopup.instance()
    try:
        first = bar.tabButton(0, QTabBar.ButtonPosition.RightSide)
        QTest.mouseMove(first, first.rect().center())
        QTest.qWait(50)
        assert popup.isVisible() and popup.text() == "Подсказка 0"

        tabs.setCurrentIndex(11)
        QTest.qWait(50)
        assert not popup.isVisible() or popup.text() != "Подсказка 0"

        tabs.setCurrentIndex(0)
        QTest.mouseMove(first, first.rect().center())
        QTest.qWait(50)
        assert popup.isVisible() and popup.text() == "Подсказка 0"
        tabs.removeTab(0)
        QTest.qWait(50)
        assert not popup.isVisible() or popup.text() != "Подсказка 0"
        assert not QToolTip.isVisible()
    finally:
        popup.hide()
        tabs.close()
