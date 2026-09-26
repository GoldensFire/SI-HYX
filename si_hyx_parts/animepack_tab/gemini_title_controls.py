# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Своя модель Gemini у ЗАГАДОК ПО НАЗВАНИЮ. Namespace: animepack_tab.

Сюжетный вопрос и перевод диалогов — это пересказ живого текста, а синонимы,
антонимы, украинский и определения — работа со словарём: сто названий уходят
одним запросом, и модель тут нужна другая (просьба пользователя). Ключ остаётся
общим: он один на весь Gemini.
"""
from __future__ import annotations

import animepack_tab as api


def build_controls(tab):
    """Заводит вторую пару списков (модель + рассуждение) и их коробку."""
    tab.cb_gemini_title_model = api.QComboBox()
    for model in api.GEMINI_MODELS:
        tab.cb_gemini_title_model.addItem(model, model)
    tab.cb_gemini_title_model.setCurrentText(api.GEMINI_DEFAULT_MODEL)
    tab.cb_gemini_title_model.setToolTip(
        "Модель для загадок по названию: синонимы, антонимы, украинский, "
        "определения.\n"
        "Отдельная от сюжета и диалогов: там модель пересказывает живой "
        "текст, а здесь подбирает слова к сотне названий за один запрос.\n"
        "Ключ Gemini общий — он задаётся выше, у сюжетных вопросов.")
    tab.cb_gemini_title_think = api.QComboBox()
    for level in api.GEMINI_THINKING_LEVELS:
        tab.cb_gemini_title_think.addItem(api.GEMINI_THINKING_LABELS[level],
                                          level)
    tab.cb_gemini_title_think.setCurrentIndex(
        tab.cb_gemini_title_think.findData(api.GEMINI_THINKING_LEVEL))
    tab.cb_gemini_title_think.setToolTip(
        "Сколько модель думает над загадками по названию.\n"
        "Выше уровень — аккуратнее синонимы и определения, но каждый запрос "
        "идёт дольше, а суточная квота бесплатного тарифа кончается быстрее.")
    tab.cb_gemini_title_model.currentTextChanged.connect(
        lambda: refresh_levels(tab))
    tab.box_gemini_titles = api.SettingsBox()
    grid = api.QGridLayout(tab.box_gemini_titles)
    grid.setContentsMargins(16, 0, 0, 0)
    grid.setHorizontalSpacing(8)
    grid.setVerticalSpacing(6)
    grid.addWidget(tab._hint(
        "Загадки по названию спрашивают Gemini своей моделью — ключ общий "
        "с сюжетными вопросами."), 0, 0, 1, 2)
    grid.addWidget(tab.cb_gemini_title_model, 1, 0, 1, 2)
    grid.addWidget(tab.cb_gemini_title_think, 2, 0, 1, 2)
    grid.setColumnStretch(1, 1)
    tab.box_gemini_titles.setVisible(False)
    refresh_levels(tab)


def refresh_levels(tab):
    """Оставляет только уровни, которые принимает выбранная модель.

    Та же оговорка, что и у сюжета: «Минимальный» умеет один Flash-Lite, и
    обычный Flash отвечает на него 400 (см. gemini_model_controls)."""
    from gemini_api import model_thinking_levels

    box = getattr(tab, "cb_gemini_title_think", None)
    if box is None:
        return
    levels = model_thinking_levels(tab.cb_gemini_title_model.currentText())
    if [box.itemData(i) for i in range(box.count())] == list(levels):
        return
    want = box.currentData()
    box.blockSignals(True)
    box.clear()
    for level in levels:
        box.addItem(api.GEMINI_THINKING_LABELS[level], level)
    index = box.findData(want)
    box.setCurrentIndex(index if index >= 0 else 0)
    box.blockSignals(False)
