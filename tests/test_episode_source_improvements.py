"""Regressions reproduced by the live source/clip audit."""
import asyncio
from types import SimpleNamespace
import time

import animepack as api
import pytest
from si_hyx_parts.kuhi import _race, _match, anikoto, anikoto_watch, anikoto_megaplay
from si_hyx_parts.kuhi.client import KuhiClient
from si_hyx_parts.kuhi.provider_policy import DISABLED
from si_hyx_parts.animepack import episode_captions as captions
from si_hyx_parts.animepack import episode_release_cache as cache
from si_hyx_parts.animepack.episode_caption_policy import mode, dialogue_window


@pytest.mark.parametrize("name", sorted(DISABLED))
def test_disabled_provider_is_never_called_even_if_injected_into_race(name):
    async def fail(*args):
        raise AssertionError("disabled provider contacted")
    mod = SimpleNamespace(get_episodes=fail, watch=fail)
    async def run():
        assert await _race._episodes_one(mod, name, 1, {}) == (name, None)
        assert await _race._watch_one(mod, name, 1, 1, "sub", {}) == (name, None, 0.0, False)
    asyncio.run(run())


def test_miruro_client_compatibility_entry_points_never_call_network(monkeypatch):
    from si_hyx_parts.kuhi import legacy
    monkeypatch.setattr(legacy, "episodes", lambda *_: pytest.fail("Miruro request"))
    client = KuhiClient()
    assert client.legacy_episodes(1, None) == {}
    assert client.legacy_streams(1, 1, None) == []
    client.close()


@pytest.mark.parametrize("name", ["kaa", "animegg", "aniwaves"])
def test_zero_ru_sources_do_not_consume_required_ru_budget(name):
    async def fail(*args):
        pytest.fail("source without RU queried")
    assert asyncio.run(_race._episodes_one(SimpleNamespace(get_episodes=fail), name, 1,
                                           {"subtitle_mode": "required"})) == (name, None)


def test_episode_count_cannot_rescue_the_wrong_title():
    async def episodes(slug):
        return [{"number": number} for number in range(1, 26)]
    assert asyncio.run(_match.select_series(
        [{"slug": "osomatsu-third-season", "score": .57}], episodes, 25, "FINISHED", 50)) is None
    assert asyncio.run(_match.select_series(
        [{"slug": "bakuman-third-season", "score": .99}], episodes, 25, "FINISHED", 50))["slug"] == "bakuman-third-season"


def test_non_latin_titles_and_opaque_url_hashes_do_not_create_false_matches():
    assert _match.dice_coeff("", "") == 0
    assert _match.dice_coeff("青い花", "黒い猫") < .65
    assert _match.title_score("Bakuman 3rd Season", "Bakuman 3rd Season", "bakuman-3rd-season-x71nm") > .9
    assert _match.title_score("Ao Ashi", "Ao Ashi", "ao-ashi-g5zlq") > .9


def test_watch_rejects_explicit_foreign_mal_before_resolving_players(monkeypatch):
    async def series(*args):
        return {"mode": "local", "offset": 0, "show_id": "wrong", "slug": "wrong", "title": "wrong"}
    async def listing(url, headers):
        assert "/episode/list/" in url
        return {"result": '<a data-id="1" data-num="6" data-mal="34106" data-ids="server" data-slug="6" data-timestamp="x">'}
    monkeypatch.setattr(anikoto, "resolve_series", series)
    monkeypatch.setattr(anikoto_watch, "fetch_json", listing)
    with pytest.raises(RuntimeError, match="MAL"):
        asyncio.run(anikoto_watch._scrape_episode_watch(12365, "sub", 6, {"media": {"idMal": 12365}}))


def test_catalogue_rejects_foreign_mal_and_ignores_old_identity_cache(monkeypatch):
    async def candidates(*args):
        return [{"slug": "wrong", "title": "Bakuman 3", "score": 1}]
    async def episodes(*args):
        return [{"number": 1, "mal_id": "34106"}]
    async def offset(*args):
        return 0
    monkeypatch.setattr(anikoto, "find_top_slugs", candidates)
    monkeypatch.setattr(anikoto, "scrape_series", episodes)
    monkeypatch.setattr(anikoto, "get_prequel_offset", offset)
    monkeypatch.setattr(anikoto._cache, "cached", lambda key, *_: {"slug": "old-wrong"} if key.startswith("np:anikoto:") else None)
    with pytest.raises(RuntimeError, match="match not found"):
        asyncio.run(anikoto.resolve_series(12365, {"media": {"idMal": 12365, "title": {"romaji": "Bakuman 3"}, "episodes": 25}}))


def test_unknown_and_arabic_tracks_are_not_labelled_english():
    assert anikoto_megaplay._map_track({"label": "Arabic"}, "server")["srclang"] == "ar"
    assert anikoto_megaplay._map_track({"label": "Russian"}, "server")["srclang"] == "ru"
    assert anikoto_megaplay._map_track({"label": "unknown"}, "server")["srclang"] == "und"


def test_legacy_checkbox_migrates_to_strict_mode():
    assert mode(api.PackSettings(episode_ru_subtitles=True)) == "required"
    assert mode(api.PackSettings(episode_ru_subtitles=False)) == "none"
    settings = api.PackSettings(episode_subtitle_mode="preferred")
    assert mode(api.PackSettings.from_dict(settings.to_dict())) == "preferred"


def test_no_ru_does_not_download_or_burn_detachable_russian_track(monkeypatch):
    gen = SimpleNamespace(s=api.PackSettings(episode_subtitle_mode="none"),
                          stopped=lambda: False, rng=None)
    monkeypatch.setattr(captions, "choose_start", lambda *a: 100)
    monkeypatch.setattr(captions, "load", lambda *a: pytest.fail("RU captions downloaded"))
    source = {"audio": "sub", "ru_subtitles": True, "hardsub": False, "subtitles": [{}]}
    assert captions.prepare(gen, source, {"format": {"duration": 1400}},
                            SimpleNamespace(deadline=time.monotonic() + 60)) == (100, [])
    assert not captions.allowed(gen, dict(source, hardsub=True))


def test_required_ru_never_accepts_english_hardsub():
    gen = SimpleNamespace(s=api.PackSettings(episode_subtitle_mode="required"))
    assert not captions.allowed(gen, {"hardsub": True, "subtitle_language": "en"})


def test_sfx_and_overlapping_duplicate_cues_do_not_count_as_dialogue():
    assert not dialogue_window([(0, 3, "Жамк"), (4, 8, "Жамк")])
    assert not dialogue_window([(0, 1, "Привет, давно не виделись!"), (0, 1, "Я тоже очень рад тебя видеть.")])
    assert dialogue_window([(0, 3, "Привет, давно не виделись!"), (4, 8, "Я тоже очень рад тебя видеть.")])


def test_same_alloha_metadata_is_fetched_once_concurrently_but_parents_are_preserved():
    cache._CACHE.clear()
    calls = []
    async def load():
        calls.append(1)
        await asyncio.sleep(.01)
        return {"all": {"1": {}}, "type": "tv"}
    async def run():
        return await asyncio.gather(
            cache.public_metadata("https://alloha.test/id?episode=1&season=1", load),
            cache.public_metadata("https://alloha.test/id?episode=7&season=1", load))
    first, second = asyncio.run(run())
    assert len(calls) == 1 and first == second
    first["type"] = "wrong"
    assert second["type"] == "tv"
    assert cache.identity("https://alloha.test/id?season=1") != cache.identity("https://alloha.test/id?season=2")


def test_alloha_array_uses_published_episode_number_not_array_position():
    from si_hyx_parts.animepack.episode_alloha_catalog import releases
    item = dict(episode=7, seasons=1, translation="Русские субтитры", id_translation=275, id=1)
    data = {"type": "serial", "all": {"1": [{"t275": item}]}}
    result = releases(data, "https://alloha.test/id", "https://animego.test/title", "animego")
    assert list(result) == [7]
    assert "episode=7" in result[7][0]["embed"]
    item["episode"] = 7.5
    assert releases(data, "https://alloha.test/id", "https://animego.test/title", "animego") == {}


def test_alloha_dictionary_rejects_contradictory_episode_numbers():
    from si_hyx_parts.animepack.episode_alloha_catalog import releases
    item = dict(episode=7, seasons=1, translation="Русские субтитры", id_translation=275, id=1)
    data = {"type": "serial", "all": {"1": {"8": {"t275": item}}}}
    assert releases(data, "https://alloha.test/id", "https://animego.test/title", "animego") == {}
