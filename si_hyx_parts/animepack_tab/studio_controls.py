# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Настройки вопроса-студии: три аниме и время показа каждого кадра."""
from __future__ import annotations

import animepack_tab as _api


def build_controls(tab):
    tab.chk_studio = _api.QCheckBox("Студия")
    tab.chk_studio.setToolTip(
        "Вопрос — три кадра из трёх разных аниме одной студии. Назвать нужно "
        "только СТУДИЮ. Надпись «Назовите студию» висит на экране "
        "одновременно с кадрами.\n"
        "Стоит такой вопрос столько же, сколько обычный вопрос-кадр по тому "
        "же аниме.")
    tab.box_studio = _api.SettingsBox()
    layout = _api.QGridLayout(tab.box_studio)
    layout.setContentsMargins(16, 0, 0, 0)
    layout.setHorizontalSpacing(8)
    tab.sp_studio_seconds = _api.QSpinBox()
    tab.sp_studio_seconds.setRange(1, _api.STUDIO_SECONDS_MAX)
    tab.sp_studio_seconds.setValue(_api.STUDIO_FRAME_SECONDS)
    tab.sp_studio_seconds.setSuffix(" с")
    tab.sp_studio_seconds.setToolTip(
        "Сколько секунд висит КАЖДЫЙ кадр. Три кадра по пять секунд — это "
        "пятнадцать секунд вопроса.")
    layout.addWidget(tab._lab("Секунд на кадр"), 0, 0)
    layout.addWidget(tab.sp_studio_seconds, 0, 1)
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
    settings.studio_seconds = tab.sp_studio_seconds.value()


def apply_controls(tab, settings):
    tab.sp_studio_seconds.setValue(max(1, min(
        _api.STUDIO_SECONDS_MAX,
        int(getattr(settings, "studio_seconds", _api.STUDIO_FRAME_SECONDS)
            or _api.STUDIO_FRAME_SECONDS))))
