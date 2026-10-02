# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Selectable page readers, independent of the title catalogue."""
import animepack_tab as _api
from si_hyx_parts.animepack_api.manga_reader_base import SOURCE_LABELS, clean_sources


def build_controls(tab, grid, row):
    cell = _api.SettingsBox()
    layout = _api.QGridLayout(cell)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(_api.QLabel("Источники страниц"), 0, 0, 1, 2)
    tab.chk_manga_sources = {}
    for index, (key, label) in enumerate(SOURCE_LABELS.items()):
        checkbox = _api.QCheckBox(label)
        checkbox.setChecked(True)
        checkbox.setToolTip(
            "При автоматическом выборе сначала ReManga и MangaLib, затем "
            "русские страницы других сайтов, после них английские и украинские. "
            "Если страницы не нашлись или сайт недоступен, проверяется следующий источник. "
            "Comix.to и WeebCentral дают английские главы. MangaFire "
            "поддерживает несколько языков. ReManga и MangaLib дают доступные бесплатные "
            "русские главы. Явно выбранный язык сохраняется.")
        checkbox.toggled.connect(tab._recount)
        saver = getattr(getattr(tab, "main", None), "_save_settings_soon", None)
        if saver:
            checkbox.toggled.connect(saver)
        layout.addWidget(checkbox, 1 + index // 2, index % 2)
        tab.chk_manga_sources[key] = checkbox
    grid.addWidget(cell, row, 0, 1, 4)


def apply_controls(tab, settings):
    values = clean_sources(getattr(settings, "manga_sources", None))
    for key, checkbox in tab.chk_manga_sources.items():
        checkbox.setChecked(values[key])


def collect(tab, settings):
    settings.manga_sources = {key: checkbox.isChecked()
                              for key, checkbox in tab.chk_manga_sources.items()}
