# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Всё про музыку — одной коробкой под галочкой «Песни». Namespace: animepack_tab.

Раньше эти настройки жили в группе «Прочее», в самом низу панели: длина
отрезка, коллаж поверх песни, подсказка о типе, сжатие дорожки, Chiptune и
каверы. До них приходилось листать через состав пака целиком, хотя относятся
они ровно к одному роду вопросов. Теперь коробка стоит там же, где настройки
всех остальных родов, — прямо под своей галочкой (просьба пользователя).

Коробка та же самая (`box_audio_opts`), и имена полей не поменялись: их читают
и сохранение настроек, и тесты. Переехало только место сборки — из
`_group_other` сюда, потому что группа «Состав пака» строится ПЕРВОЙ, а
`box_song_opts` существует только в ней.
"""
from __future__ import annotations

import animepack_tab as _api

CUT_TIP = ("Сколько секунд песни играет в вопросе. Таймера на экране у "
           "дорожки нет: отрезок просто доигрывает до конца.")
COMPRESS_TIP = ("Включено — отрезок песни кодируется как во вкладке "
                "«Обработка»: opus 192 кбит, нормализация громкости (−20 "
                "LUFS, LRA 11, TP −1.5) и затухание за секунду до конца.\n"
                "Выключено — отрезок просто вырезается из скачанного файла "
                "без перекодирования: качество ровно то, что отдал сервер "
                "AMQ, но громкость у вопросов будет разная и пак весит "
                "больше.\n"
                "Chiptune: включено — MP3 192 кбит; выключено — "
                "синтезированный WAV.")


def build_controls(tab):
    """Собирает `tab.box_audio_opts` и возвращает её."""
    tab.sp_cut = _api.QSpinBox()
    tab.sp_cut.setRange(5, 60)
    tab.sp_cut.setValue(20)
    tab.sp_cut.setSuffix(" с")
    tab.sp_cut.setMinimumWidth(64)
    tab.sp_cut.setToolTip(CUT_TIP)

    tab.chk_images = _api.QCheckBox("Скриншоты в вопросе за")
    tab.chk_images.setToolTip(
        "Коллаж 2×2 из случайных кадров аниме появляется поверх играющей "
        "песни за указанное число секунд до конца.")
    tab.sp_images_time = _api.QSpinBox()
    tab.sp_images_time.setRange(1, 30)
    tab.sp_images_time.setValue(7)
    tab.sp_images_time.setSuffix(" с")
    tab.sp_images_time.setMinimumWidth(64)

    # Галочки «Подсказка: тип песни» здесь больше нет: подсказка есть ВСЕГДА
    # (просьба пользователя). Пока играет песня, на экране висит «Опенинг»,
    # «Эндинг» или «OST», а у кавера — ещё и что именно звучит («Опенинг
    # (кавер на фортепиано)»). Поле hint в PackSettings осталось — его читает
    # сборка content.xml, и collect() всегда ставит его включённым.
    #
    # «Сжимать аудио» уехало в группу «Прочее», к «Сжимать картинки» (просьба
    # пользователя): обе галочки про одно и то же — вес пака. Подсказка к ней
    # (COMPRESS_TIP) осталась здесь: она про звук вопроса-песни.

    tab.box_audio_opts = _api.SettingsBox()
    grid = _api.QGridLayout(tab.box_audio_opts)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(8)
    grid.setVerticalSpacing(8)
    grid.addWidget(tab._lab("Отрезок песни"), 0, 0)
    grid.addWidget(tab.sp_cut, 0, 1, 1, 3)
    grid.addWidget(tab.chk_images, 1, 0, 1, 3)
    grid.addWidget(tab.sp_images_time, 1, 3)
    from .music_effect_controls import build_controls as build_chiptune
    grid.addWidget(build_chiptune(tab), 2, 0, 1, 4)
    from .cover_controls import build_controls as build_cover
    grid.addWidget(build_cover(tab), 3, 0, 1, 4)
    for column in (1, 3):
        grid.setColumnStretch(column, 1)
    return tab.box_audio_opts
