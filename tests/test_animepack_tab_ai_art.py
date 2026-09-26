# -*- coding: utf-8 -*-
"""Art controls, model selection, proportions and central credentials."""
import pytest

import animepack_tab
from animepack import AI_ART_KIND
from cloudflare_art_api import MODELS
from test_animepack_tab_mix import _FakeMain


@pytest.fixture
def tab(qapp):
    main = _FakeMain(cloudflare="test-token", cloudflare_account_id="a" * 32)
    widget = animepack_tab.AnimePackTab(main_window=main)
    yield widget
    widget.cleanup()


def test_checkbox_adds_art_and_counts_questions(tab):
    assert "ai_art" not in tab.mix.keys()
    tab.chk_ai_art.setChecked(True)
    assert tab.box_ai_art.isVisibleTo(tab)
    assert tab.mix.shares()["ai_art"] > 0
    tab.mix.set_shares({"ai_art": 100})
    tab._on_mix_changed()
    settings = tab.collect()
    assert settings.only_kind == AI_ART_KIND and settings.random_mode
    assert not settings.has_songs
    assert "ИИ-артов" in tab.lbl_left.text()
    assert not tab.box_song_opts.isVisibleTo(tab)
    assert not settings.validate()
    tab.chk_ai_art.setChecked(False)
    assert "ai_art" not in tab.mix.keys() and tab.mix.shares()["songs"] == 100


def test_model_and_mix_survive_reload_without_copying_secrets(tab):
    tab.chk_ai_art.setChecked(True)
    tab.cb_cloudflare_model.setCurrentIndex(1)
    tab.mix.set_shares({"songs": 30, "ai_art": 70})
    data = tab.get_settings()
    assert data["cloudflare_model"] == list(MODELS)[1]
    assert data["pct_ai_art"] == 70 and "ai_art_cache" not in data
    assert "cloudflare_token" not in data and "cloudflare_account_id" not in data
    tab.apply_settings(data)
    settings = tab.collect()
    assert settings.cloudflare_model == list(MODELS)[1]
    assert settings.pct_ai_art == 70 and settings.pack_ai_art
    assert settings.cloudflare_token == "test-token"
    assert not tab.box_ai_art.isHidden()


def test_cleared_global_token_cannot_return_from_tab_settings(tab):
    tab.chk_ai_art.setChecked(True)
    data = tab.get_settings()
    tab.main.set_api_key("cloudflare", "")
    tab.apply_settings(data)
    assert tab.collect().cloudflare_token == ""
    assert any("токен" in problem for problem in tab.collect().validate())


def test_old_settings_leave_art_disabled(tab):
    tab.apply_settings({"pct_songs": 100})
    assert not tab.chk_ai_art.isChecked()
    assert tab.collect().pct_ai_art == 0


def test_quota_refresh_updates_label_without_blocking(tab, monkeypatch):
    import time
    from datetime import datetime, timezone
    from si_hyx_parts.animepack_tab import ai_quota_controls

    monkeypatch.setattr(ai_quota_controls, "fetch_quota", lambda *args: {
        "remaining": 7654, "used": 2346,
        "day": datetime.now(timezone.utc).date().isoformat()})
    tab.btn_ai_quota.click()
    deadline = time.monotonic() + 2
    while not tab.btn_ai_quota.isEnabled() and time.monotonic() < deadline:
        tab._ai_quota_timer.timeout.emit()
        time.sleep(0.005)
    assert "7,654" in tab.lbl_ai_quota.text()
    assert "10 000" in tab.lbl_ai_quota.text()
    tab.cleanup()
    assert not tab._ai_quota_timer.isActive()
