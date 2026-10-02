# -*- coding: utf-8 -*-
"""Comic-only settings, one share bar, and no prose-to-manga substitution."""
import animepack as ap
import animepack_tab
from animepack_api import MANGA_KINDS, MangaDexApi
from si_hyx_parts.animepack.manga_editions import shares
from test_animepack_extras import make_manga


def test_prose_is_removed_even_when_old_flags_are_true():
    settings = ap.PackSettings.from_dict({"manga_kinds": {
        "manga": False, "manhwa": True, "manhua": True,
        "light_novel": True, "novel": True}})
    assert "novel" not in MANGA_KINDS and "light_novel" not in MANGA_KINDS
    assert "novel" not in settings.to_dict()["manga_kinds"]
    assert shares(settings) == {"manga": 0, "manhwa": 50, "manhua": 50}
    settings.manga_kinds["light_novel"] = True
    assert not ap.filter_anime(make_manga(kind="light_novel"), settings, manga=True)


def test_prose_only_old_settings_restore_a_usable_comic_selection():
    settings = ap.PackSettings.from_dict({"manga_kinds": {
        k: k in ("light_novel", "novel") for k in
        ("manga", "manhwa", "manhua", "one_shot", "doujin", "light_novel", "novel")}})
    assert any(settings.manga_kinds.values())
    assert sum(shares(settings).values()) == 100


def test_comic_share_bar_survives_reload_and_controls_generation(qapp):
    tab = animepack_tab.AnimePackTab()
    try:
        tab.manga_edition_bar.set_values({"manga": 0, "manhwa": 65, "manhua": 35})
        got = tab.collect()
        assert shares(got) == {"manga": 0, "manhwa": 65, "manhua": 35}
        assert not got.manga_kinds["manga"]
        assert not {"light_novel", "novel"} & tab.chk_manga_kinds.keys()
        tab.apply_settings(got.to_dict())
        assert tab.manga_edition_bar.values() == {"manga": 0, "manhwa": 65, "manhua": 35}
        mix = ap.MangaMix(got, 20)
        assert mix.kind_target == {"manhwa": 13, "manhua": 7, "": 0}
        cand = ap.SongCandidate({}, make_manga(), kind=ap.MANGA_KIND, media="manga")
        assert not mix.allows(cand) and mix.bench_size == 0
        mix.off = True
        assert not mix.allows(cand)
    finally:
        tab.cleanup()


def test_matching_title_cannot_override_a_conflicting_mal_id():
    row = {"id": "wrong-edition", "attributes": {
        "links": {"mal": "83021"}, "title": {"en": "Same Title"}}}
    assert MangaDexApi._match([row], 83019, {"sametitle"}) == ""
    row["attributes"]["links"]["mal"] = "83019"
    assert MangaDexApi._match([row], 83019, {"sametitle"}) == "wrong-edition"


def test_rounding_edition_targets_keeps_the_requested_question_count():
    settings = ap.PackSettings(manga_pct_manhwa=50, manga_pct_manhua=50)
    mix = ap.MangaMix(settings, 3)
    assert sum(mix.kind_target.values()) == 3
    assert mix.kind_target[""] == 0


def test_scene_selection_requires_a_key_even_with_local_title_check():
    settings = ap.PackSettings(pack_manga=True, pct_manga=100, pct_songs=0,
                               manga_gemini_check=False, manga_title_check_mode="local")
    assert any("выбора сцен" in message for message in settings.validate())
    settings.manga_character_crop = False
    assert not any("выбора сцен" in message for message in settings.validate())
