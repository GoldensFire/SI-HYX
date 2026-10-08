# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Горизонтальный переключатель «База Shikimori | Из списков пользователя».

Откуда берутся тайтлы пака: случайной выборкой из базы Shikimori или из
списков добавленных людей (тогда их ники пишутся в ответе). Мастер-лист AMQ
как источник убран (просьба пользователя)."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QPushButton

_STYLE = """
QFrame#sourceSwitch {{
    background: {surface}; border: 1px solid {border}; border-radius: 7px;
}}
QFrame#sourceSwitch QPushButton {{
    background: transparent; color: {text2}; border: none;
    border-radius: 5px; padding: 5px 10px;
}}
QFrame#sourceSwitch QPushButton:hover:!checked {{
    background: {surface3}; color: {text};
}}
QFrame#sourceSwitch QPushButton:checked {{
    background: {accent}; color: {bg}; font-weight: 600;
}}
"""


class SourceSwitch(QFrame):
    """Два взаимоисключающих положения; changed(lists) — выбраны ли списки."""

    changed = pyqtSignal(bool)

    def __init__(self, palette: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("sourceSwitch")
        self.setStyleSheet(_STYLE.format(**palette))
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(2)
        self.btn_shiki = QPushButton("База Shikimori")
        self.btn_lists = QPushButton("Из списков пользователя")
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for button in (self.btn_shiki, self.btn_lists):
            button.setCheckable(True)
            self._group.addButton(button)
            row.addWidget(button, 1)
        self.btn_shiki.setChecked(True)
        self.btn_shiki.toggled.connect(lambda _on: self.changed.emit(self.is_lists()))

    def is_lists(self) -> bool:
        return self.btn_lists.isChecked()

    def set_lists(self, lists: bool) -> None:
        """Без сигнала: так восстанавливаются сохранённые настройки."""
        target = self.btn_lists if lists else self.btn_shiki
        target.blockSignals(True)
        self.btn_shiki.blockSignals(True)
        target.setChecked(True)
        self.btn_shiki.blockSignals(False)
        target.blockSignals(False)
