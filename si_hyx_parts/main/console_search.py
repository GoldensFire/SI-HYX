# -*- coding: utf-8 -*-
"""Поиск и копирование текста общей консоли."""
from __future__ import annotations

from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QApplication

from .console_find_bar import ConsoleFindBar


def install_search(widget) -> None:
    """Ctrl+F по консоли — панель поиска как в браузере (console_find_bar).

    Сама панель ловит Ctrl+F, пока фокус в консоли, — по виртуальной клавише,
    то есть и на русской раскладке. Ярлык окна оставлен, как был: Ctrl+F
    открывает поиск по консоли и когда фокус где-то ещё в том же окне."""
    bar = ConsoleFindBar(widget)
    widget._console_find_bar = bar
    shortcut = QShortcut(QKeySequence.StandardKey.Find, widget)
    shortcut.activated.connect(lambda: find_text(widget))
    widget._console_find_shortcut = shortcut


def find_text(widget) -> None:
    """Открывает панель поиска консоли (прежнее имя сохранено)."""
    bar = getattr(widget, "_console_find_bar", None)
    if bar is None:
        install_search(widget)
        bar = widget._console_find_bar
    if widget.isVisible():
        bar.open_bar()


def copy_text(widget) -> None:
    cursor = widget.textCursor()
    text = cursor.selectedText() if cursor.hasSelection() \
        else widget.toPlainText()
    QApplication.clipboard().setText(text)
