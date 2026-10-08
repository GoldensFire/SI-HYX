"""Karaoke options beside chiptune and cover presentation shares."""
from __future__ import annotations

import animepack_tab as ap
from karaoke.render import EFFECT_LABELS


def build_controls(tab):
    box = ap.SettingsBox()
    grid = ap.QGridLayout(box)
    grid.setContentsMargins(0, 0, 0, 0)
    tab.chk_karaoke = ap.QCheckBox("Караоке — romaji с подсветкой")
    tab.chk_karaoke.setToolTip(
        "OP, ED и OST становятся видео с пословной или послоговой подсветкой. "
        "Перевод включается отдельной галочкой. Версия песни проверяется по аудио.")
    grid.addWidget(tab.chk_karaoke, 0, 0, 1, 2)
    tab.box_karaoke = ap.SettingsBox()
    inner = ap.QGridLayout(tab.box_karaoke)
    inner.setContentsMargins(16, 0, 0, 0)
    tab.sp_karaoke_percent = ap.QSpinBox()
    tab.sp_karaoke_percent.setRange(1, 100)
    tab.sp_karaoke_percent.setValue(25)
    tab.sp_karaoke_percent.setSuffix(" % песен")
    tab.sp_karaoke_percent.hide()
    tab.chk_karaoke_translations = ap.QCheckBox("Показывать перевод — RU, иначе EN")
    tab.chk_karaoke_translations.setToolTip(
        "По умолчанию только romaji. Перевод показывается при наличии проверенного соответствия строк.")
    tab.chk_karaoke_ai = ap.QCheckBox("Если нет готовых таймингов — распознать вокал")
    tab.chk_karaoke_ai.setChecked(True)
    tab.chk_karaoke_ai.setToolTip(
        "Сначала Karaoke Mugen, затем AMLL TTML. Если подходящих таймингов нет, "
        "текст берётся с AnimeLyrics / AnimeSongLyrics и выравнивается с вокалом. "
        "Обработчик и модели устанавливаются при первом использовании.")
    inner.addWidget(tab.chk_karaoke_ai, 1, 0, 1, 2)
    tab.cb_karaoke_effect = ap.QComboBox()
    for key, label in EFFECT_LABELS.items():
        tab.cb_karaoke_effect.addItem(label, key)
    tab.cb_karaoke_effect.setToolTip(
        "Высота тона, шум и полосовой фильтр сохраняют тайминги. "
        "Темп и обрезка пересчитывают их. Reverse отключает караоке.")
    inner.addWidget(tab._lab("Эффект звука"), 2, 0)
    inner.addWidget(tab.cb_karaoke_effect, 2, 1)
    tab.sp_karaoke_tempo = ap.QDoubleSpinBox()
    tab.sp_karaoke_tempo.setRange(.5, 2)
    tab.sp_karaoke_tempo.setSingleStep(.05)
    tab.sp_karaoke_tempo.setValue(1)
    tab.sp_karaoke_tempo.setSuffix(" ×")
    inner.addWidget(tab._lab("Темп"), 3, 0)
    inner.addWidget(tab.sp_karaoke_tempo, 3, 1)
    tab.sp_karaoke_pitch = ap.QSpinBox()
    tab.sp_karaoke_pitch.setRange(-12, 12)
    tab.sp_karaoke_pitch.setSuffix(" полутонов")
    inner.addWidget(tab._lab("Высота тона"), 4, 0)
    inner.addWidget(tab.sp_karaoke_pitch, 4, 1)
    tab.ed_karaoke_python = ap.QLineEdit()
    tab.ed_karaoke_python.setPlaceholderText("пусто — установить автоматически")
    inner.addWidget(tab._lab("Python обработчика"), 5, 0)
    inner.addWidget(tab.ed_karaoke_python, 5, 1)
    tab.sp_karaoke_crf = ap.QSpinBox()
    tab.sp_karaoke_crf.setRange(0, 63)
    tab.sp_karaoke_crf.setValue(ap.PackSettings().karaoke_crf)
    tab.sp_karaoke_crf.setToolTip("Меньше CRF — выше качество и больше файл.")
    inner.addWidget(tab._lab("Качество караоке (CRF)"), 6, 0)
    inner.addWidget(tab.sp_karaoke_crf, 6, 1)
    tab.sp_karaoke_preset = ap.QSpinBox()
    tab.sp_karaoke_preset.setRange(0, 13)
    tab.sp_karaoke_preset.setValue(ap.PackSettings().karaoke_preset)
    tab.sp_karaoke_preset.setToolTip("Больше пресет — быстрее кодирование, но больше файл при том же CRF.")
    inner.addWidget(tab._lab("Пресет кодирования"), 7, 0)
    inner.addWidget(tab.sp_karaoke_preset, 7, 1)
    inner.addWidget(tab._hint("CRF и пресет действуют только на караоке. "
                             "Готовый ASS/TTML используется без распознавания."), 8, 0, 1, 2)
    inner.addWidget(tab.chk_karaoke_translations, 9, 0, 1, 2)
    tab.sp_karaoke_ai_minutes = ap.QSpinBox()
    tab.sp_karaoke_ai_minutes.setRange(1, 60)
    tab.sp_karaoke_ai_minutes.setValue(5)
    tab.sp_karaoke_ai_minutes.setSuffix(" мин")
    tab.sp_karaoke_ai_minutes.setToolTip(
        "Общий срок ожидания и распознавания одной песни. После него выбирается другая песня.")
    inner.addWidget(tab._lab("Лимит распознавания"), 10, 0)
    inner.addWidget(tab.sp_karaoke_ai_minutes, 10, 1)
    tab.cb_karaoke_separator = ap.QComboBox()
    from karaoke.separator_health import kim_disabled
    disabled_kim = kim_disabled()
    for label, value in (("Автоматически", "auto"), ("Kim", "kim"), ("HTDemucs", "htdemucs")):
        if value == "kim" and disabled_kim:
            continue
        tab.cb_karaoke_separator.addItem(label, value)
    tab.cb_karaoke_separator.setToolTip(
        "На этом компьютере используется HTDemucs: Kim не прошёл проверку памяти."
        if disabled_kim else "Автоматически: Kim на видеокарте, HTDemucs на CPU или после сбоя Kim.")
    inner.addWidget(tab._lab("Разделение вокала"), 11, 0)
    inner.addWidget(tab.cb_karaoke_separator, 11, 1)
    grid.addWidget(tab.box_karaoke, 1, 0, 1, 2)
    inner.setColumnStretch(1, 1)
    grid.setColumnStretch(1, 1)
    tab.chk_karaoke.toggled.connect(lambda _: refresh(tab))
    tab.cb_karaoke_effect.currentIndexChanged.connect(lambda _: refresh(tab))
    tab.chk_karaoke_ai.toggled.connect(lambda _: refresh(tab))
    refresh(tab)
    return box


def refresh(tab):
    tab.box_karaoke.setVisible(tab.chk_karaoke.isChecked())
    effect = tab.cb_karaoke_effect.currentData()
    tab.sp_karaoke_tempo.setEnabled(effect == "tempo")
    tab.sp_karaoke_pitch.setEnabled(effect == "pitch")
    tab.chk_karaoke_ai.setEnabled(effect != "reverse")
    enabled = tab.chk_karaoke_ai.isChecked() and effect != "reverse"
    tab.sp_karaoke_ai_minutes.setEnabled(enabled)
    tab.cb_karaoke_separator.setEnabled(enabled)
    if getattr(tab, "settings_columns", None) is not None:
        tab._fit_settings_width()


def collect_controls(tab, settings):
    settings.karaoke_enabled = tab.chk_karaoke.isChecked()
    settings.karaoke_translations = tab.chk_karaoke_translations.isChecked()
    settings.karaoke_percent = tab.sp_karaoke_percent.value()
    settings.karaoke_ai_fallback = tab.chk_karaoke_ai.isChecked()
    settings.karaoke_ai_timeout = tab.sp_karaoke_ai_minutes.value() * 60
    settings.karaoke_separator = tab.cb_karaoke_separator.currentData() or "auto"
    settings.karaoke_effect = tab.cb_karaoke_effect.currentData() or "original"
    settings.karaoke_tempo = tab.sp_karaoke_tempo.value()
    settings.karaoke_pitch = tab.sp_karaoke_pitch.value()
    settings.karaoke_crf = tab.sp_karaoke_crf.value()
    settings.karaoke_preset = tab.sp_karaoke_preset.value()
    settings.karaoke_python = tab.ed_karaoke_python.text().strip()


def apply_controls(tab, settings):
    tab.chk_karaoke.setChecked(settings.karaoke_enabled)
    tab.chk_karaoke_translations.setChecked(settings.karaoke_translations)
    tab.sp_karaoke_percent.setValue(settings.karaoke_percent)
    tab.chk_karaoke_ai.setChecked(settings.karaoke_ai_fallback)
    tab.sp_karaoke_ai_minutes.setValue(max(1, (settings.karaoke_ai_timeout + 59) // 60))
    tab.cb_karaoke_separator.setCurrentIndex(max(0, tab.cb_karaoke_separator.findData(settings.karaoke_separator)))
    tab.cb_karaoke_effect.setCurrentIndex(max(0, tab.cb_karaoke_effect.findData(settings.karaoke_effect)))
    tab.sp_karaoke_tempo.setValue(settings.karaoke_tempo)
    tab.sp_karaoke_pitch.setValue(settings.karaoke_pitch)
    tab.sp_karaoke_crf.setValue(settings.karaoke_crf)
    tab.sp_karaoke_preset.setValue(settings.karaoke_preset)
    tab.ed_karaoke_python.setText(settings.karaoke_python)
    refresh(tab)
