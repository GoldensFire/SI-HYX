# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Один полноширинный ползунок для нижней и верхней границы сложности."""
from __future__ import annotations

import animepack_tab as _api
from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QFontMetrics, QPainterPath, QPen
from .difficulty_slider import DifficultySlider


class DifficultyRange(_api._ShareBar):
    """Диапазон на той же полосе, что доли опенингов и эндингов.

    ``low_control`` и ``high_control`` сохраняют прежний интерфейс настроек:
    код загрузки/сохранения всё ещё видит два обычных DifficultySlider, но на
    экране вместо четырёх коротких полос находится одна полоса с двумя ручками.
    """

    def __init__(self, low=0, high=100, parent=None, *, minimum=0,
                 maximum=100, suffix="", average=False, formatter=None):
        super().__init__(parent=parent)
        self.minimum = int(minimum)
        self.maximum = max(self.minimum + 1, int(maximum))
        self.suffix = str(suffix or "")
        # Подпись значения: оценка хранится десятыми, а показывается «7.5».
        self.formatter = formatter or str
        self._show_average = bool(average)
        self.set_parts([
            ("below", "", "surface3"),
            ("inside", "", "accent"),
            ("above", "", "surface3"),
        ])
        self.low_control = DifficultySlider(self.minimum, self.maximum, low, self)
        self.high_control = DifficultySlider(self.minimum, self.maximum, high, self)
        self.avg_control = DifficultySlider(0, self.maximum, 0, self)
        self.any_check = _api.QCheckBox("Любая", self)
        self.any_check.setChecked(True)
        self.any_check.setVisible(self._show_average)
        self.any_check.setToolTip("Не задавать отдельную среднюю сложность")
        self.low_control.hide()
        self.high_control.hide()
        self.avg_control.hide()
        self.low_control.valueChanged.connect(self._low_changed)
        self.high_control.valueChanged.connect(self._high_changed)
        self.avg_control.valueChanged.connect(self._avg_changed)
        self.any_check.toggled.connect(self._any_changed)
        self.changed.connect(self._bar_changed)
        self._avg_drag = False
        self._overlap = ""
        self.set_range(low, high)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.any_check.setGeometry(max(0, self.width() - 82), 0, 76, 24)

    def _bar_rect(self):
        reserve = 96 if self._show_average else 10
        return _api.QRect(10, 4, max(1, self.width() - reserve - 10), self.BAR_H)

    def _x_of(self, pct: int) -> int:
        bar = self._bar_rect()
        return bar.x() + int(round(bar.width() * pct / 100.0))

    def _pct_of(self, x: int) -> int:
        bar = self._bar_rect()
        return max(0, min(100, int(round((x - bar.x()) * 100.0 / bar.width()))))

    def set_range(self, low: int, high: int) -> None:
        low = max(self.minimum, min(self.maximum, int(low)))
        high = max(low, min(self.maximum, int(high)))
        super().set_values({"below": self._pct(low),
                            "inside": self._pct(high) - self._pct(low),
                            "above": 100 - self._pct(high)})
        self._sync_controls()
        self._clamp_avg()

    def _clamp_avg(self):
        if not self._show_average:
            return
        avg = self.avg_control.value()
        if avg:
            low, high = self.range_values()
            self.avg_control.setValue(max(low, min(high, avg)))

    def _avg_changed(self, value):
        if value:
            low, high = self.range_values()
            bounded = max(low, min(high, value))
            if bounded != value:
                self.avg_control.setValue(bounded)
                return
        self.any_check.blockSignals(True)
        self.any_check.setChecked(value == 0)
        self.any_check.blockSignals(False)
        self.update()

    def _any_changed(self, checked):
        if checked:
            self.avg_control.setValue(0)
        elif not self.avg_control.value():
            low, high = self.range_values()
            self.avg_control.setValue((low + high) // 2)
        self.update()

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
        self._clamp_avg()

    def _bar_changed(self) -> None:
        self._sync_controls()
        self._clamp_avg()

    def mousePressEvent(self, event):
        avg = self.avg_control.value()
        low, high = self.range_values()
        if avg and abs(event.position().x() - self._x_of(self._pct(avg))) <= 9:
            if avg == low or avg == high:
                # Когда ручки совпали, направление перетаскивания решает,
                # какую двигать: наружу — край диапазона, внутрь — среднюю.
                self._overlap = ("both" if low == high else
                                 "low" if avg == low else "high")
                self._press_x = event.position().x()
                return
            self._avg_drag = True
            self._move_avg(event.position().x())
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._overlap:
            delta = event.position().x() - self._press_x
            if abs(delta) < 2:
                return
            move_edge = (self._overlap == "both" or
                         (delta < 0 if self._overlap == "low" else delta > 0))
            if move_edge:
                self._drag = (0 if self._overlap == "low" or
                              (self._overlap == "both" and delta < 0) else 1)
            else:
                self._avg_drag = True
            self._overlap = ""
        if self._avg_drag:
            self._move_avg(event.position().x())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._avg_drag = False
        self._overlap = ""
        super().mouseReleaseEvent(event)

    def _move_avg(self, x):
        low, high = self.range_values()
        self.avg_control.setValue(max(low, min(high, self._value(self._pct_of(x)))))

    def paintEvent(self, event):
        if not self._keys:
            return
        painter = _api.QPainter(self)
        painter.setRenderHint(_api.QPainter.RenderHint.Antialiasing)
        bar = self._bar_rect()
        track = QRectF(bar)
        track.adjust(0.5, 0.5, -0.5, -0.5)
        shape = QPainterPath()
        shape.addRoundedRect(track, 5, 5)
        painter.fillPath(shape, _api.QColor(_api.C["surface3"]))
        cuts = self._cuts()
        if len(cuts) == 2:
            painter.save()
            painter.setClipPath(shape)
            painter.fillRect(QRectF(self._x_of(cuts[0]), track.y(),
                                    max(0, self._x_of(cuts[1]) - self._x_of(cuts[0])),
                                    track.height()), _api.QColor(_api.C["accent"]))
            painter.restore()
        painter.setPen(QPen(_api.QColor(_api.C["border"]), 1))
        painter.setBrush(_api.Qt.BrushStyle.NoBrush)
        painter.drawPath(shape)
        painter.setPen(_api.Qt.PenStyle.NoPen)
        painter.setBrush(_api.QColor(_api.C["text"]))
        for cut in cuts:
            painter.drawRoundedRect(QRectF(self._x_of(cut) - 4.5, 1, 9, 22), 2, 2)
        avg = self.avg_control.value()
        if avg:
            painter.setPen(QPen(_api.QColor(_api.C["accent2"]), 1.5))
            painter.setBrush(_api.QColor(_api.C["text"]))
            painter.drawEllipse(QRectF(self._x_of(self._pct(avg)) - 8, 4, 16, 16))
        painter.setPen(_api.QColor(_api.C["text2"]))
        painter.setFont(self._legend_font())
        painter.drawText(_api.QRect(bar.x(), 25, bar.width(), max(1, self.height() - 27)),
                         int(_api.Qt.AlignmentFlag.AlignHCenter |
                             _api.Qt.TextFlag.TextWordWrap), self._legend_text())

    def _sync_height(self) -> None:
        fm = QFontMetrics(self._legend_font())
        width = max(1, self._bar_rect().width())
        need = fm.boundingRect(_api.QRect(0, 0, width, 1000),
                               int(_api.Qt.AlignmentFlag.AlignHCenter |
                                   _api.Qt.TextFlag.TextWordWrap),
                               self._legend_text()).height()
        self.setMinimumHeight(27 + max(fm.height(), need) + 2)

    def _sync_controls(self) -> None:
        low, high = self.range_values()
        for control, value in ((self.low_control, low),
                               (self.high_control, high)):
            blocked = control.slider.blockSignals(True)
            control.setValue(value)
            control.slider.blockSignals(blocked)

    def _legend_text(self) -> str:
        if not self._cuts() or not hasattr(self, "avg_control"):
            return ""
        low, high = self.range_values()
        low, high = self.formatter(low), self.formatter(high)
        if not self._show_average:
            return f"От {low}{self.suffix} до {high}{self.suffix}"
        avg = self.avg_control.value()
        return (f"От {low}{self.suffix} до {high}{self.suffix} · "
                f"В среднем: {avg if avg else 'Любая'}")


class ScaledBound:
    """Граница ползунка в единицах настройки: ``value()``/``setValue()`` как у
    прежнего QDoubleSpinBox, а ручка полосы целая (оценка — в десятых)."""

    def __init__(self, control, scale: int):
        self.control = control
        self.scale = int(scale)

    def value(self) -> float:
        return self.control.value() / self.scale

    def setValue(self, value) -> None:
        self.control.setValue(int(round(float(value) * self.scale)))
