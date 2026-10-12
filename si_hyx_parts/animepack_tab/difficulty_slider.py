# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Ползунок сложности с постоянно видимым числом. Namespace: animepack_tab."""
from __future__ import annotations

import animepack_tab as _api


class _JumpSlider(_api.QSlider):
    """QSlider, у которого клик по дорожке ставит ручку прямо в точку клика.

    Обычный QSlider сдвигается на pageStep к курсору: на трёх положениях
    приоритета клик по «Низкому» с «Высокого» доводил только до «Обычного»."""

    def mousePressEvent(self, event):
        if event.button() != _api.Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        from PyQt6.QtWidgets import QStyle, QStyleOptionSlider
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        style = self.style()
        handle = style.subControlRect(QStyle.ComplexControl.CC_Slider, opt,
                                      QStyle.SubControl.SC_SliderHandle, self)
        pos = event.position().toPoint()
        if not handle.contains(pos):
            groove = style.subControlRect(QStyle.ComplexControl.CC_Slider, opt,
                                          QStyle.SubControl.SC_SliderGroove, self)
            span = max(1, groove.width() - handle.width())
            x = pos.x() - groove.x() - handle.width() // 2
            self.setValue(QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(), x, span, opt.upsideDown))
        # Дальше штатная обработка: ручка уже под курсором, её можно тянуть.
        super().mousePressEvent(event)


class DifficultySlider(_api.QWidget):
    """QSlider с интерфейсом значения, совместимым с прежним QSpinBox."""

    valueChanged = _api.pyqtSignal(int)

    def __init__(self, minimum=0, maximum=100, value=0, parent=None):
        super().__init__(parent)
        self._special = ""
        self._suffix = ""
        self.slider = _JumpSlider(_api.Qt.Orientation.Horizontal)
        self.slider.setRange(int(minimum), int(maximum))
        self.slider.setSingleStep(1)
        self.slider.setPageStep(max(1, (int(maximum) - int(minimum)) // 10))
        self.slider.setTickPosition(_api.QSlider.TickPosition.TicksBelow)
        self.slider.setTickInterval(max(1, (int(maximum) - int(minimum)) // 10))
        self.number = _api.QLabel()
        self.number.setMinimumWidth(38)
        self.number.setAlignment(_api.Qt.AlignmentFlag.AlignRight |
                                 _api.Qt.AlignmentFlag.AlignVCenter)
        row = _api.QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(self.slider, 1)
        row.addWidget(self.number)
        self.slider.valueChanged.connect(self._changed)
        self.setValue(value)
        self._show_value(self.value())

    def _changed(self, value):
        self._show_value(value)
        self.valueChanged.emit(value)

    def _show_value(self, value):
        text = self._special if self._special and value == self.minimum() else str(value)
        self.number.setText(text + (self._suffix if text != self._special else ""))

    def value(self):
        return self.slider.value()

    def setValue(self, value):
        self.slider.setValue(int(value))
        self._show_value(self.value())

    def setRange(self, minimum, maximum):
        self.slider.setRange(int(minimum), int(maximum))
        span = int(maximum) - int(minimum)
        self.slider.setPageStep(max(1, span // 10))
        self.slider.setTickInterval(max(1, span // 10))
        self._show_value(self.value())

    def minimum(self):
        return self.slider.minimum()

    def maximum(self):
        return self.slider.maximum()

    def setSingleStep(self, step):
        self.slider.setSingleStep(int(step))

    def setSpecialValueText(self, text):
        self._special = str(text or "")
        self._show_value(self.value())

    def setSuffix(self, suffix):
        self._suffix = str(suffix or "")
        self._show_value(self.value())

    def setToolTip(self, text):
        super().setToolTip(text)
        self.slider.setToolTip(text)
        self.number.setToolTip(text)
