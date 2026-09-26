# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Один полноширинный ползунок для нижней и верхней границы сложности."""
from __future__ import annotations

import animepack_tab as _api
from .difficulty_slider import DifficultySlider


class DifficultyRange(_api._ShareBar):
    """Диапазон на той же полосе, что доли опенингов и эндингов.

    ``low_control`` и ``high_control`` сохраняют прежний интерфейс настроек:
    код загрузки/сохранения всё ещё видит два обычных DifficultySlider, но на
    экране вместо четырёх коротких полос находится одна полоса с двумя ручками.
    """

    def __init__(self, low=0, high=100, parent=None, *, minimum=0,
                 maximum=100, suffix=""):
        super().__init__(parent=parent)
        self.minimum = int(minimum)
        self.maximum = max(self.minimum + 1, int(maximum))
        self.suffix = str(suffix or "")
        self.set_parts([
            ("below", "", "surface3"),
            ("inside", "", "accent"),
            ("above", "", "surface3"),
        ])
        self.low_control = DifficultySlider(self.minimum, self.maximum, low, self)
        self.high_control = DifficultySlider(self.minimum, self.maximum, high, self)
        self.low_control.hide()
        self.high_control.hide()
        self.low_control.valueChanged.connect(self._low_changed)
        self.high_control.valueChanged.connect(self._high_changed)
        self.changed.connect(self._bar_changed)
        self.set_range(low, high)

    def set_range(self, low: int, high: int) -> None:
        low = max(self.minimum, min(self.maximum, int(low)))
        high = max(low, min(self.maximum, int(high)))
        super().set_values({"below": self._pct(low),
                            "inside": self._pct(high) - self._pct(low),
                            "above": 100 - self._pct(high)})
        self._sync_controls()

    def range_values(self) -> tuple[int, int]:
        cuts = self._cuts()
        return self._value(cuts[0]), self._value(cuts[1])

    def _pct(self, value: int) -> int:
        span = self.maximum - self.minimum
        return int(round((int(value) - self.minimum) * 100.0 / span))

    def _value(self, pct: int) -> int:
        span = self.maximum - self.minimum
        return max(self.minimum, min(self.maximum,
                   int(round(self.minimum + int(pct) * span / 100.0))))

    def _low_changed(self, value: int) -> None:
        _low, high = self.range_values()
        self.set_range(min(value, high), high)

    def _high_changed(self, value: int) -> None:
        low, _high = self.range_values()
        self.set_range(low, max(value, low))

    def _apply_cuts(self, cuts: list[int]) -> None:
        low = self._value(cuts[0])
        high = max(low, self._value(cuts[1]))
        super()._apply_cuts([self._pct(low), self._pct(high)])
        self._sync_controls()

    def _bar_changed(self) -> None:
        self._sync_controls()

    def _sync_controls(self) -> None:
        low, high = self.range_values()
        for control, value in ((self.low_control, low),
                               (self.high_control, high)):
            blocked = control.slider.blockSignals(True)
            control.setValue(value)
            control.slider.blockSignals(blocked)

    def _legend_text(self) -> str:
        low, high = self.range_values()
        return f"От {low}{self.suffix} до {high}{self.suffix}"
