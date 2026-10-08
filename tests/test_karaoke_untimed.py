"""Untimed source testing must never reuse authored timings or call their sites."""
from types import SimpleNamespace

import numpy as np

import animepack as ap
from karaoke.lyrics import LyricSites, Sheet, clean_lines, parse_html, text_lines
from karaoke.model import Line, Track, Unit
from karaoke.resolver import Resolver
from karaoke.source_audit import SourceAudit


def test_untimed_mode_ignores_authored_cache_and_all_timing_providers(tmp_path, monkeypatch):
    import karaoke.resolver as module
    import karaoke.fallback as fallback
    source = tmp_path / "source.mp3"
    source.write_bytes(b"recording")
    settings = ap.PackSettings(karaoke_ai_fallback=True)
    monkeypatch.setattr(module, "decode", lambda *a: np.zeros(40 * 22050))
    monkeypatch.setattr(module, "verify_audio", lambda *a: {"offset": 0})
    authored = Resolver(None, settings, "ffmpeg", None, cache=tmp_path)
    authored.providers = [SimpleNamespace(search=lambda *a: [
        Track("Song", ["Artist"], 40, "Karaoke Mugen", "ass", "audio")])]
    monkeypatch.setattr(authored.http, "bytes", lambda url, **k: b"reference")
    monkeypatch.setattr(module, "read_ass", lambda *a: [Line(1, 3, [Unit(1, 3, "old")])])
    assert authored.resolve(source, "Song", "Artist")[1]["ai_used"] is False

    untimed = Resolver(None, settings, "ffmpeg", None, cache=tmp_path, authored_sources=False)
    assert untimed.providers == []
    def unexpected(*a, **k):
        raise AssertionError("Authored sources must not be consulted")
    monkeypatch.setattr(untimed.paired, "resolve", unexpected)
    sheet = Sheet("Song", "Artist", "https://lyrics.example/song", ["native"], ["new"])
    monkeypatch.setattr(untimed.lyrics, "search", lambda *a, **k: sheet)
    calls = []
    def align(*a, **k):
        calls.append(a[1])
        return [Line(1, 3, [Unit(1, 3, "new")])]
    monkeypatch.setattr(fallback, "align", align)
    lines, metadata = untimed.resolve(source, "Song", "Artist")
    assert lines[0].text == "new" and metadata["ai_used"] is True
    assert calls == [sheet]
    assert untimed.resolve(source, "Song", "Artist")[1]["ai_used"] is True
    assert len(calls) == 1


def test_plain_lyric_audit_distinguishes_source_error_and_missing_original(monkeypatch):
    audit = SourceAudit()
    sites = LyricSites(None, audit=audit)
    def animelyrics(*a, **k):
        raise RuntimeError("site unavailable")
    def animesonglyrics(*a, **k):
        return Sheet("Song", "Artist", "url", [], ["roman"])
    monkeypatch.setattr(sites, "animelyrics", animelyrics)
    monkeypatch.setattr(sites, "animesonglyrics", animesonglyrics)
    assert sites.search("Song", "Artist", duration=90).original == []
    sources = audit.snapshot()["sources"]
    assert sources["animelyrics"]["error"] == 1
    assert sources["animesonglyrics"]["romaji_only"] > 0


def test_missing_lyric_placeholder_cannot_be_passed_to_recognition():
    assert clean_lines(["N/A", " n/a ", "Not available", "Kanji not available", "星の光"]) == ["星の光"]


def test_ruby_readings_are_not_duplicate_sung_lyrics():
    node = parse_html('<div><ruby>巡<rt>めぐ</rt></ruby>り'
                      '<ruby>逢<rp>(</rp><rt>あ</rt><rp>)</rp></ruby>いたい<br>君と</div>'.encode())
    assert text_lines(node, short=True) == ["巡り逢いたい", "君と"]


def test_identical_english_and_roman_columns_are_original_english():
    page = b'<h1>Song Lyrics</h1><p>Artist</p><div class="kanjilyrics-sbs">N/A</div>'
    page += b'<div class="romajilyrics-sbs">You shine</div><div class="englishlyrics-sbs">You shine</div>'
    http = SimpleNamespace(bytes=lambda url, **k: page if url.endswith('/anime/song') else
                           b'<a href="/anime/song">Song</a>')
    sheet = LyricSites(http).animesonglyrics("Song", "Artist", True)
    assert sheet.original == ["You shine"]


def test_tv_native_projection_uses_text_only_and_keeps_unmatched_version():
    from karaoke.lyric_versions import native_version
    native = ["kimi wa", "sora wo", "mitsumete", "future verse unrelated text"]
    assert native_version(native, ["kimi wa", "sora wo", "mitsumete"]) == native[:3]
    assert native_version(native, ["entirely different unrelated lyrics"]) == native


def test_japanese_readings_match_equivalent_kanji_and_kana_without_filling_times():
    from karaoke.asr_phrases import phrases
    from karaoke.lyric_versions import phonetic_key
    words = [{"word": "心を", "start": 2, "end": 3},
             {"word": "つなぐ", "start": 3, "end": 4},
             {"word": "強い", "start": 4, "end": 5},
             {"word": "絆", "start": 5, "end": 6}]
    rows = phrases([{"words": words}], ["心を繋ぐ強い絆"], normalizer=phonetic_key)
    assert len(rows) == 1 and (rows[0]["start"], rows[0]["end"]) == (2, 6)
    assert phrases([{"words": words}], ["世界に知らない歌"], normalizer=phonetic_key) == []


def test_plain_uta_net_fallback_does_not_repeat_all_discovery_queries(monkeypatch):
    from karaoke.uta_net import UtaNet
    sites = LyricSites(None)
    monkeypatch.setattr(sites, "animelyrics", lambda *a, **k: None)
    monkeypatch.setattr(sites, "animesonglyrics", lambda *a, **k: None)
    calls = []
    def search(self, title, artist, context=None):
        calls.append((title, artist))
        return Sheet(title, artist, "https://www.uta-net.com/global/en/lyric/1/",
                     ["native"], ["roman"])
    monkeypatch.setattr(UtaNet, "search", search)
    assert sites.search("Song", "Artist", duration=90).original == ["native"]
    assert calls == [("Song", "Artist")]


def test_checkpoint_reuse_cannot_admit_authored_or_incomplete_twenty_second_clips():
    from tools.karaoke_checkpoint_reuse import confirmed
    proof = dict(ai_used=True, authored_timing_sources_excluded=True,
                 timing_origin="source_audio_asr", lyrics_url="https://www.animesonglyrics.com/song",
                 confirmed_excerpt=[10, 40], selected_lyric_indices=[2, 3, 4],
                 aligned_lyrics_lines=3, crop_start=15, output_duration=20,
                 source_audio_sha256="source", original_lyrics_sha256="lyrics", duration=90,
                 recording={"aligned_to_source_sha256": "source"})
    assert confirmed(proof, 20)
    assert not confirmed(dict(proof, ai_used=False, source="Karaoke Mugen"), 20)
    assert not confirmed(dict(proof, crop_start=25), 20)
    assert not confirmed(dict(proof, selected_lyric_indices=[2, 4, 5]), 20)
    assert not confirmed(dict(proof, aligned_lyrics_lines=2), 20)
    assert not confirmed(dict(proof, duration=33), 20)
    assert not confirmed(dict(proof, recording={"aligned_to_source_sha256": "another"}), 20)
