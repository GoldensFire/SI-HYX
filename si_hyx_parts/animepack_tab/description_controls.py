"""Controls for Shikimori description questions with optional speech."""
from __future__ import annotations

import animepack_tab as api
from si_hyx_parts.animepack.description_gemini_tts import TTS_MODELS


def build_controls(tab):
    tab.chk_description_audio = api.QCheckBox("Описание")
    tab.chk_description_audio.setToolTip(
        "Описание берётся с Shikimori, Gemini переводит его на выбранный язык, "
        "озвучку можно включить отдельно. Название аниме остаётся ответом.")
    tab.chk_description_voice = api.QCheckBox("Озвучить описание")
    tab.chk_description_voice.setChecked(True)
    tab.description_language_box = api.QWidget()
    languages_grid = api.QGridLayout(tab.description_language_box)
    languages_grid.setContentsMargins(0, 0, 0, 0)
    tab.description_language_checks = {}
    for index, (label, code) in enumerate((
            ("Английский", "en"), ("Украинский", "uk"),
            ("Казахский", "kk"), ("Русский", "ru"),
            ("Японский", "ja"), ("Немецкий", "de"),
            ("Французский", "fr"), ("Испанский", "es"))):
        check = api.QCheckBox(label)
        check.setChecked(code == "en")
        check.toggled.connect(lambda _value: _keep_one_language(tab))
        languages_grid.addWidget(check, index // 2, index % 2)
        tab.description_language_checks[code] = check
    tab.description_language_box.setToolTip(
        "Для каждого вопроса случайно выбирается один из отмеченных языков. "
        "Google Cloud доступен для английского и украинского; остальные "
        "языки озвучивают Gemini или ElevenLabs.")
    tab.cb_description_tts_first = api.QComboBox()
    tab.cb_description_tts_first.addItem("Сначала Gemini", "gemini")
    tab.cb_description_tts_first.addItem("Сначала Google Cloud", "google")
    tab.cb_description_tts_first.addItem("Сначала ElevenLabs", "elevenlabs")
    tab.cb_description_gemini_model = api.QComboBox()
    for model in TTS_MODELS:
        tab.cb_description_gemini_model.addItem(model, model)
    tab.cb_description_gemini_model.setToolTip(
        "Доступность моделей зависит от квоты вашего ключа Gemini.")
    tab.btn_elevenlabs_key = tab._api_key_button("elevenlabs", "Ключ ElevenLabs")
    tab.ed_elevenlabs_voice = api.QLineEdit()
    tab.ed_elevenlabs_voice.setPlaceholderText("ID голоса ElevenLabs")
    tab.ed_elevenlabs_voice.setText("JBFqnCBsd6RMkjVDRZzb")
    tab.ed_google_tts_credentials = api.QLineEdit()
    tab.ed_google_tts_credentials.setPlaceholderText(
        "Путь к service account JSON (пусто — Google ADC)")
    tab.box_description_audio = api.SettingsBox()
    grid = api.QGridLayout(tab.box_description_audio)
    grid.setContentsMargins(16, 0, 0, 0)
    grid.setHorizontalSpacing(8)
    grid.setVerticalSpacing(6)
    for row, (label, widget) in enumerate((
            ("Языки", tab.description_language_box),
            ("", tab.chk_description_voice),
            ("Приоритет озвучки", tab.cb_description_tts_first),
            ("Модель Gemini TTS", tab.cb_description_gemini_model),
            ("ElevenLabs", tab.btn_elevenlabs_key),
            ("ID голоса", tab.ed_elevenlabs_voice),
            ("Google Cloud", tab.ed_google_tts_credentials))):
        grid.addWidget(tab._lab(label), row, 0)
        grid.addWidget(widget, row, 1)
    grid.setColumnStretch(1, 1)
    tab.box_description_audio.setVisible(False)
    tab.chk_description_audio.toggled.connect(
        lambda value: _toggle(tab, value))
    tab.chk_description_voice.toggled.connect(
        lambda value: _toggle_voice(tab, value))


def _keep_one_language(tab):
    checks = tab.description_language_checks
    if checks and not any(check.isChecked() for check in checks.values()):
        checks["en"].setChecked(True)


def _toggle_voice(tab, enabled):
    for widget in (tab.cb_description_tts_first, tab.cb_description_gemini_model,
                   tab.btn_elevenlabs_key, tab.ed_elevenlabs_voice,
                   tab.ed_google_tts_credentials):
        widget.setEnabled(bool(enabled))


def _toggle(tab, enabled):
    tab.box_description_audio.setVisible(bool(enabled))
    from .composition_controls import toggle
    toggle(tab, "description_audio", enabled)


def collect(tab, settings):
    settings.pack_description_audio = tab.chk_description_audio.isChecked()
    settings.pct_description_audio = tab.mix.shares()["description_audio"]
    settings.description_languages = [
        code for code, check in tab.description_language_checks.items()
        if check.isChecked()]
    settings.description_language = settings.description_languages[0]
    settings.description_voice_enabled = tab.chk_description_voice.isChecked()
    settings.description_tts_first = tab.cb_description_tts_first.currentData() or "gemini"
    settings.description_gemini_tts_model = tab.cb_description_gemini_model.currentData()
    settings.elevenlabs_key = tab._api_key("elevenlabs")
    settings.elevenlabs_voice = tab.ed_elevenlabs_voice.text().strip()
    settings.google_tts_credentials = tab.ed_google_tts_credentials.text().strip()


def apply(tab, settings):
    tab.chk_description_audio.setChecked(bool(settings.pack_description_audio))
    tab.chk_description_voice.setChecked(bool(settings.description_voice_enabled))
    _toggle_voice(tab, tab.chk_description_voice.isChecked())
    tab.mix._set_part("description_audio", tab.chk_description_audio.isChecked())
    selected = set(settings.description_languages or [settings.description_language])
    for code, check in tab.description_language_checks.items():
        check.blockSignals(True)
        check.setChecked(code in selected)
        check.blockSignals(False)
    _keep_one_language(tab)
    index = tab.cb_description_tts_first.findData(settings.description_tts_first)
    tab.cb_description_tts_first.setCurrentIndex(index if index >= 0 else 0)
    tab.ed_elevenlabs_voice.setText(settings.elevenlabs_voice)
    model = settings.description_gemini_tts_model
    index = tab.cb_description_gemini_model.findData(model)
    tab.cb_description_gemini_model.setCurrentIndex(index if index >= 0 else 0)
    tab.ed_google_tts_credentials.setText(settings.google_tts_credentials)
    tab._migrate_api_key("elevenlabs", settings.elevenlabs_key)
