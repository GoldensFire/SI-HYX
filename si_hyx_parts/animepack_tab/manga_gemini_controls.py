# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Галочка и модель проверки страниц манги через Gemini (как у Pixiv)."""
import animepack_tab as _api


def build_controls(tab, grid, row: int) -> None:
    """Строка «Проверять страницы через Gemini» + модель в группе «Манга»."""
    tab.chk_manga_gemini = _api.QCheckBox("Проверять страницы через Gemini")
    tab.chk_manga_gemini.setChecked(True)
    tab.chk_manga_gemini.setToolTip(
        "Перед добавлением Gemini смотрит саму страницу. Если на ней видно "
        "название манги (титул главы, колонтитул, логотип, титры "
        "переводчиков), берётся другая страница той же манги.\n"
        "Нужен ключ Gemini (Настройки → «Ключи API»). До четырёх картинок "
        "с одинаковой моделью проверяются одним запросом из суточного лимита.")
    tab.cb_manga_gemini_model = _api.QComboBox()
    for model in _api.GEMINI_MODELS:
        tab.cb_manga_gemini_model.addItem(model, model)
    tab.cb_manga_gemini_model.setCurrentText(_api.GEMINI_DEFAULT_MODEL)
    tab.cb_manga_gemini_model.setToolTip(
        "Модель Gemini, которая проверяет страницы манги.")
    tab.chk_manga_gemini.toggled.connect(tab.cb_manga_gemini_model.setEnabled)
    # Галочка и модель — в ОДНОЙ ячейке друг под другом, а не рядом: в одну
    # строку они требовали 564 px, группа «Состав пака» переставала влезать
    # в колонку, и настройки схлопывались в одну колонку на всё окно.
    # Ячейка одна, чтобы вызывающему коду не пришлось сдвигать строки.
    cell = _api.SettingsBox()
    box = _api.QVBoxLayout(cell)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(4)
    box.addWidget(tab.chk_manga_gemini)
    box.addWidget(tab.cb_manga_gemini_model)
    grid.addWidget(cell, row, 0, 1, 4)


def apply_controls(tab, settings) -> None:
    tab.chk_manga_gemini.setChecked(
        bool(getattr(settings, "manga_gemini_check", True)))
    model = (str(getattr(settings, "manga_gemini_model", "") or "")
             or str(getattr(settings, "gemini_model", "") or "")
             or _api.GEMINI_DEFAULT_MODEL)
    if tab.cb_manga_gemini_model.findText(model) < 0:
        tab.cb_manga_gemini_model.addItem(model, model)
    tab.cb_manga_gemini_model.setCurrentText(model)


def collect(tab, settings) -> None:
    settings.manga_gemini_check = tab.chk_manga_gemini.isChecked()
    settings.manga_gemini_model = tab.cb_manga_gemini_model.currentText().strip()
