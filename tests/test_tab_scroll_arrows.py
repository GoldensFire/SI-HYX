# -*- coding: utf-8 -*-
"""Стрелки прокрутки вкладок «как в браузере» (widgets.TabScrollArrows).

Родной QTabBar держит обе стрелки у правого края и просто гасит ненужную.
Нужно иначе: левая — у ЛЕВОГО края и только пока слева есть уехавшие вкладки,
правая — у правого и только пока справа что-то не влезло.
"""
import pytest
from PyQt6.QtWidgets import QTabWidget, QWidget


@pytest.fixture
def bar(qapp):
    from widgets import install_tab_scroll_arrows
    tw = QTabWidget()
    tw.resize(200, 60)
    for i in range(12):
        tw.addTab(QWidget(), f"Вкладка {i}")
    tw.tabBar().setUsesScrollButtons(True)
    tw.show()
    qapp.processEvents()
    arrows = install_tab_scroll_arrows(tw.tabBar())
    qapp.processEvents()
    yield tw, arrows, qapp
    tw.close()
    tw.deleteLater()
    qapp.processEvents()


def _x(btn):
    return btn.x()


def test_left_arrow_hides_while_nothing_ran_off_to_the_left(bar):
    tw, arrows, app = bar
    left, right = arrows.buttons()
    assert not left.isEnabled() and _x(left) < 0        # уведена за край
    assert right.isEnabled() and _x(right) > 0          # правая на месте


def test_left_arrow_comes_to_the_left_edge_after_scrolling(bar):
    tw, arrows, app = bar
    tw.setCurrentIndex(6)
    app.processEvents()
    left, right = arrows.buttons()
    assert left.isEnabled() and _x(left) == 0
    assert right.isEnabled() and _x(right) > 0


def test_right_arrow_hides_at_the_very_end(bar):
    tw, arrows, app = bar
    tw.setCurrentIndex(11)
    app.processEvents()
    left, right = arrows.buttons()
    assert left.isEnabled() and _x(left) == 0
    assert not right.isEnabled() and _x(right) < 0


def test_both_arrows_hide_when_everything_fits(bar):
    tw, arrows, app = bar
    tw.resize(2000, 60)
    app.processEvents()
    left, right = arrows.buttons()
    assert _x(left) < 0 and _x(right) < 0
