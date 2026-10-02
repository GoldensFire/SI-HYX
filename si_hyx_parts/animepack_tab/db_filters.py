# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Собственные фильтры окна базы, независимые от состава генерации."""
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QGroupBox, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout,
)

import animepack_tab as api


class DbFiltersDialog(QDialog):
    def __init__(self, filters, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Фильтры базы")
        layout = QVBoxLayout(self)
        note = QLabel("Фильтры меняют только таблицы этого окна.")
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

    def values(self):
        result = {}
        for target, checks in self.checks.items():
            selected = tuple(kind for kind, check in checks.items()
                             if check.isChecked())
            result[target] = None if len(selected) == len(checks) else selected
        return result
