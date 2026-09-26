# -*- coding: utf-8 -*-
"""Настройки: клик по разделу слева ставит раздел к ВЕРХУ области.

Раньше ensureWidgetVisible прокручивал минимально, и при переходе вниз
заголовок «Ключи API» вставал у нижнего края — на экране оставался
предыдущий раздел.
"""
from unittest import mock

from PyQt6.QtCore import QPoint

import main


class _Window(main.QWidget):
    """Главное окно-заглушка: чего нет — отдаётся подставным объектом."""

    def get_api_key(self, name):
        return ""

    def __getattr__(self, name):
        value = mock.MagicMock(name=name)
        setattr(self, name, value)
        return value


def _open(monkeypatch, check, section=None):
    seen = {}

    class Dialog(main.QDialog):
        def exec(self):
            self.resize(760, 560)
            self.show()
            main.QApplication.processEvents()
            seen["ok"] = check(self)
            self.close()
            return 0

    monkeypatch.setattr(main, "QDialog", Dialog)
    window = _Window()
    for name, value in (("_wheel_changes_values", False), ("tab_edit", None),
                        ("_show_advanced_encode", False), ("_server_enabled", False)):
        setattr(window, name, value)
    main.UnifiedWindow._open_settings_dialog(window, section)
    return seen["ok"]


def _parts(dlg):
    nav = dlg.findChild(main.QListWidget)
    scroll = dlg.findChild(main.QScrollArea)
    return nav, scroll


def test_nav_click_puts_section_on_top(qapp, monkeypatch):
    def check(dlg):
        nav, scroll = _parts(dlg)
        row = [nav.item(i).text() for i in range(nav.count())].index("Ключи API")
        nav.setCurrentRow(row)
        header = [w for w in scroll.widget().findChildren(main.QLabel)
                  if w.text() == "Ключи API"][0]
        top = header.mapTo(scroll.widget(), QPoint(0, 0)).y()
        value = scroll.verticalScrollBar().value()
        return abs(top - value) <= 8 and nav.currentRow() == row
    assert _open(monkeypatch, check)


def test_open_straight_to_api_keys(qapp, monkeypatch):
    def check(dlg):
        nav, scroll = _parts(dlg)
        return (nav.currentItem().text() == "Ключи API"
                and scroll.verticalScrollBar().value() > 0)
    assert _open(monkeypatch, check, "Ключи API")
