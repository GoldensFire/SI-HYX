# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Controls for Cloudflare anime art questions."""
from __future__ import annotations

import animepack_tab as _api
from cloudflare_art_api import DEFAULT_MODEL, MODELS, MODEL_HINTS


def build_controls(tab):
    tab.chk_ai_art = _api.QCheckBox("ИИ-арты")
    tab.chk_ai_art.setToolTip(
        "Добавляет вопросы с артом по названию аниме. Тайтлы выбираются "
        "случайно из выбранной базы или списков с учётом фильтров пака. "
        "Только ТВ-сериалы, только первый сезон. "
        "В ответе — исходное название аниме.")
    tab.box_ai_art = _api.SettingsBox()
    layout = _api.QGridLayout(tab.box_ai_art)
    layout.setContentsMargins(16, 0, 0, 0)
    layout.setHorizontalSpacing(8)
    layout.setVerticalSpacing(6)
    tab.cb_cloudflare_model = _api.QComboBox()
    for model, label in MODELS.items():
        tab.cb_cloudflare_model.addItem(label, model)
    tab.btn_cloudflare_key = tab._api_key_button("cloudflare", "Токен Cloudflare")
    tab.btn_cloudflare_key.setToolTip(
        "Открыть Настройки → Ключи API: введите Account ID и токен Cloudflare.")
    tab.lbl_cloudflare_model = tab._hint(MODEL_HINTS[DEFAULT_MODEL])
    layout.addWidget(tab._lab("Cloudflare"), 0, 0)
    layout.addWidget(tab.btn_cloudflare_key, 0, 1)
    layout.addWidget(tab._lab("Модель"), 1, 0)
    layout.addWidget(tab.cb_cloudflare_model, 1, 1)
    layout.addWidget(tab.lbl_cloudflare_model, 2, 0, 1, 2)
    from si_hyx_parts.animepack_tab.ai_quota_controls import build_quota_controls
    build_quota_controls(tab, layout)
    layout.setColumnStretch(1, 1)
    tab.box_ai_art.setVisible(False)
    tab.chk_ai_art.toggled.connect(lambda checked: toggle_controls(tab, checked))
    tab.cb_cloudflare_model.currentIndexChanged.connect(
        lambda *_: refresh_model_hint(tab))


def toggle_controls(tab, checked):
    tab.box_ai_art.setVisible(checked)
    tab.mix.set_ai_art(checked)
    tab._refresh_song_opts()


def refresh_model_hint(tab):
    tab.lbl_cloudflare_model.setText(MODEL_HINTS.get(tab.cb_cloudflare_model.currentData(), ""))
    tab._fit_settings_width()


def apply_controls(tab, settings):
    index = tab.cb_cloudflare_model.findData(settings.cloudflare_model)
    tab.cb_cloudflare_model.setCurrentIndex(max(0, index))
    tab._migrate_api_key("cloudflare", settings.cloudflare_token)
    tab._migrate_api_key("cloudflare_account_id", settings.cloudflare_account_id)
