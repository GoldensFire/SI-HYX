# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""AnimeThemes video as an optional presentation of song questions."""
import animepack_tab as api


def build_controls(tab):
    tab.chk_video = api.QCheckBox("Опенинги с видеорядом")
    tab.chk_video.setToolTip(
        "Вместо аудио оригинального опенинга или эндинга показывать ролик "
        "с AnimeThemes. Доля песен и соотношение опенингов, эндингов и OST "
        "сохраняются. Доля задаётся на общей полосе способов подачи песен. "
        "OST, каверы, Chiptune и караоке используют свой звук.\n"
        "Если ролика нет или загрузка не удалась, играет аудио песни. "
        "Фактическое число готовых роликов выводится в журнале.")
    tab.chk_video.toggled.connect(tab._on_video_toggled)
    tab.sp_video_cut = api.QSpinBox()
    tab.sp_video_cut.setRange(3, 90)
    tab.sp_video_cut.setValue(api.VIDEO_CUT)
    tab.sp_video_cut.setSuffix(" с")
    tab.sp_video_cut.setMinimumWidth(64)
    tab.sp_video_cut.setToolTip("Длина ролика в вопросе.")
    tab.sp_video_crf = api.QSpinBox()
    tab.sp_video_crf.setRange(0, 63)
    tab.sp_video_crf.setValue(api.VIDEO_CRF)
    tab.sp_video_crf.setMinimumWidth(44)
    tab.sp_video_crf.setToolTip(
        "CRF libsvtav1: меньше — качественнее и тяжелее. "
        "45 — заметно сжато, зато пак не раздувается.")
    tab.sp_video_preset = api.QSpinBox()
    tab.sp_video_preset.setRange(0, 13)
    tab.sp_video_preset.setValue(api.VIDEO_PRESET)
    tab.sp_video_preset.setMinimumWidth(44)
    tab.sp_video_preset.setToolTip(
        "Пресет libsvtav1: 13 — самый быстрый, "
        "0 — самый медленный и качественный.")
    tab.box_video_opts = api.SettingsBox()
    grid = api.QGridLayout(tab.box_video_opts)
    grid.setContentsMargins(16, 0, 0, 0)
    grid.setHorizontalSpacing(8)
    grid.setVerticalSpacing(6)
    for row, label, control in (
            (0, "Длина ролика", tab.sp_video_cut),
            (1, "CRF", tab.sp_video_crf),
            (2, "Пресет", tab.sp_video_preset)):
        grid.addWidget(tab._lab(label), row, 0)
        grid.addWidget(control, row, 1)
    grid.setColumnStretch(1, 1)
    tab.box_video_opts.hide()


def migrate_settings(settings):
    """Merge the former video share into songs, retaining explicit selection."""
    if settings.song_video:
        settings.pct_songs += max(0, settings.pct_videos)
    settings.pct_videos = 0
    enabled = settings.composition_enabled
    if enabled is not None and "video" in enabled:
        settings.composition_enabled = [key for key in enabled if key != "video"]
        if settings.song_video and "songs" not in settings.composition_enabled:
            settings.composition_enabled.append("songs")
