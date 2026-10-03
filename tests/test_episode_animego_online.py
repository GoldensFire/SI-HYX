"""AnimeGO.online's actual DLE cards, relay slots and Alloha episode metadata."""
import asyncio
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from si_hyx_parts.animepack import episode_ru_animego as online
from si_hyx_parts.animepack import episode_alloha_catalog as alloha
from si_hyx_parts.animepack import episode_ru_yummy as yummy
from si_hyx_parts.animepack import episode_ru_players as players


def response(text="", data=None, url=""):
    return SimpleNamespace(text=text, json=lambda: data, url=url)


def file_script(data):
    # This is a JS quoted JSON string, not an executable fixture.
    return "const fileList = JSON.parse(" + json.dumps(json.dumps(data, ensure_ascii=False)) + ");"


def serial():
    def row(number, translation, label, season=1):
        return {"id": number * 100 + translation, "seasons": season, "episode": number,
                "id_translation": translation, "translation": label}
    return {"type": "serial", "active": {"seasons": 1, "episode": 7}, "all": {
        "1": {"2": {"t79": row(2, 79, "Субтитры"), "t1": row(2, 1, "AniStar")},
              "7": {"t79": row(7, 79, "Субтитры"), "t2": row(7, 2, "English subtitles")}},
        "2": {"1": {"t79": row(1, 79, "Субтитры", season=2)}}}}


def test_online_search_reads_numeric_prefix_paths_and_original_title_on_page():
    content = '''<a href="/872-title-p1.html"><span class="poster__title">Другой перевод</span></a>
    <a href="https://foreign.test/872-title.html"><span class="poster__title">Wrong</span></a>'''
    assert online.MIRRORS == ("https://animego.online",)
    assert online.search_rows(content) == [{"id": "872", "title": "Другой перевод",
                                           "url": "https://animego.online/872-title-p1.html"}]
    identity, _ = online.page_identity('<h1>Другой перевод</h1><div class="page__original">Original Title</div>')
    assert identity["other_titles"] == ["Original Title"]


def test_online_catalogue_uses_relay_and_actual_subtitle_episodes(monkeypatch):
    calls = []
    page = '''<h1>Другой перевод</h1><div class="page__original">Original Title</div>
    <div data-player-anime-id="872"><div data-player-slot="0" data-player-title="Плеер Alloha"></div>
    <div data-player-slot="1" data-player-title="Плеер Kodik"></div></div>'''
    async def get(url, *, params=None, **kwargs):
        calls.append((url, params))
        if url.endswith("index.php"):
            assert params["do"] == "search" and params["story"] == "Original Title"
            return response('<a href="/872-title-p1.html"><span class="poster__title">Другой перевод</span></a>')
        if url.endswith("controller.php"):
            assert params == {"mod": "player", "id": "872", "slot": "0"}
            return response(data={"status": True, "data": {"kind": "iframe", "src": "https://player.test/?token=x"}})
        if url.startswith("https://player.test"):
            return response(file_script(serial()))
        return response(page, url=url)
    monkeypatch.setattr(online, "get", get)
    monkeypatch.setattr(alloha, "get", get)
    candidate = SimpleNamespace(mal_id=42, anime={"name": "Original Title"})
    result = asyncio.run(online.catalogue(candidate, {}))
    assert set(result) == {2, 7}
    for number, rows in result.items():
        assert len(rows) == 1 and rows[0]["source"] == "animego"
        params = parse_qs(urlsplit(rows[0]["embed"]).query)
        assert params == {"token": ["x"], "season": ["1"], "episode": [str(number)], "translation": ["79"]}
    assert not any("animego.me" in url or "/player/" in url for url, _ in calls)


def test_foreign_mal_identity_rejects_same_named_wrong_season(monkeypatch):
    async def get(url, **kwargs):
        if url.endswith("index.php"):
            return response('<a href="/872-title.html"><span class="poster__title">Title</span></a>')
        return response('<h1>Title</h1><a href="https://shikimori.one/animes/43">MAL</a>')
    monkeypatch.setattr(online, "get", get)
    result = asyncio.run(online.catalogue(SimpleNamespace(mal_id=42, anime={"name": "Title"}), {}))
    assert not result and "тайтл не найден" in result.reason


def test_missing_player_metadata_raises_instead_of_reported_zero(monkeypatch):
    async def get(*args, **kwargs):
        return response("<html>Challenge page</html>")
    monkeypatch.setattr(alloha, "get", get)
    with pytest.raises(ValueError, match="списка серий"):
        asyncio.run(alloha.catalogue("https://player.test", online.BASE, "animego"))


def test_movie_and_requested_season_never_invent_episode_numbers():
    movie = {"type": "movie", "all": {"t79": {"id": 9, "id_translation": 79, "translation": "Субтитры"}}}
    assert set(alloha.releases(movie, "https://player.test", online.BASE, "animego")) == {1}
    assert set(alloha.releases(serial(), "https://player.test?season=2", online.BASE, "animego")) == {1}


def test_native_cvh_relay_uses_supplied_publisher_and_title_id(monkeypatch):
    async def get(url, *, params, **kwargs):
        assert params == {"pub": "321", "aggr": "site", "id": "100"}
        return response(data={"items": [{"episode": 7, "season": 1, "vkId": "sub",
                                         "voiceType": "Субтитры", "voiceStudio": "Team"}]})
    monkeypatch.setattr(players, "get", get)
    result = asyncio.run(players.subtitle_playlist(online.BASE, online.BASE, "animego",
                           title_id=100, publisher=321, aggregator="site"))
    assert list(result) == [7] and result[7][0]["video_id"] == "sub"


def test_yummy_distinguishes_missing_title_from_only_dub(monkeypatch):
    candidate = SimpleNamespace(mal_id=42, anime={"name": "Title"})
    async def absent(*args, **kwargs):
        return response(data={"response": []})
    monkeypatch.setattr(yummy, "get", absent)
    result = asyncio.run(yummy.catalogue(candidate, {}))
    assert not result and "тайтл не найден" in result.reason
    async def dub(url, **kwargs):
        rows = [{"anime_id": 9, "title": "Title", "remote_ids": {"myanimelist_id": 42}}]
        if url.endswith("videos"):
            rows = [{"number": "1", "data": {"player": "Плеер Alloha", "dubbing": "Озвучка"}}]
        return response(data={"response": rows})
    monkeypatch.setattr(yummy, "get", dub)
    result = asyncio.run(yummy.catalogue(candidate, {}))
    assert not result and "тайтл найден; нет RU-субтитров" in result.reason
