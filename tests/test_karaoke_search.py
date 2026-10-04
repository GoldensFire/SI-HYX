"""Discovery uses anime context while preserving song and singer identity."""
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from karaoke.lyrics import LyricSites
from karaoke.mugen import Mugen
from karaoke.search import context, queries, matches_page
from karaoke.matching import metadata_matches
from karaoke.model import Track


def test_queries_cover_song_artist_anime_aliases_and_song_type():
    info = context({"songName": "Light (TV Size)", "songArtist": "Singer",
                    "animeENName": "Star Journey"},
                   {"name": "Hoshi no Tabi", "japanese": "星の旅",
                    "russian": "Путешествие звёзд", "synonyms": ["Hoshi no Tabi"]}, "opening")
    planned = queries("Light (TV Size)", "Singer", info)
    assert "Light (TV Size) Singer" in planned and "Light Singer" in planned
    assert "Light" in planned and "Singer" in planned
    assert "Hoshi no Tabi opening" in planned
    assert "Hoshi no Tabi" in planned and "星の旅" in planned
    assert "Light (TV Size) Star Journey" in planned
    assert len(planned) == len(set(planned)) <= 20


def test_anime_only_hit_needs_song_and_performer_on_destination_page():
    calls = []
    class Http:
        def bytes(self, url, **kwargs):
            calls.append(url)
            query = parse_qs(urlparse(url).query).get("q", [""])[0]
            if url.endswith("/journey/light"):
                return ('<h1>Light Lyrics</h1><p>Artist: Singer</p>'
                        '<div class="kanjilyrics-sbs">星の光</div>'
                        '<div class="romajilyrics-sbs">hoshi no hikari</div>').encode()
            if url.endswith("/journey/wrong"):
                return ('<h1>Light Lyrics</h1><p>Other performer</p>'
                        '<div class="kanjilyrics-sbs">他の歌</div>').encode()
            if "animesonglyrics" in url and query == "Journey":
                return b'<a href="/journey/wrong">Journey</a><a href="/journey/light">Journey</a>'
            return b'<html><p>No matches</p></html>'
    sheet = LyricSites(Http()).search("Light", "Singer", duration=90,
                                     context={"anime": ["Journey"], "kind": "opening"})
    assert sheet and sheet.original == ["星の光"]
    assert sheet.url.endswith("/journey/light")
    searches = [parse_qs(urlparse(url).query).get("q", [""])[0] for url in calls]
    assert "Light Singer" in searches and "Journey" in searches


def test_song_aliases_help_discovery_without_accepting_other_song_or_singer():
    info = {"titles": ["光"], "artists": ["歌手"]}
    assert matches_page("Light", "Singer", "光 Lyrics", "歌手", info)
    assert not matches_page("Light", "Singer", "Other song", "歌手", info)
    assert not matches_page("Light", "Singer", "光 Lyrics", "OtherSinger", info)
    track = Track("光", ["歌手"], 90, "KM", "lyrics", "audio")
    assert not metadata_matches("Light", "Singer", 90, track)
    assert metadata_matches("Light", "Singer", 90, track, aliases=info["titles"], artists=info["artists"])


def test_mugen_finds_anime_search_hit_and_deduplicates_lyrics():
    calls = []
    class Http:
        def json(self, url, **kwargs):
            query = parse_qs(urlparse(url).query)["filter"][0]
            calls.append(query)
            row = dict(titles={"qro": "Light"}, singers=[{"name": "Singer"}],
                       lyrics_infos=[{"filename": "light.ass"}], mediafile="light.mp4", duration=90)
            return {"content": [row]} if "Journey" in query else {}
    tracks = list(Mugen(Http()).search("Light", "Singer", context={"anime": ["Journey"]}))
    assert len(tracks) == 1 and tracks[0].title == "Light"
    assert "Journey" in calls and "Light Singer" in calls and "Singer" in calls


def test_blocked_site_is_skipped_but_other_searches_continue(monkeypatch):
    sites = LyricSites(SimpleNamespace())
    attempts = []
    class Forbidden(Exception):
        response = SimpleNamespace(status_code=403)
    def animelyrics(*args, **kwargs):
        attempts.append("blocked")
        raise Forbidden("403")
    def animesonglyrics(*args, **kwargs):
        attempts.append(kwargs["query"])
    monkeypatch.setattr(sites, "animelyrics", animelyrics)
    monkeypatch.setattr(sites, "animesonglyrics", animesonglyrics)
    sites.search("Light", "Singer", duration=90)
    sites.search("Light", "Singer", duration=90)
    assert attempts.count("blocked") == 1 and attempts.count("Light Singer") == 2


def test_resolver_passes_context_and_cached_presentation_retains_cutoff(tmp_path, monkeypatch):
    import numpy as np
    import animepack as ap
    import karaoke.resolver as module
    from karaoke.resolver import Resolver
    source = tmp_path / "source.audio"
    source.write_bytes(b"source recording")
    settings = ap.PackSettings(karaoke_ai_fallback=False)
    resolver = Resolver(None, settings, "ffmpeg", None, cache=tmp_path)
    info = {"anime": ["Journey"], "kind": "opening"}
    calls = []
    def search(title, artist, *, context):
        calls.append(context)
        return [Track("Light", ["Singer"], 40, "KM", "ass", "audio")]
    resolver.providers = [SimpleNamespace(search=search)]
    ass = ('[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
           r'Dialogue: 0,0:00:00.00,0:00:02.00,Romaji,,0,0,0,,{\kf300}light')
    monkeypatch.setattr(resolver.http, "bytes", lambda url, **k: ass.encode() if url == "ass" else b"ref")
    monkeypatch.setattr(module, "decode", lambda *a: np.zeros(40 * 22050))
    monkeypatch.setattr(module, "verify_audio", lambda *a: {"offset": 0})
    for _ in range(2):
        lines, _ = resolver.resolve(source, "Light", "Singer", info)
        assert lines[0].end == 3 and lines[0].visible_end == 2
    assert calls == [info]
