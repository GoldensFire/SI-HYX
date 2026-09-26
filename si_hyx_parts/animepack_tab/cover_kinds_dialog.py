# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Виды и языки исполнения каверов — отдельным окном. Namespace: animepack_tab.

Восемь галочек видов, переключатель языков и ещё пятнадцать галочек самих
языков занимали в колонке настроек десяток строк — две трети экрана, стоило
включить каверы (просьба пользователя). Вопрос «на чём и на каком языке
перепето» задают один раз и надолго, поэтому галочки живут в окне, а на панели
от них осталась строчка-итог и кнопка.

Сами галочки — ТЕ ЖЕ САМЫЕ объекты (`tab.cover_type_checks`,
`tab.cover_lang_checks`, `tab.cmb_cover_lang_mode`): их читают и сохранение
настроек, и тесты. Переехало только место, где они нарисованы.
"""
from __future__ import annotations

import animepack_tab as _api
from cover_meta_rules import TYPE_LABELS

MODE_LABELS = {"allow": "только отмеченные", "exclude": "кроме отмеченных"}


class CoverKindsDialog(_api.QDialog):
    """Окно с уже готовыми галочками видов и языков."""

    def __init__(self, tab, parent=None):
        super().__init__(parent or tab)
        self.setWindowTitle("Виды и языки исполнения")
        self._tab = tab
        root = _api.QVBoxLayout(self)
        root.setSpacing(8)

        root.addWidget(tab._lab("Виды исполнения"))
        types = _api.SettingsBox()
        grid = _api.QGridLayout(types)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        for number, key in enumerate(TYPE_LABELS):
            grid.addWidget(tab.cover_type_checks[key],
                           number // 3, number % 3)
        root.addWidget(types)
        root.addWidget(tab._hint(
            "Ничего не отмечено — берутся любые виды исполнения."))

        row = _api.QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(tab._lab("Язык кавера"))
        row.addWidget(tab.cmb_cover_lang_mode, 1)
        root.addLayout(row)
        langs = _api.SettingsBox()
        lang_grid = _api.QGridLayout(langs)
        lang_grid.setContentsMargins(0, 0, 0, 0)
        lang_grid.setHorizontalSpacing(12)
        for number, key in enumerate(tab.cover_lang_checks):
            lang_grid.addWidget(tab.cover_lang_checks[key],
                                number // 3, number % 3)
        root.addWidget(langs)
        root.addStretch(1)

        buttons = _api.QHBoxLayout()
        buttons.addStretch(1)
        close = _api.QPushButton("Готово")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        root.addLayout(buttons)


def open_dialog(tab) -> None:
    """Показывает окно и обновляет строчку-итог на панели."""
    dialog = getattr(tab, "_cover_kinds_dialog", None)
    if dialog is None:
        dialog = CoverKindsDialog(tab)
        tab._cover_kinds_dialog = dialog
    dialog.exec()
    refresh_summary(tab)


def summary(tab) -> str:
    """Одна строка: что отмечено видами и языками."""
    types = [label for key, label in TYPE_LABELS.items()
             if tab.cover_type_checks[key].isChecked()]
    langs = [check.text() for check in tab.cover_lang_checks.values()
             if check.isChecked()]
    parts = ["Виды: " + (", ".join(types) if types else "любые")]
    if langs:
        mode = MODE_LABELS.get(
            str(tab.cmb_cover_lang_mode.currentData() or "allow"), "")
        parts.append(f"языки ({mode}): " + ", ".join(langs))
    else:
        parts.append("языки: любые")
    return "; ".join(parts) + "."


def refresh_summary(tab) -> None:
    label = getattr(tab, "lbl_cover_kinds", None)
    if label is not None:
        label.setText(summary(tab))
