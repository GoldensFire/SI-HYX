# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Настройки вопроса-студии: три аниме и время показа каждого кадра."""
from __future__ import annotations

import animepack_tab as _api


def build_controls(tab):
    tab.chk_studio = _api.QCheckBox("Студия")
    tab.chk_studio.setToolTip(
        "Вопрос — три кадра из трёх разных аниме одной студии. Назвать нужно "
        "только СТУДИЮ. Перед каждым кадром надпись «Назовите студию» "
        "показывается 1 секунду, затем кадр — 4 секунды.\n"
        "Стоит такой вопрос столько же, сколько обычный вопрос-кадр по тому "
        "же аниме.")
    tab.box_studio = _api.SettingsBox()
    layout = _api.QGridLayout(tab.box_studio)
    layout.setContentsMargins(16, 0, 0, 0)
    layout.setHorizontalSpacing(8)
    layout.addWidget(tab._lab("Надпись — 1 с, каждый кадр — 4 с"), 0, 0, 1, 2)
    layout.setColumnStretch(1, 1)
    tab.box_studio.setVisible(False)
    tab.chk_studio.toggled.connect(lambda value: toggle(tab, value))


def toggle(tab, checked):
    tab.box_studio.setVisible(checked)
    tab.mix.set_studio(checked)
    tab._refresh_song_opts()


def collect(tab, settings):
    settings.pack_studio = tab.chk_studio.isChecked()
    settings.pct_studio = tab.mix.shares()["studio"]
    settings.studio_frames = _api.STUDIO_FRAMES
    settings.studio_seconds = _api.STUDIO_FRAME_SECONDS


def apply_controls(tab, settings):
    settings.studio_seconds = _api.STUDIO_FRAME_SECONDS
