# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Три положения приоритета с прежним API сохранения настроек."""
import animepack_tab as _api

from .difficulty_slider import DifficultySlider


class PrioritySlider(DifficultySlider):
    currentIndexChanged = _api.pyqtSignal(int)
    KEYS = ("low", "normal", "high")
    LABELS = ("Низкий", "Обычный", "Высокий")

    def __init__(self, parent=None):
        super().__init__(0, 2, 1, parent)
        self.valueChanged.connect(self.currentIndexChanged)

    def _show_value(self, value):
        self.number.setText(self.LABELS[value])

    def currentData(self):
        return self.KEYS[self.value()]

    def findData(self, key):
        return self.KEYS.index(key) if key in self.KEYS else -1

    def setCurrentIndex(self, index):
        self.setValue(index if 0 <= index < len(self.KEYS) else 1)
