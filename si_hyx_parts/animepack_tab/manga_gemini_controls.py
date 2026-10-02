# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Выбор проверки названия страниц манги: Gemini или локальный OCR."""
import animepack_tab as _api


def build_controls(tab, grid, row: int) -> None:
    """Строка «Проверять страницы через Gemini» + модель в группе «Манга»."""
    tab.chk_manga_gemini = _api.QCheckBox("Проверять названия на страницах")
    tab.chk_manga_gemini.setChecked(True)
    tab.chk_manga_gemini.setToolTip(
        "Перед добавлением выбранный способ смотрит саму страницу. Если видно "
        "название манги (титул главы, колонтитул, логотип, титры "
        "переводчиков), берётся другая страница той же манги.\n"
        "Для режима Gemini нужен ключ (Настройки → «Ключи API»). OCR "
        "работает локально; при сомнениях использует Gemini, если ключ есть.")
    tab.cb_manga_gemini_model = _api.QComboBox()
    for model in _api.GEMINI_MODELS:
        tab.cb_manga_gemini_model.addItem(model, model)
    tab.cb_manga_gemini_model.setCurrentText(_api.GEMINI_DEFAULT_MODEL)
    tab.cb_manga_gemini_model.setToolTip(
        "Модель Gemini для выбора сцены с персонажами и проверки названий.")
    # Галочка и модель — в ОДНОЙ ячейке друг под другом, а не рядом: в одну
    # строку они требовали 564 px, группа «Состав пака» переставала влезать
    # в колонку, и настройки схлопывались в одну колонку на всё окно.
    # Ячейка одна, чтобы вызывающему коду не пришлось сдвигать строки.
    cell = _api.SettingsBox()
    box = _api.QVBoxLayout(cell)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(4)
    tab.chk_manga_character_crop = _api.QCheckBox(
        "Сцена с персонажами из вебтуна (Gemini)")
    tab.chk_manga_character_crop.setChecked(True)
    tab.chk_manga_character_crop.setToolTip(
        "Gemini просматривает манхву и маньхуа, включая короткие куски страниц, "
        "и длинные ленты манги. Соседние куски соединяются, чтобы сохранить "
        "лицо целиком. Большие пустые поля обрезаются. Готовая вырезка "
        "проверяется отдельно: одни реплики, обрубки лица и пустые области "
        "отклоняются. Книжные страницы японской манги сохраняются целиком. "
        "Нужен ключ Gemini.")
    box.addWidget(tab.chk_manga_character_crop)
    box.addWidget(tab.chk_manga_gemini)
    tab.cb_manga_title_mode = _api.QComboBox()
    tab.cb_manga_title_mode.addItem("Gemini", "gemini")
    tab.cb_manga_title_mode.addItem("Локальный OCR (Gemini при сомнениях)", "local")
    tab.cb_manga_title_mode.setToolTip(
        "OCR проверяет латиницу и кириллицу на компьютере. При неясном "
        "результате может обратиться к Gemini, если есть ключ.")
    box.addWidget(tab.cb_manga_title_mode)
    box.addWidget(tab.cb_manga_gemini_model)
    def refresh():
        tab.cb_manga_gemini_model.setEnabled(
            tab.chk_manga_character_crop.isChecked()
            or tab.chk_manga_gemini.isChecked())
        tab.cb_manga_title_mode.setEnabled(tab.chk_manga_gemini.isChecked())

    tab.chk_manga_gemini.toggled.connect(refresh)
    tab.chk_manga_character_crop.toggled.connect(refresh)
    tab.cb_manga_title_mode.currentIndexChanged.connect(refresh)
    refresh()
    grid.addWidget(cell, row, 0, 1, 4)


def apply_controls(tab, settings) -> None:
    tab.chk_manga_character_crop.setChecked(
        bool(getattr(settings, "manga_character_crop", True)))
    tab.chk_manga_gemini.setChecked(
        bool(getattr(settings, "manga_gemini_check", True)))
    mode = str(getattr(settings, "manga_title_check_mode", "gemini") or "gemini")
    tab.cb_manga_title_mode.setCurrentIndex(max(0, tab.cb_manga_title_mode.findData(mode)))
    model = (str(getattr(settings, "manga_gemini_model", "") or "")
             or str(getattr(settings, "gemini_model", "") or "")
             or _api.GEMINI_DEFAULT_MODEL)
    if tab.cb_manga_gemini_model.findText(model) < 0:
        tab.cb_manga_gemini_model.addItem(model, model)
    tab.cb_manga_gemini_model.setCurrentText(model)


def collect(tab, settings) -> None:
    settings.manga_character_crop = tab.chk_manga_character_crop.isChecked()
    settings.manga_gemini_check = tab.chk_manga_gemini.isChecked()
    settings.manga_title_check_mode = tab.cb_manga_title_mode.currentData() or "gemini"
    settings.manga_gemini_model = tab.cb_manga_gemini_model.currentText().strip()
