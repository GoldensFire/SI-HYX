"""Real timing tiers, edition identity, text transfer and the no-model branch."""
import base64
from dataclasses import replace
import struct
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import numpy as np
import pytest

import animepack as ap
from karaoke.identity import exact_identity, recording_matches
from karaoke.lyrics import Sheet
from karaoke.model import Line, Unit
from karaoke.petit_timing import TimedLyrics, word_sync, line_sync, line_times
from karaoke.petitlyrics import Edition, PetitLyrics
from karaoke.source_audit import SourceAudit
from karaoke.text_alignment import transfer
from karaoke.uta_net import parse_sheet


def edition(**values):
    return replace(Edition("123", "Song", "Artist", "Album", 90, b"", 3), **values)


def test_identity_never_accepts_fuzzy_artists_or_longer_titles():
    assert exact_identity("Song", "Artist", "Song(songu)", "Artist")
    assert not exact_identity("Song", "Artist", "Song 2", "Artist")
    assert not exact_identity("Song", "Artist", "Song", "Artists")
    assert not exact_identity("が", "Artist", "か", "Artist")
    assert not exact_identity("Song", "ば", "Song", "は")
    assert not recording_matches("Song", 90, edition(title="Song (cover)"))
    assert exact_identity("Song", "Artist", "歌", "歌手",
                          {"titles": ["歌"], "artists": ["歌手"]})


@pytest.mark.parametrize("title,duration,accepted", [
    ("Song", 90, True), ("Song (TV size)", 90, True),
    ("Song (Full ver.)", 240, False), ("Song (live)", 90, False),
    ("Song", 0, False), ("Song", 94, False)])
def test_editions_need_agreeing_duration_and_version(title, duration, accepted):
    assert recording_matches("Song", 90, edition(title=title, duration=duration)) == accepted


def test_word_sync_keeps_each_real_character_interval():
    payload = b'<wsy><line><linestring>ab</linestring><word><starttime>1000</starttime>' \
              b'<endtime>1250</endtime><wordstring>a</wordstring></word><word>' \
              b'<starttime>1500</starttime><endtime>2000</endtime><wordstring>b</wordstring>' \
              b'</word></line></wsy>'
    timed = word_sync(payload, 3)
    assert timed.level == "character"
    assert timed.lines[0].units == [Unit(1, 1.25, "a"), Unit(1.5, 2, "b")]
    with pytest.raises(ValueError):
        word_sync(payload.replace(b"<linestring>ab", b"<linestring>ac"), 3)
    with pytest.raises(ValueError):
        word_sync(payload, 1.8)


def lsy(times):
    count = len(times)
    payload = bytearray(204 + 66 * count)
    payload[:8] = b"MHDROBJT"
    struct.pack_into("<I", payload, 56, count)
    struct.pack_into("<H", payload, 66, 64)
    struct.pack_into(f"<{count}H", payload, 204, *times)
    return bytes(payload)


def test_line_sync_keeps_blank_cues_and_never_invents_word_timing():
    timed = line_sync(lsy([100, 250, 300, 500]), "a\n\nb\n\n", 6)
    assert timed.level == "line"
    assert [(row.start, row.end) for row in timed.lines] == [(1, 2.5), (3, 5)]
    assert len(timed.lines[0].units) == 1
    with pytest.raises(ValueError, match="число строк"):
        line_sync(lsy([100, 200]), "a", 6)
    with pytest.raises(ValueError):
        line_times(lsy([100, 90]))
    assert line_times(lsy([65000, 100])) == [650, 656.36]


def test_line_sync_text_is_pinned_to_same_publication():
    client = PetitLyrics(None, SourceAudit())
    client.request = lambda *a, **k: [edition(id="999", tier=1, payload=b"a\nb")]
    with pytest.raises(ValueError, match="выбранного ID"):
        client.timings(edition(tier=2, payload=lsy([100, 200])))


def test_external_romaji_is_retained_and_split_lines_are_aligned(monkeypatch):
    import karaoke.phonetic_units as pronunciation
    monkeypatch.setattr(pronunciation, "readings", lambda text: [
        {"orig": char, "hepburn": {"あ": "a", "い": "i"}.get(char, char)} for char in text])
    original = [Line(1, 3, [Unit(1, 1.5, "あ"), Unit(2, 3, "い")]),
                Line(4, 5, [Unit(4, 5, "あ")])]
    sheet = Sheet("Song", "Artist", "uta", ["あ", "いあ"], ["A I", "A"])
    lines, meta = transfer(TimedLyrics(original, "character"), sheet)
    assert [u.text for u in lines[0].units] == ["A", " I"]
    assert [(u.start, u.end) for u in lines[0].units] == [(1, 1.5), (2, 3)]
    assert [line.text for line in lines] == ["A I", "A"]
    assert meta["jp_coverage"] == 1
    with pytest.raises(ValueError, match="JP"):
        transfer(TimedLyrics(original, "character"), replace(sheet, original=["違う曲"]))
    with pytest.raises(ValueError, match="Romaji"):
        transfer(TimedLyrics(original, "character"), replace(sheet, romaji=["unrelated lyrics"]))


def test_uta_parses_actual_global_containers():
    payload = '<h1><span>歌(uta)</span><span class="artist-name">歌手</span></h1>' \
              '<div id="kashi-area-roma">a<br>b</div><div id="kashi-area">あ<br>い</div>'
    sheet = parse_sheet(payload.encode(), "uta")
    assert (sheet.title, sheet.artist, sheet.original, sheet.romaji) == ("歌(uta)", "歌手", ["あ", "い"], ["a", "b"])
    assert parse_sheet(payload.replace("a<br>b", "").encode(), "uta") is None


def test_uta_discovery_accepts_its_explicit_romaji_title_alias():
    from karaoke.uta_net import UtaNet
    page = '<h1><span>歌(uta)</span><span class="artist-name">Artist</span></h1>' \
           '<div id="kashi-area-roma">a</div><div id="kashi-area">あ</div>'
    http = SimpleNamespace(json=lambda *a, **k: {"song": [{"tid": 123, "title": "歌", "titleRoma": "uta"}]},
                           bytes=lambda *a, **k: page.encode())
    assert UtaNet(http, SourceAudit()).search("Uta", "Artist").original == ["あ"]


def test_petit_response_keeps_distinct_ids_and_passes_query_as_form():
    requests = []
    def post(url, data, **options):
        requests.append(data)
        tree = ET.Element("response")
        ET.SubElement(tree, "status").text = "00000000"
        songs = ET.SubElement(tree, "songs")
        for id in ("123", "124"):
            song = ET.SubElement(songs, "song")
            for key, value in dict(lyricsId=id, title="Song", artist="Artist", duration="90000",
                                  lyricsType="3", lyricsData=base64.b64encode(b"<wsy/>").decode()).items():
                ET.SubElement(song, key).text = value
        return ET.tostring(tree)
    client = PetitLyrics(SimpleNamespace(post=post), SourceAudit())
    assert [row.id for row in client.search("Song", "Artist", 90)] == ["123", "124"]
    assert requests[0]["lyricsType"] == "3" and requests[0]["maxCount"] == "20"


def test_pair_precedes_ai_and_survives_with_ai_disabled(tmp_path, monkeypatch):
    import karaoke.resolver as module
    import karaoke.fallback as fallback
    source = tmp_path / "audio.mp3"
    source.write_bytes(b"source")
    resolver = module.Resolver(None, ap.PackSettings(karaoke_ai_fallback=False), "ffmpeg", None, cache=tmp_path)
    resolver.providers = []
    monkeypatch.setattr(module, "decode", lambda *a: np.zeros(90 * 22050))
    resolver.paired.resolve = lambda *a: ([Line(1, 2, [Unit(1, 2, "romaji")])],
                                        {"source": "PetitLyrics + Uta-Net Global", "offset": 0})
    def unexpected(*a, **k):
        raise AssertionError("No acoustic models on the paired path")
    monkeypatch.setattr(fallback, "align", unexpected)
    lines, metadata = resolver.resolve(source, "Song", "Artist")
    assert lines[0].text == "romaji" and not metadata["ai_used"]
    resolver.paired.resolve = unexpected
    assert resolver.resolve(source, "Song", "Artist")[1] == metadata


def test_paired_miss_reaches_ai_after_providers(tmp_path, monkeypatch):
    import karaoke.resolver as module
    import karaoke.fallback as fallback
    source = tmp_path / "audio.mp3"
    source.write_bytes(b"source")
    resolver = module.Resolver(None, ap.PackSettings(karaoke_ai_fallback=True), "ffmpeg", None, cache=tmp_path)
    resolver.providers = []
    monkeypatch.setattr(module, "decode", lambda *a: np.zeros(90 * 22050))
    calls = []
    resolver.paired.resolve = lambda *a: calls.append("pair")
    def lyrics(*a, **k):
        calls.append("lyrics")
        return Sheet("Song", "Artist", "lyrics", ["歌"], ["uta"])
    resolver.lyrics.search = lyrics
    def align(*a, **k):
        calls.append("ai")
        return [Line(1, 2, [Unit(1, 2, "romaji")])]
    monkeypatch.setattr(fallback, "align", align)
    assert resolver.resolve(source, "Song", "Artist")[1]["ai_used"]
    assert calls == ["pair", "lyrics", "ai"]


def test_post_cache_distinguishes_publication_and_tier(tmp_path):
    from karaoke.http import Http
    calls = []
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def raise_for_status(self):
            pass
        def iter_content(self, *args):
            yield b"response"
    def post(url, **options):
        calls.append(options["data"])
        return Response()
    http = Http(SimpleNamespace(post=post), cache=tmp_path)
    http.post("endpoint", {"id": "123", "tier": "3"})
    http.post("endpoint", {"id": "124", "tier": "3"})
    http.post("endpoint", {"id": "123", "tier": "1"})
    http.post("endpoint", {"tier": "3", "id": "123"})
    assert len(calls) == 3
