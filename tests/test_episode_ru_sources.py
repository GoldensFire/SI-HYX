"""Real catalogue shapes: exact title binding, all sub teams, no Kodik/dub."""
import asyncio
import html
import json
from types import SimpleNamespace

from si_hyx_parts.animepack import episode_ru_animego as animego
from si_hyx_parts.animepack import episode_ru_animelib as animelib
from si_hyx_parts.animepack import episode_ru_yummy as yummy
from si_hyx_parts.animepack import episode_ru_players as players
from si_hyx_parts.animepack.episode_ru_catalog import matches, subtitle_release


def response(data=None, text=""):
    return SimpleNamespace(json=lambda: data, text=text)


def test_exact_foreign_identity_overrules_same_title():
    candidate = SimpleNamespace(mal_id=42, anime={"name": "Same Title"})
    ctx = {"media": {"id": 7, "seasonYear": 2023}}
    assert matches({"name": "Same Title", "mal_id": 42}, candidate, ctx)
    assert not matches({"name": "Same Title", "mal_id": 43}, candidate, ctx)
    assert not matches({"name": "Same Title", "year": 2024}, candidate, ctx)
    assert not matches({"name": "Same Title", "anilist_id": 8}, candidate, ctx)
    assert not matches({"name": "Same Title II"}, candidate, ctx)


def test_subtitle_classification_never_uses_dub_or_english_subs():
    assert subtitle_release("Субтитры Team A")
    assert subtitle_release("Russian subtitles")
    assert subtitle_release({"id": 1, "label": "Субтитры"})
    assert not subtitle_release({"id": 2, "label": "Субтитры"})
    assert not subtitle_release("English subtitles")
    assert not subtitle_release("Озвучка Team A")


def test_animego_reads_all_sub_players_and_actual_ajax_episode_ids():
    content = """<button data-episode-number='7' data-episode='900'></button>
    <button data-episode='901' data-episode-number='9'></button>
    <button data-player='//aniboom.one/embed/a?episode=7&amp;translation=1'
      data-provider-title='AniBoom' data-translation-title='Субтитры A'></button>
    <button data-player='//aniboom.one/embed/b?episode=7'
      data-provider-title='AniBoom' data-translation-title='Субтитры B'></button>
    <button data-player='//kodikplayer.com/seria/x/h/720p'
      data-provider-title='Kodik' data-translation-title='Субтитры'></button>
    <button data-player='//animego.me/cdn-iframe/7/1/7'
      data-provider-title='CVH' data-translation-title='Озвучка'></button>"""
    episodes, rows = animego.parse_players(content, "https://animego.me/anime/title-1")
    assert episodes == {7: "900", 9: "901"}
    assert [r["release"] for r in rows] == ["Субтитры A", "Субтитры B"]
    assert "&translation=1" in rows[0]["embed"]


def test_yummy_retains_all_sub_releases_and_skips_fractional_episodes():
    def video(player, dubbing, number="7", ident=1):
        return {"video_id": ident, "number": number,
                "data": {"player": "Плеер " + player, "dubbing": dubbing},
                "iframe_url": f"//{player.lower()}.example/embed/{ident}",
                "skips": {"opening": {"time": 0, "length": 90}}}
    rows = [video("CVH", "Субтитры A"), video("Aniboom", "Субтитры B", ident=2),
            video("Alloha", "Субтитры C", ident=3), video("Kodik", "Субтитры"),
            video("CVH", "Озвучка"), video("CVH", "Субтитры", "7.5")]
    catalog = yummy.releases(rows, "https://yummyani.me/catalog/item/title")
    assert list(catalog) == [7]
    assert [r["player"] for r in catalog[7]] == ["cvh", "aniboom", "alloha"]
    assert catalog[7][0]["intro"] == {"start": 0, "end": 90}


def test_animelib_checks_episode_binding_and_keeps_each_sub_team():
    row = {"episode_id": 9, "anime_id": "42", "number": 7,
           "embed": "https://api.animelib.org/api/episodes/9", "referer": "https://animelib.org/watch"}
    data = {"id": 9, "anime_id": 42, "number": "7", "players": [
        {"id": 1, "player": "Animelib", "translation_type": {"id": 1},
         "team": {"name": "Team A"}, "video": {"quality": [{"quality": 1080, "href": "a.mp4"}]}},
        {"id": 2, "player": "Animelib", "translation_type": {"id": 1}, "src": "https://cdn/b.mp4"},
        {"id": 3, "player": "Kodik", "translation_type": {"id": 1}, "src": "https://kodik/720p"},
        {"id": 4, "player": "Animelib", "translation_type": {"id": 2}, "src": "https://cdn/dub.mp4"}]}
    result = animelib.releases(data, row)
    assert [r["release_id"] for r in result] == [1, 2]
    assert result[0]["payload"]["video"]["quality"][0]["href"] == "a.mp4"
    assert not animelib.releases(data | {"number": "8"}, row)
    assert not animelib.releases(data | {"anime_id": 43}, row)


def test_cvh_discovers_sub_teams_even_when_site_exposes_only_dub_button(monkeypatch):
    rows = [{"vkId": "sub-a", "season": 1, "episode": 7, "voiceStudio": None, "voiceType": "Субтитры"},
            {"vkId": "sub-b", "season": 1, "episode": 7, "voiceStudio": "Team", "voiceType": "Субтитры"},
            {"vkId": "dub", "season": 1, "episode": 7, "voiceType": "Многоголосый"},
            {"vkId": "season2", "season": 2, "episode": 7, "voiceType": "Субтитры"}]
    async def get(*args, **kwargs):
        return response({"items": rows})
    monkeypatch.setattr(players, "get", get)
    catalog = asyncio.run(players.subtitle_playlist(
        "https://animego.me/cdn-iframe/42/1/7?dubbing=Dub", "https://animego.me/anime/title-1", "animego"))
    assert list(catalog) == [7]
    assert [r["video_id"] for r in catalog[7]] == ["sub-a", "sub-b"]


def test_animelib_search_and_episode_pagination_are_not_truncated(monkeypatch):
    candidate = SimpleNamespace(mal_id=42, anime={"name": "Title"})
    calls = []
    async def get(url, *, params, **kwargs):
        calls.append((url, params["page"]))
        if url.endswith("/anime"):
            rows = [] if params["page"] == 1 else [{"id": 5, "name": "Title", "mal_id": 42, "slug_url": "5--title"}]
        else:
            rows = [{"id": params["page"], "number": "7" if params["page"] == 1 else "9", "anime_id": 5}]
        return response({"data": rows, "links": {"next": "next" if params["page"] == 1 else None}})
    monkeypatch.setattr(animelib, "get", get)
    catalog = asyncio.run(animelib.catalogue(candidate, {}))
    assert set(catalog) == {7, 9}
    assert len(calls) == 4


def test_aniboom_reads_html_escaped_hls_and_dash_with_required_referer(monkeypatch):
    data = {"hls": json.dumps({"src": "https://cdn/master.m3u8"}),
            "dash": json.dumps({"src": "https://cdn/master.mpd"}), "quality": 1080}
    async def get(*args, **kwargs):
        assert kwargs["headers"]["Referer"] == "https://animego.me/anime/title-1"
        return response(text='<video data-parameters="' + html.escape(json.dumps(data), quote=True) + '">')
    monkeypatch.setattr(players, "get", get)
    row = {"source": "animego", "player": "aniboom", "embed": "https://aniboom.one/embed/a?episode=7",
           "referer": "https://animego.me/anime/title-1", "release": "Субтитры"}
    result = asyncio.run(players.aniboom(row))
    assert [s["type"] for s in result] == ["hls", "dash"]
    assert all(s["ru_subtitles"] and s["referer"] == "https://aniboom.one/" for s in result)
