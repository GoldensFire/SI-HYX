# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Выбор эффекта появления для текущей картинки или видео в монтаже."""
from PIL import Image, ImageOps
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QLabel, QSpinBox, QVBoxLayout)
from PyQt6.QtCore import Qt

from image_entrance import EFFECTS
from si_hyx_parts.animepack_tab.entrance_preview import EntrancePreview


class EntranceDialog(QDialog):
    def __init__(self, parent, source, is_image):
        super().__init__(parent)
        self.setWindowTitle("Появление")
        self.resize(440, 460)
        layout = QVBoxLayout(self)
        label = QLabel("Выберите, как картинка появится в начале видео.")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.cb_entrance_effect = QComboBox()
        for key, (name, english, hint) in EFFECTS.items():
            self.cb_entrance_effect.addItem(name, key)
            self.cb_entrance_effect.setItemData(
                self.cb_entrance_effect.count() - 1, f"{english}\n{hint}",
                Qt.ItemDataRole.ToolTipRole)
        layout.addWidget(self.cb_entrance_effect)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.sp_entrance_seconds = QDoubleSpinBox()
        self.sp_entrance_seconds.setRange(0.2, 5)
        self.sp_entrance_seconds.setSingleStep(0.1)
        self.sp_entrance_seconds.setValue(1.2)
        self.sp_entrance_seconds.setSuffix(" с")
        self.sp_entrance_strength = self._spin(10, 100, 70, " %")
        self.sp_entrance_fps = self._spin(10, 60, 30)
        self.sp_entrance_preset = self._spin(0, 13, 13)
        self.sp_crf = self._spin(0, 63, 25)
        form = QFormLayout()
        for text, widget in (("Длительность появления", self.sp_entrance_seconds),
                             ("Сила", self.sp_entrance_strength),
                             ("Кадров/с", self.sp_entrance_fps),
                             ("Пресет кодирования", self.sp_entrance_preset),
                             ("Качество (CRF)", self.sp_crf)):
            form.addRow(text, widget)
        layout.addLayout(form)
        self.entrance_preview = EntrancePreview(self)
        if is_image:
            try:
                with Image.open(source) as opened:
                    original = ImageOps.exif_transpose(opened).convert("RGB")
                original.thumbnail((320, 180), Image.Resampling.LANCZOS)
                self.entrance_preview.original = original
            except (OSError, ValueError):
                pass
        layout.addWidget(self.entrance_preview)
        note = QLabel("Результат сохраняется новым видео. У исходного ролика "
                      "сохраняются звук и длительность.")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Создать видео")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.cb_entrance_effect.currentIndexChanged.connect(self._refresh)
        for field in (self.sp_entrance_seconds, self.sp_entrance_strength):
            field.valueChanged.connect(self.entrance_preview.restart)
        self._refresh()

    @staticmethod
    def _spin(minimum, maximum, value, suffix=""):
        field = QSpinBox()
        field.setRange(minimum, maximum)
        field.setValue(value)
        field.setSuffix(suffix)
        return field

    def _refresh(self):
        self.hint.setText(EFFECTS[self.cb_entrance_effect.currentData()][2])
        self.entrance_preview.restart()

    def options(self):
        return {"effect": self.cb_entrance_effect.currentData(),
                "seconds": self.sp_entrance_seconds.value(),
                "strength": self.sp_entrance_strength.value(),
                "fps": self.sp_entrance_fps.value(),
                "preset": self.sp_entrance_preset.value(), "crf": self.sp_crf.value()}
