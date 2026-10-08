# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Поля ввода: сочетание клавиш на любой раскладке, спинбоксы и комбобокс. Public namespace: widgets."""
import widgets as _api


class LatinKeySequenceEdit(_api.QKeySequenceEdit):
    """QKeySequenceEdit, который пишет буквы/цифры по ФИЗИЧЕСКОЙ клавише
    (латиница), а не по текущей раскладке: Shift+Y на русской раскладке даёт
    «Shift+Y», а не «Shift+Н». Для остальных клавиш (F-ряд, стрелки и пр.) —
    штатное поведение базового класса."""
    _MODS = (_api.Qt.Key.Key_Control, _api.Qt.Key.Key_Shift, _api.Qt.Key.Key_Alt, _api.Qt.Key.Key_Meta)
    _KBD = (_api.Qt.KeyboardModifier.ShiftModifier | _api.Qt.KeyboardModifier.ControlModifier
            | _api.Qt.KeyboardModifier.AltModifier | _api.Qt.KeyboardModifier.MetaModifier)

    def keyPressEvent(self, ev):
        # Windows VK: 0x30..0x39 = '0'..'9', 0x41..0x5A = 'A'..'Z' — не зависят от
        # раскладки. Берём латинский символ напрямую по физической клавише.
        vk = ev.nativeVirtualKey()
        latin = chr(vk) if (0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39) else None
        if latin is not None and ev.key() not in self._MODS:
            try:
                key_enum = getattr(_api.Qt.Key, f"Key_{latin}")
                mods = ev.modifiers() & self._KBD
                self.setKeySequence(_api.QKeySequence(int(mods.value) | int(key_enum.value)))
                ev.accept()
                return
            except Exception:
                pass
        super().keyPressEvent(ev)

LatinKeySequenceEdit.__module__ = _api.__name__
_api.LatinKeySequenceEdit = LatinKeySequenceEdit


# --- Custom ComboBox для инвертированного скролла битрейта ---
class InvertedWheelComboBox(_api.QComboBox):
    def wheelEvent(self, event):
        idx = self.currentIndex()
        if event.angleDelta().y() > 0:  # Вверх → повысить битрейт
            if idx < self.count() - 1:
                self.setCurrentIndex(idx + 1)
        else:                            # Вниз → понизить битрейт
            if idx > 0:
                self.setCurrentIndex(idx - 1)
        event.accept()

InvertedWheelComboBox.__module__ = _api.__name__
_api.InvertedWheelComboBox = InvertedWheelComboBox


# --- Custom SpinBox для 01, 02... ---
class ZeroSpinBox(_api.QSpinBox):
    def textFromValue(self, val):
        return f"{val:02d}"

ZeroSpinBox.__module__ = _api.__name__
_api.ZeroSpinBox = ZeroSpinBox


# --- Custom SpinBox для Скорости (100, 105, 107, 110) ---
class SpeedSpinBox(_api.QSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.allowed_steps = [100, 105, 107, 110]
        self.setRange(1, 500)
    
    def wheelEvent(self, event):
        current_val = self.value()
        angle = event.angleDelta().y()
        
        if angle > 0: 
            next_val = next((x for x in self.allowed_steps if x > current_val), None)
            if next_val:
                self.setValue(next_val)
            else:
                if current_val < 500: self.setValue(current_val + 1)
        else:
            prev_val = next((x for x in reversed(self.allowed_steps) if x < current_val), None)
            if prev_val:
                self.setValue(prev_val)
            else:
                if current_val > 1: self.setValue(current_val - 1)
        
        event.accept()

SpeedSpinBox.__module__ = _api.__name__
_api.SpeedSpinBox = SpeedSpinBox
