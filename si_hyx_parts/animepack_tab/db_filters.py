# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Собственные фильтры окна базы, независимые от состава генерации."""
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QGroupBox, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QFormLayout, QSpinBox, QDoubleSpinBox, QComboBox,
)

import animepack_tab as api
from .db_view_filters import RANGES


class DbFiltersDialog(QDialog):
    def __init__(self, filters, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Фильтры отображения базы")
        layout = QVBoxLayout(self)
        note = QLabel("Только отображение таблиц. Обновление всегда собирает полные каталоги.")
        note.setWordWrap(True)
        layout.addWidget(note)
        groups = QHBoxLayout()
        self.checks = {}
        for target, title, kinds, labels in (
                ("anime", "Аниме", api.ANIME_KINDS, api.KIND_LABELS),
                ("manga", "Манга", api.MANGA_KINDS, api.MANGA_KIND_LABELS)):
            box = QGroupBox(title)
            column = QVBoxLayout(box)
            selected = filters.get(target)
            self.checks[target] = {}
            for kind in kinds:
                check = QCheckBox(labels.get(kind, kind))
                check.setChecked(selected is None or kind in selected)
                column.addWidget(check)
                self.checks[target][kind] = check
            column.addStretch()
            groups.addWidget(box)
        layout.addLayout(groups)
        ranges = QFormLayout()
        self.ranges = {}
        for field, label, maximum in RANGES:
            row = QHBoxLayout()
            for side in ("from", "to"):
                control = QDoubleSpinBox() if field == "score" else QSpinBox()
                control.setRange(0, maximum)
                control.setSpecialValueText("—")
                control.setValue(filters.get(f"{field}_{side}") or 0)
                row.addWidget(QLabel("от" if side == "from" else "до"))
                row.addWidget(control)
                self.ranges[f"{field}_{side}"] = control
            ranges.addRow(label, row)
        self.favorites = QComboBox()
        for label, value in (("Все", None), ("Известно", "NORMAL"),
                             ("Неизвестно", "UNKNOWN"), ("Требуется вход 18+", "AGE_RESTRICTED"),
                             ("Страница не найдена", "NOT_FOUND")):
            self.favorites.addItem(label, value)
        self.favorites.setCurrentIndex(max(0, self.favorites.findData(filters.get("favorites_status"))))
        ranges.addRow("Избранное", self.favorites)
        layout.addLayout(ranges)
        reset = QPushButton("Показать всё")
        reset.clicked.connect(self.reset)
        layout.addWidget(reset)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Применить")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def reset(self):
        for checks in self.checks.values():
            for check in checks.values():
                check.setChecked(True)
        for control in self.ranges.values():
            control.setValue(0)
        self.favorites.setCurrentIndex(0)

    def values(self):
        result = {}
        for target, checks in self.checks.items():
            selected = tuple(kind for kind, check in checks.items()
                             if check.isChecked())
            result[target] = None if len(selected) == len(checks) else selected
        result.update({key: control.value() or None for key, control in self.ranges.items()})
        result["favorites_status"] = self.favorites.currentData()
        return result
