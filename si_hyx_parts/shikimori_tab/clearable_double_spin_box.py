# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ClearableDoubleSpinBox. Public namespace: shikimori_tab."""
import shikimori_tab as _api


class ClearableDoubleSpinBox(_api.QDoubleSpinBox):
    """QDoubleSpinBox, который МОЖНО очистить с клавиатуры (Backspace/Delete).

    Обычный QDoubleSpinBox при стирании всего текста считает пустую строку
    «промежуточной» (Intermediate) и при потере фокуса откатывается к прежнему
    значению — поэтому очистить поле не получается. Здесь пустой ввод трактуется
    как минимум диапазона: при заданном setSpecialValueText() поле показывает
    спецтекст (например «любая»), то есть фильтр сбрасывается.
    """

    def validate(self, text, pos):  # type: ignore[override]
        if text.strip() == "":
            return (_api.QValidator.State.Acceptable, text, pos)
        return super().validate(text, pos)

    def valueFromText(self, text):  # type: ignore[override]
        if text.strip() == "":
            return self.minimum()
        return super().valueFromText(text)

ClearableDoubleSpinBox.__module__ = _api.__name__
_api.ClearableDoubleSpinBox = ClearableDoubleSpinBox
