# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Настройки Chiptune внутри панели музыки. Namespace: animepack_tab.

Коробка с настройками показывается ТОЛЬКО при включённой галочке — ровно как у
каверов (просьба пользователя): полтора десятка полей, из которых ни одно не
работает без Chiptune, занимали пол-экрана настроек и разъезжались с подписями
в узкой колонке.
"""
import animepack_tab as _api

LEAD_TIP = ("Какую партию превращать в ноты. «Авто» сперва пробует вокал, а "
            "без него берёт инструментальную.")
PERCENT_TIP = ("Сколько песенных вопросов прозвучит синтезатором вместо "
               "оригинальной записи.")
SEED_TIP = ("Зерно случайности: при одном и том же зерне выбор песен под "
            "Chiptune повторяется от пака к паку.")
PYTHON_TIP = ("Свой Python для обработчика. Пусто — тот, который программа "
              "установила сама.")


def build_controls(tab):
    """Галочка Chiptune и её коробка настроек (скрыта, пока она снята)."""
    box = _api.SettingsBox()
    grid = _api.QGridLayout(box)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(8)
    grid.setVerticalSpacing(6)
    tab.chk_chiptune = _api.QCheckBox("Chiptune (не работает)")
    tab.chk_chiptune.setToolTip(
        "Вокал превращается в ноты и звучит простым синтезатором. "
        "Плохой результат заменяется другим кандидатом. Обработка медленная.")
    grid.addWidget(tab.chk_chiptune, 0, 0, 1, 2)

    tab.box_chiptune = _api.SettingsBox()
    inner = _api.QGridLayout(tab.box_chiptune)
    inner.setContentsMargins(16, 0, 0, 0)
    inner.setHorizontalSpacing(8)
    inner.setVerticalSpacing(6)
    tab.sp_chiptune_percent = _api.QSpinBox()
    tab.sp_chiptune_percent.setRange(1, 100)
    tab.sp_chiptune_percent.setSuffix(" % аудиовопросов")
    tab.sp_chiptune_percent.setValue(25)
    tab.sp_chiptune_percent.setToolTip(PERCENT_TIP)
    tab.sp_chiptune_percent.hide()
    tab.sp_chiptune_seed = _api.QSpinBox()
    tab.sp_chiptune_seed.setRange(0, 2147483647)
    tab.sp_chiptune_seed.setToolTip(SEED_TIP)
    inner.addWidget(tab._lab("Случайное зерно"), 1, 0)
    inner.addWidget(tab.sp_chiptune_seed, 1, 1)
    tab.cb_chiptune_lead = _api.QComboBox()
    tab.cb_chiptune_lead.setToolTip(LEAD_TIP)
    for label, key in (("Авто: сначала вокальная мелодия", "auto"),
                       ("Мелодия вокала", "vocals"),
                       ("Инструментальная партия (OST)", "other")):
        tab.cb_chiptune_lead.addItem(label, key)
    inner.addWidget(tab._lab("Партия"), 2, 0)
    inner.addWidget(tab.cb_chiptune_lead, 2, 1)
    for row, name, label, value, upper in ((3, "lead", "Громкость мелодии", 85, 100),
                                           (4, "bass", "Громкость баса", 25, 70)):
        spin = _api.QSpinBox()
        spin.setRange(1 if name == "lead" else 0, upper)
        spin.setValue(value)
        spin.setSuffix(" %")
        setattr(tab, f"sp_chiptune_{name}_volume", spin)
        inner.addWidget(tab._lab(label), row, 0)
        inner.addWidget(spin, row, 1)
    tab.ed_chiptune_python = _api.QLineEdit()
    tab.ed_chiptune_python.setPlaceholderText("пусто — установленный автоматически")
    tab.ed_chiptune_python.setToolTip(PYTHON_TIP)
    inner.addWidget(tab._lab("Python обработчика"), 5, 0)
    inner.addWidget(tab.ed_chiptune_python, 5, 1)
    preview = _api.QPushButton("Прослушать оригинал / Chiptune…")
    preview.clicked.connect(lambda: open_preview(tab))
    inner.addWidget(preview, 6, 0, 1, 2)
    inner.addWidget(tab._hint(
        "В прослушивании можно установить модели и проверить свой файл. "
        "Одновременно работает один обработчик. Бас добавляется только при "
        "уверенном распознавании."), 7, 0, 1, 2)
    inner.setColumnStretch(1, 1)
    grid.addWidget(tab.box_chiptune, 1, 0, 1, 2)
    grid.setColumnStretch(1, 1)
    tab.chk_chiptune.toggled.connect(lambda _=None: refresh(tab))
    tab._chiptune_version = "chiptune-2"
    refresh(tab)
    return box


def refresh(tab):
    """Настройки Chiptune видны, только пока он включён."""
    box = getattr(tab, "box_chiptune", None)
    if box is not None:
        box.setVisible(bool(tab.chk_chiptune.isChecked()))
    if getattr(tab, "settings_columns", None) is not None:
        tab._fit_settings_width()


def collect_controls(tab, settings):
    settings.chiptune_enabled = tab.chk_chiptune.isChecked()
    settings.chiptune_percent = tab.sp_chiptune_percent.value()
    settings.chiptune_seed = tab.sp_chiptune_seed.value()
    settings.chiptune_lead = tab.cb_chiptune_lead.currentData()
    settings.chiptune_lead_volume = tab.sp_chiptune_lead_volume.value()
    settings.chiptune_bass_volume = tab.sp_chiptune_bass_volume.value()
    settings.chiptune_python = tab.ed_chiptune_python.text().strip()
    settings.chiptune_version = tab._chiptune_version


def apply_controls(tab, settings):
    tab.chk_chiptune.setChecked(settings.chiptune_enabled)
    refresh(tab)
    tab.sp_chiptune_percent.setValue(settings.chiptune_percent)
    tab.sp_chiptune_seed.setValue(settings.chiptune_seed)
    tab.cb_chiptune_lead.setCurrentIndex(max(0, tab.cb_chiptune_lead.findData(settings.chiptune_lead)))
    tab.sp_chiptune_lead_volume.setValue(settings.chiptune_lead_volume)
    tab.sp_chiptune_bass_volume.setValue(settings.chiptune_bass_volume)
    tab.ed_chiptune_python.setText(settings.chiptune_python)
    tab._chiptune_version = settings.chiptune_version


def open_preview(tab):
    from .music_preview import MusicPreview
    dialog = MusicPreview(tab.collect(), tab)
    dialog.exec()
    if dialog.installed_python:
        tab.ed_chiptune_python.setText(dialog.installed_python)
