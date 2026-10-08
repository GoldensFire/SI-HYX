"""Nested title composition survives migration, toggles and model selection."""
import pytest
import animepack as api
import animepack_tab


@pytest.fixture
def tab(qapp):
    widget = animepack_tab.AnimePackTab()
    yield widget
    widget.cleanup()


def test_old_title_shares_migrate_to_one_pack_share(tab):
    tab.apply_settings(dict(pct_songs=50, pack_anagram=True, pct_anagram=10,
                           pack_synonyms=True, pct_synonyms=30,
                           pack_ukrainian=True, pct_ukrainian=10))
    assert tab.mix.keys() == ["songs", "titles"]
    assert tab.mix.shares()["titles"] == 50
    assert tab.title_mix.shares()["synonyms"] == 60
    settings = tab.collect()
    assert settings.mix_shares["songs"] == 50
    assert settings.mix_shares["synonyms"] == 30
    assert settings.mix_shares["anagram"] == 10
    assert settings.mix_shares["ukrainian"] == 10


def test_inner_toggles_do_not_change_the_pack_share_and_persist_when_disabled(tab):
    tab.chk_titles.setChecked(True)
    tab.mix.sliders["titles"].setValue(40)
    tab.chk_synonyms.setChecked(True)
    tab.title_mix.sliders["synonyms"].setValue(75)
    assert tab.mix.shares()["titles"] == 40
    settings = tab.collect()
    assert settings.mix_shares["synonyms"] == 30
    assert settings.mix_shares["anagram"] == 10
    tab.chk_titles.setChecked(False)
    data = tab.get_settings()
    tab.apply_settings(data)
    assert not tab.chk_titles.isChecked()
    assert tab.chk_synonyms.isChecked()
    assert tab.title_mix.shares()["synonyms"] == 75
    assert not tab.collect().mix_shares["synonyms"]


def test_all_five_title_types_share_one_category(tab):
    tab.chk_titles.setChecked(True)
    tab.chk_songs.setChecked(False)
    for key in tab.title_mix.KEYS:
        getattr(tab, "chk_" + key).setChecked(True)
    tab.title_mix.set_shares(dict.fromkeys(tab.title_mix.KEYS, 20))
    settings = api.PackSettings.from_dict(tab.collect().to_dict())
    assert tab.mix.keys() == ["titles"]
    assert sum(settings.mix_shares.values()) == 100
    assert all(settings.mix_shares[k] == 20 for k in tab.title_mix.KEYS)
    assert "По названию" in tab.lbl_left.text()


def test_image_model_is_shared_and_three_groups_are_independent(tab):
    tab.cb_gemini_image_model.setCurrentText("gemini-3.6-flash")
    tab.cb_gemini_model.setCurrentText("gemini-3.7-flash")
    tab.cb_gemini_title_model.setCurrentText("gemini-3.8-flash")
    data = tab.get_settings()
    tab.apply_settings(data)
    settings = tab.collect()
    assert settings.gemini_image_model == "gemini-3.6-flash"
    assert settings.pixiv_gemini_model == settings.manga_gemini_model == settings.gemini_image_model
    assert settings.gemini_model == "gemini-3.7-flash"
    assert settings.gemini_title_model == "gemini-3.8-flash"
    assert tab.cb_gemini_image_model.parent() is tab.group_gemini
    assert tab.cb_gemini_model.parent() is tab.group_gemini
    assert tab.cb_gemini_title_model.parent() is tab.group_gemini


def test_small_title_share_is_rounded_in_questions_instead_of_losing_types(tab):
    tab.chk_titles.setChecked(True)
    for key in tab.title_mix.KEYS:
        getattr(tab, "chk_" + key).setChecked(True)
    tab.title_mix.set_shares(dict.fromkeys(tab.title_mix.KEYS, 20))
    tab.mix.sliders["titles"].setValue(1)
    settings = tab.collect()
    settings.rounds, settings.themes, settings.questions = 10, 5, 6
    assert all(settings.mix_shares[k] > 0 for k in tab.title_mix.KEYS)
    quotas = settings.question_quotas
    assert sum(quotas[k] for k in tab.title_mix.KEYS) == 3
    assert sum(bool(quotas[k]) for k in tab.title_mix.KEYS) == 3


def test_legacy_image_model_follows_the_active_visual_composition(tab):
    tab.apply_settings(dict(pct_songs=0, pack_pixel=True, pct_pixel=100,
                           gemini_model="gemini-3.5-flash-lite",
                           pixiv_gemini_model="gemini-3.6-flash",
                           manga_gemini_model="gemini-3.7-flash"))
    assert tab.cb_gemini_image_model.currentText() == "gemini-3.5-flash-lite"
    tab.apply_settings(dict(pct_songs=0, pack_manga=True, pct_manga=100,
                           gemini_model="gemini-3.5-flash-lite",
                           manga_gemini_model="gemini-3.7-flash"))
    assert tab.cb_gemini_image_model.currentText() == "gemini-3.7-flash"


def test_generator_routes_all_visual_checks_to_the_same_selected_client():
    settings = api.PackSettings(pct_songs=0, pct_frames=34, frame_gemini_check=True,
                               pack_pixiv_art=True, pct_pixiv_art=33,
                               pack_manga=True, pct_manga=33, gemini_key="test-key",
                               gemini_image_model="gemini-3.6-flash",
                               gemini_image_thinking="low")
    generator = api.AnimePackGenerator(settings)
    assert generator.gemini_frames is generator.gemini_pixiv is generator.gemini_manga
    assert generator.gemini_frames.model == "gemini-3.6-flash"
    assert generator.gemini_frames.thinking == "low"
    assert generator.gemini_frames.purpose == "Изображения"
    generator.cleanup()
