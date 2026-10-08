# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Настройки вопроса-студии: три аниме и время показа каждого кадра."""
from __future__ import annotations

import animepack_tab as _api


def build_controls(tab):
    tab.chk_studio = _api.QCheckBox("Студия")
    tab.chk_studio.setToolTip(
        "Вопрос — три кадра из трёх разных аниме одной студии. Назвать нужно "
        "только СТУДИЮ. Каждый кадр показывается 4 секунды вместе с надписью "
        "«Назовите студию». Gemini выбирает только кадры с персонажами "
        "и без видимого названия аниме. Нужен ключ Gemini.")
    tab.box_studio = _api.SettingsBox()
    tab.box_studio.setVisible(False)
    tab.chk_studio.toggled.connect(lambda value: toggle(tab, value))


def toggle(tab, checked):
    tab.mix.set_studio(checked)
    tab._refresh_song_opts()


def collect(tab, settings):
    settings.pack_studio = tab.chk_studio.isChecked()
    settings.pct_studio = tab.mix.shares()["studio"]
    settings.studio_frames = _api.STUDIO_FRAMES
    settings.studio_seconds = _api.STUDIO_FRAME_SECONDS


def apply_controls(tab, settings):
    settings.studio_seconds = _api.STUDIO_FRAME_SECONDS
