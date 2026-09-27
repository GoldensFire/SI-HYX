# -*- coding: utf-8 -*-
"""Правая полоса прокрутки использует край вкладки и доступна в низком окне."""
import pytest

from animepack_tab import AnimePackTab
from config import STYLESHEET


@pytest.mark.parametrize("width,height", [(1200, 420), (1600, 760)])
def test_pack_scrollbar_reaches_the_right_edge(qapp, width, height):
    tab = AnimePackTab()
    try:
        tab.setStyleSheet(STYLESHEET + tab.styleSheet())
        tab.resize(width, height)
        tab.show()
        for _ in range(3):
            qapp.processEvents()
        scroll = tab.scroll_pack
        assert scroll.geometry().right() == tab.rect().right()
        bar = scroll.verticalScrollBar()
        if bar.isVisible():
            edge = bar.mapTo(tab, bar.rect().topRight()).x()
            assert tab.rect().right() - edge <= 1
        assert scroll.horizontalScrollBar().maximum() == 0
    finally:
        tab.cleanup()
        tab.close()
