# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Редактируемые шаблоны настроек генератора аниме-паков."""
from __future__ import annotations

from copy import deepcopy

from PyQt6.QtCore import QPoint, QTimer, Qt
from PyQt6.QtWidgets import QInputDialog, QLabel, QMessageBox

import animepack_tab as _api


META_TEMPLATES = "_templates"
META_ACTIVE = "_active_template"
META_DELETED = "_deleted_templates"
_PRESERVE = {
    "title", "theme_title", "pack_number", "test_pack_number",
    "users", "saved_users",
    "exclude_siq", "exclude_exact_siq", "auto_add_to_exclusions", "out_dir",
    "gemini_key", "elevenlabs_key", "jimaku_key", "subdl_key", "tmdb_key", "cloudflare_token",
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
    title_row = _api.QHBoxLayout()
    self.cb_template = _api.QComboBox()
    self.cb_template.addItems(list(self._templates))
    self.cb_template.setCurrentText(self._active_template)
    self.cb_template.setEditable(True)
    self.cb_template.setInsertPolicy(_api.QComboBox.InsertPolicy.NoInsert)
    self.cb_template.setToolTip("Выберите шаблон или нажмите на название, чтобы переименовать")
    self.cb_template.currentIndexChanged.connect(self._template_selected)
    self.cb_template.lineEdit().editingFinished.connect(self._rename_template)
    title_row.addWidget(self.cb_template, 1)
    self.btn_delete_template = _api.QToolButton()
    self.btn_delete_template.setIcon(_api.get_icon("fa5s.trash-alt"))
    self.btn_delete_template.setFixedWidth(34)
    self.btn_delete_template.setToolTip("Удалить выбранный шаблон")
    self.btn_delete_template.clicked.connect(self._delete_template)
    title_row.addWidget(self.btn_delete_template)
    layout.addLayout(title_row)
    row = _api.QHBoxLayout()
    update_btn = _api.QPushButton("Обновить")
    update_btn.setFixedWidth(116)
    update_btn.setToolTip("Заменить выбранный шаблон текущими настройками")
    update_btn.clicked.connect(self._update_template)
    row.addWidget(update_btn)
    save_btn = _api.QPushButton("Сохранить…")
    save_btn.setToolTip("Сохранить текущие настройки как новый шаблон")
    save_btn.clicked.connect(self._save_template_as)
    row.addWidget(save_btn, 1)
    layout.addLayout(row)
    self.template_notice = QLabel("Шаблон обновлён и сохранён", self,
                                  Qt.WindowType.ToolTip)
    self.template_notice.setTextFormat(Qt.TextFormat.PlainText)
    self.template_notice.setWordWrap(True)
    self.template_notice.setMaximumWidth(420)
    self.template_notice.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    self.template_notice.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    self.template_notice.setStyleSheet(
        "background: #243b2e; color: #bde8cc; padding: 8px; "
        "border: 1px solid #399b68; border-radius: 6px; font-size: 11px;")
    self.template_notice.hide()
    self._template_notice_timer = QTimer(self)
    self._template_notice_timer.setSingleShot(True)
    self._template_notice_timer.timeout.connect(self.template_notice.hide)
    return box


def _template_selected(self, _index: int) -> None:
    name = self.cb_template.itemText(self.cb_template.currentIndex())
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
    name = self.cb_template.itemText(self.cb_template.currentIndex())
    if name:
        self._templates[name] = self._editable_settings()
        self._active_template = name
        saver = getattr(getattr(self, "main", None), "_save_settings_now", None)
        if saver is None:
            _save_soon(self)
            saved = True
        else:
            saved = saver()
        if saved:
            self.template_notice.setText(f"Шаблон «{name}» обновлён и сохранён")
            self.template_notice.adjustSize()
            self.template_notice.move(self.templates_box.mapToGlobal(
                QPoint(0, self.templates_box.height())))
            self.template_notice.show()
            self._template_notice_timer.start(3500)


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


def _rename_template(self) -> None:
    index = self.cb_template.currentIndex()
    old = self.cb_template.itemText(index)
    if old not in self._templates:
        return
    name = self.cb_template.lineEdit().text().strip()
    if not name or name == old:
        self.cb_template.setCurrentText(old)
        return
    if name in self._templates:
        QMessageBox.warning(self, "Шаблон уже существует",
                            f"Шаблон «{name}» уже существует.")
        self.cb_template.setCurrentText(old)
        return
    self._templates[name] = self._templates.pop(old)
    self._deleted_templates.add(old)
    self._deleted_templates.discard(name)
    self.cb_template.setItemText(index, name)
    self._active_template = name
    _save_soon(self)


def _delete_template(self) -> None:
    name = self.cb_template.itemText(self.cb_template.currentIndex())
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
