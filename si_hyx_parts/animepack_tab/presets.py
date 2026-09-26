# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Редактируемые шаблоны настроек генератора аниме-паков."""
from __future__ import annotations

from copy import deepcopy

from PyQt6.QtWidgets import QInputDialog, QMessageBox

import animepack_tab as _api


META_TEMPLATES = "_templates"
META_ACTIVE = "_active_template"
META_DELETED = "_deleted_templates"
_PRESERVE = {
    "title", "theme_title", "pack_number", "users", "saved_users",
    "exclude_siq", "exclude_exact_siq", "out_dir",
    "gemini_key", "jimaku_key", "subdl_key", "tmdb_key", "cloudflare_token",
    "cloudflare_account_id", "pixiv_refresh_token",
}


def _level_settings(low: int, high: int, average: int) -> dict:
    data = {"level_min": low, "level_max": high, "level_avg": average,
            "char_level_min": low, "char_level_max": high,
            "char_level_avg": average}
    for prefix in ("song", "studio", "plot", "art", "manga"):
        data[f"{prefix}_level_min"] = low
        data[f"{prefix}_level_max"] = high
        data[f"{prefix}_level_avg"] = average
    return data


def default_templates() -> dict[str, dict]:
    easy = _level_settings(1, 6, 3)
    easy.update(difficulty_min=65, difficulty_max=100,
                ost_difficulty_min=55, ost_difficulty_max=100)
    medium = _level_settings(4, 11, 7)
    medium.update(difficulty_min=30, difficulty_max=75,
                  ost_difficulty_min=20, ost_difficulty_max=70)
    hard = _level_settings(9, 15, 12)
    hard.update(difficulty_min=0, difficulty_max=45,
                ost_difficulty_min=0, ost_difficulty_max=35)
    return {"Лёгкий": easy, "Средний": medium, "Сложный": hard}


def load_templates(self, settings: dict) -> None:
    saved = (settings or {}).get(META_TEMPLATES)
    templates = default_templates()
    if isinstance(saved, dict):
        templates.update({str(name): deepcopy(value)
                          for name, value in saved.items()
                          if str(name).strip() and isinstance(value, dict)})
    self._deleted_templates = {
        str(name) for name in ((settings or {}).get(META_DELETED) or [])
        if str(name).strip()}
    for name in self._deleted_templates:
        templates.pop(name, None)
    self._templates = templates
    active = str((settings or {}).get(META_ACTIVE) or "Средний")
    self._active_template = (active if active in templates
                             else next(iter(templates), ""))


def _build_templates(self):
    box = _api.QGroupBox("Шаблон")
    layout = _api.QVBoxLayout(box)
    self.cb_template = _api.QComboBox()
    self.cb_template.addItems(list(self._templates))
    self.cb_template.setCurrentText(self._active_template)
    self.cb_template.currentTextChanged.connect(self._template_selected)
    layout.addWidget(self.cb_template)
    row = _api.QHBoxLayout()
    update_btn = _api.QPushButton("Обновить")
    update_btn.setToolTip("Заменить выбранный шаблон текущими настройками")
    update_btn.clicked.connect(self._update_template)
    row.addWidget(update_btn)
    self.btn_edit_template = _api.QPushButton("Редактировать")
    self.btn_edit_template.setToolTip("Переименовать или удалить шаблон")
    self.btn_edit_template.clicked.connect(self._edit_template)
    row.addWidget(self.btn_edit_template)
    layout.addLayout(row)
    save_btn = _api.QPushButton("Сохранить как…")
    save_btn.clicked.connect(self._save_template_as)
    layout.addWidget(save_btn)
    return box


def _template_selected(self, name: str) -> None:
    if name in self._templates:
        self._apply_template()


def _apply_template(self) -> None:
    name = self.cb_template.currentText()
    values = self._templates.get(name)
    if not isinstance(values, dict):
        return
    current = self.collect().to_dict()
    current.update(deepcopy(values))
    self.apply_settings(current)
    self._active_template = name
    _save_soon(self)


def _editable_settings(self) -> dict:
    data = self.collect().to_dict()
    for key in _PRESERVE:
        data.pop(key, None)
    return data


def _update_template(self) -> None:
    name = self.cb_template.currentText()
    if name:
        self._templates[name] = self._editable_settings()
        self._active_template = name
        _save_soon(self)


def _save_template_as(self) -> None:
    name, ok = QInputDialog.getText(self, "Новый шаблон", "Название:")
    name = str(name or "").strip()
    if not ok or not name:
        return
    self._templates[name] = self._editable_settings()
    self._deleted_templates.discard(name)
    if self.cb_template.findText(name) < 0:
        self.cb_template.addItem(name)
    self.cb_template.setCurrentText(name)
    _save_soon(self)


def _edit_template(self) -> None:
    if not self.cb_template.currentText():
        return
    menu = _api.QMenu(self.btn_edit_template)
    menu.addAction("Переименовать", self._rename_template)
    menu.addAction("Удалить", self._delete_template)
    menu.exec(self.btn_edit_template.mapToGlobal(
        self.btn_edit_template.rect().bottomLeft()))


def _rename_template(self) -> None:
    old = self.cb_template.currentText()
    if old not in self._templates:
        return
    name, ok = QInputDialog.getText(self, "Переименовать шаблон",
                                    "Новое название:", text=old)
    name = str(name or "").strip()
    if not ok or not name or name == old:
        return
    if name in self._templates:
        QMessageBox.warning(self, "Шаблон уже существует",
                            f"Шаблон «{name}» уже существует.")
        return
    self._templates[name] = self._templates.pop(old)
    self._deleted_templates.add(old)
    self._deleted_templates.discard(name)
    index = self.cb_template.currentIndex()
    self.cb_template.setItemText(index, name)
    self._active_template = name
    _save_soon(self)


def _delete_template(self) -> None:
    name = self.cb_template.currentText()
    if name not in self._templates:
        return
    answer = QMessageBox.question(
        self, "Удалить шаблон", f"Удалить шаблон «{name}»?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if answer != QMessageBox.StandardButton.Yes:
        return
    self._templates.pop(name, None)
    self._deleted_templates.add(name)
    self.cb_template.removeItem(self.cb_template.currentIndex())
    self._active_template = self.cb_template.currentText()
    _save_soon(self)


def templates_to_settings(self, data: dict) -> dict:
    data[META_TEMPLATES] = deepcopy(self._templates)
    data[META_ACTIVE] = str(self._active_template or "")
    data[META_DELETED] = sorted(self._deleted_templates)
    return data


def _save_soon(self) -> None:
    saver = getattr(getattr(self, "main", None), "_save_settings_soon", None)
    if saver is not None:
        saver()
