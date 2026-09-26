# -*- coding: utf-8 -*-
"""Настройки вопросов по настоящим диалогам: SubDL, затем Jimaku."""
from __future__ import annotations

import animepack_tab as _api


def build_controls(tab):
    tab.chk_dialogue = _api.QCheckBox("Диалоги из аниме")
    tab.chk_dialogue.setToolTip(
        "Добавляет короткие диалоги из настоящих субтитров. Gemini читает "
        "серию целиком и выбирает отрывок, по которому узнаётся именно это "
        "аниме, — без названия и имён. Сначала берутся русские субтитры "
        "SubDL; когда суточная квота SubDL кончится, дальше идут субтитры "
        "Jimaku, которые Gemini ещё и переводит. Каждая серия стоит одного "
        "запроса Gemini. Тайтл связывается только по "
        "точным IMDb/TMDB/AniList ID, сборники серий, OCR и "
        "AI/Whisper-субтитры не берутся. Ответ — название аниме; ведущий "
        "произносит только «Серия N».")
    tab.btn_subdl_key = tab._api_key_button("subdl", "Ключ SubDL")
    tab.btn_jimaku_key = tab._api_key_button("jimaku", "Ключ Jimaku")
    tab.box_dialogue = _api.SettingsBox()
    grid = _api.QGridLayout(tab.box_dialogue)
    grid.setContentsMargins(16, 0, 0, 0)
    grid.setHorizontalSpacing(8)
    grid.setVerticalSpacing(6)
    grid.addWidget(tab._lab("Ключ SubDL"), 0, 0)
    grid.addWidget(tab.btn_subdl_key, 0, 1)
    grid.addWidget(tab._lab("Ключ Jimaku"), 1, 0)
    grid.addWidget(tab.btn_jimaku_key, 1, 1)
    note = tab._hint(
        "Отрывок выбирает Gemini, прочитав всю серию: только то, что "
        "узнаётся в этом аниме. SubDL идёт первым: субтитры уже русские. "
        "Jimaku — запасной, после квоты SubDL: его реплики модель Gemini ещё "
        "и переводит, а перевод сверяется построчно.")
    grid.addWidget(note, 2, 0, 1, 2)
    grid.setColumnStretch(1, 1)
    tab.box_dialogue.setVisible(False)
    tab.chk_dialogue.toggled.connect(
        lambda value: _toggle(tab, value))


def _toggle(tab, value):
    tab.box_dialogue.setVisible(bool(value))
    from .composition_controls import toggle
    toggle(tab, "dialogue", value)


def collect(tab, settings):
    settings.pack_dialogue = tab.chk_dialogue.isChecked()
    settings.pct_dialogue = tab.mix.shares()["dialogue"]
    settings.jimaku_key = tab._api_key("jimaku")
    settings.subdl_key = tab._api_key("subdl")


def apply(tab, settings):
    tab.chk_dialogue.setChecked(bool(getattr(settings, "pack_dialogue", False)))
    tab.mix.set_dialogue(tab.chk_dialogue.isChecked())
    tab._migrate_api_key("jimaku", getattr(settings, "jimaku_key", ""))
    tab._migrate_api_key("subdl", getattr(settings, "subdl_key", ""))
