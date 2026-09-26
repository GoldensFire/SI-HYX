# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Controls for Sakugabooru animation-cut questions."""
from __future__ import annotations

import animepack_tab as _api


def build_controls(tab):
    tab.chk_sakuga = _api.QCheckBox("Сакуга")
    tab.chk_sakuga.setToolTip(
        "Вопрос — вырезка самой анимации с Sakugabooru: несколько секунд без "
        "звука, титров и названия в кадре. Угадывают тайтл по рисовке и "
        "движению.")
    tab.box_sakuga = _api.SettingsBox()
    layout = _api.QGridLayout(tab.box_sakuga)
    layout.setContentsMargins(16, 0, 0, 0)
    layout.setHorizontalSpacing(8)
    tab.sp_sakuga_cut = _api.QSpinBox()
    tab.sp_sakuga_cut.setRange(2, _api.SAKUGA_MAX_CUT)
    tab.sp_sakuga_cut.setValue(_api.SAKUGA_CUT)
    tab.sp_sakuga_cut.setSuffix(" с")
    tab.sp_sakuga_cut.setToolTip(
        "Сколько секунд отрывка попадёт в вопрос. Вырезка режется с начала: "
        "там ровно та сцена, ради которой её и выложили. Дольше двадцати "
        "секунд отрывок в вопрос не идёт — всё лишнее обрезается.")
    layout.addWidget(tab._lab("Длина отрывка"), 0, 0)
    layout.addWidget(tab.sp_sakuga_cut, 0, 1)
    tab.chk_sakuga_safe = _api.QCheckBox("Только метка «safe»")
    tab.chk_sakuga_safe.setChecked(True)
    tab.chk_sakuga_safe.setToolTip(
        "Снятая галочка пускает и вырезки с меткой «questionable» — это драки "
        "и кровь, но не порно: его на Sakugabooru нет вовсе.")
    # Скорость кодирования у сакуги своя, отдельно от вопросов-роликов
    # (просьба пользователя): вырезок в паке бывает два десятка, и время на
    # них уходит заметное — а качество короткого отрывка простительно хуже.
    tab.sp_sakuga_preset = _api.QSpinBox()
    tab.sp_sakuga_preset.setRange(0, 13)
    tab.sp_sakuga_preset.setValue(_api.VIDEO_PRESET)
    tab.sp_sakuga_preset.setMinimumWidth(44)
    tab.sp_sakuga_preset.setToolTip(
        "Пресет libsvtav1 для ВЫРЕЗОК: 13 — самый быстрый, 0 — самый "
        "медленный и качественный. Считается отдельно от пресета "
        "вопросов-роликов: сакуги в паке много, и она заметная часть времени "
        "генерации.\n"
        "CRF у вырезки общий с роликами.")
    layout.addWidget(tab._lab("Пресет кодирования"), 1, 0)
    layout.addWidget(tab.sp_sakuga_preset, 1, 1)
    layout.addWidget(tab.chk_sakuga_safe, 2, 0, 1, 2)
    layout.setColumnStretch(1, 1)
    tab.box_sakuga.setVisible(False)
    tab.chk_sakuga.toggled.connect(lambda value: toggle(tab, value))


def toggle(tab, checked):
    tab.box_sakuga.setVisible(checked)
    tab.mix.set_sakuga(checked)
    tab._refresh_song_opts()


def collect(tab, settings):
    settings.pack_sakuga = tab.chk_sakuga.isChecked()
    settings.pct_sakuga = tab.mix.shares()["sakuga"]
    settings.sakuga_cut = tab.sp_sakuga_cut.value()
    settings.sakuga_safe_only = tab.chk_sakuga_safe.isChecked()
    settings.sakuga_preset = tab.sp_sakuga_preset.value()


def apply_controls(tab, settings):
    tab.sp_sakuga_cut.setValue(max(2, min(_api.SAKUGA_MAX_CUT,
                                          int(settings.sakuga_cut
                                              or _api.SAKUGA_CUT))))
    tab.chk_sakuga_safe.setChecked(bool(settings.sakuga_safe_only))
    tab.sp_sakuga_preset.setValue(max(0, min(13, int(
        getattr(settings, "sakuga_preset", _api.VIDEO_PRESET)))))
