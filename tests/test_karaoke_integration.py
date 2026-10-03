"""Priority chain, no-AI authored timing path, cache and presentation shares."""
from types import SimpleNamespace

import numpy as np
import pytest

import animepack as ap
from karaoke.model import Track
from karaoke.resolver import Resolver
from karaoke.lyrics import Sheet, add_translations, parse_html, text_lines
from karaoke.ass import read_ass
from music_effects import EffectSlots
from test_karaoke_timing import ASS


def test_authored_ass_skips_amll_and_models_and_reuses_verified_cache(tmp_path, monkeypatch):
    import karaoke.resolver as module
    import karaoke.fallback as fallback
    source = tmp_path / "source.mp3"
    source.write_bytes(b"source-recording")
    resolver = Resolver(None, ap.PackSettings(karaoke_ai_fallback=True), "ffmpeg", None, cache=tmp_path)
    calls = []
    class Provider:
        def __init__(self, name):
            self.name = name
        def search(self, *_):
            calls.append(self.name)
            return [Track("Song", ["Artist"], 40, self.name, "ass", "audio")]
    resolver.providers = [Provider("Karaoke Mugen"), Provider("AMLL")]
    monkeypatch.setattr(resolver.http, "bytes", lambda *a, **k: ASS.encode() if a[0] == "ass" else b"reference")
    monkeypatch.setattr(resolver.lyrics, "search", lambda *a, **k: None)
    monkeypatch.setattr(module, "decode", lambda *a: np.zeros(40 * 22050))
    monkeypatch.setattr(module, "verify_audio", lambda *a: {"offset": .1, "anchors": [1, 2, 3]})
    def unexpected(*a, **k):
        raise AssertionError("Authored timing must not load AI models")
    monkeypatch.setattr(fallback, "align", unexpected)
    lines, meta = resolver.resolve(source, "Song", "Artist")
    assert len(lines) == 1 and meta["ai_used"] is False
    assert calls == ["Karaoke Mugen"]
    resolver.providers = [SimpleNamespace(search=unexpected)]
    assert resolver.resolve(source, "Song", "Artist")[1] == meta


def test_ttml_priority_after_mugen_rejects_wrong_recording(tmp_path, monkeypatch):
    import karaoke.resolver as module
    source = tmp_path / "source.mp3"
    source.write_bytes(b"recording")
    resolver = Resolver(None, ap.PackSettings(karaoke_ai_fallback=False), "ffmpeg", None, cache=tmp_path)
    payload = b'<tt><body><p begin="1s" end="3s"><span begin="1s" end="3s">kimi</span></p></body></tt>'
    resolver.providers = [SimpleNamespace(search=lambda *a: [Track("Song", ["Artist"], 240, "KM", "ass", "audio")]),
                          SimpleNamespace(search=lambda *a: [Track("Song", ["Artist"], 40, "AMLL TTML", "ttml", "audio", "ttml")])]
    monkeypatch.setattr(resolver.http, "bytes", lambda *a, **k: payload if a[0] == "ttml" else b"audio")
    monkeypatch.setattr(resolver.lyrics, "search", lambda *a, **k: None)
    monkeypatch.setattr(module, "decode", lambda *a: np.zeros(40 * 22050))
    monkeypatch.setattr(module, "verify_audio", lambda *a: {"offset": 0, "anchors": [1, 2, 3]})
    assert resolver.resolve(source, "Song", "Artist")[1]["source"] == "AMLL TTML"


def test_translation_toggle_reuses_recording_cache_without_leaking_translation(tmp_path, monkeypatch):
    import karaoke.resolver as module
    source = tmp_path / "source.mp3"
    source.write_bytes(b"recording")
    settings = ap.PackSettings(karaoke_ai_fallback=False)
    resolver = Resolver(None, settings, "ffmpeg", None, cache=tmp_path)
    resolver.providers = [SimpleNamespace(search=lambda *a: [Track("Song", ["Artist"], 40, "KM", "ass", "audio")])]
    monkeypatch.setattr(resolver.http, "bytes", lambda url, **k: ASS.encode() if url == "ass" else b"audio")
    monkeypatch.setattr(module, "decode", lambda *a: np.zeros(40 * 22050))
    monkeypatch.setattr(module, "verify_audio", lambda *a: {"offset": 0})
    calls = []
    monkeypatch.setattr(resolver.lyrics, "search", lambda *a, **k: calls.append(1))
    assert not resolver.resolve(source, "Song", "Artist")[0][0].translations
    assert not calls
    settings.karaoke_translations = True
    assert resolver.resolve(source, "Song", "Artist")[0][0].translation == "Ты свет"
    assert len(calls) == 1
    settings.karaoke_translations = False
    assert not resolver.resolve(source, "Song", "Artist")[0][0].translations
    assert len(calls) == 1


def test_karaoke_slots_apply_to_all_song_types_and_never_silently_degrade():
    settings = ap.PackSettings(karaoke_enabled=True, karaoke_percent=100)
    slots = EffectSlots(settings, 24)
    assert slots.slots == ["karaoke"] * 24
    candidate = ap.SongCandidate({}, {}, kind="insert")
    slots.reserve(candidate)
    assert candidate.music_effect == "karaoke"
    with pytest.raises(RuntimeError, match="Караоке"):
        slots.quit("karaoke", "no verified timings")


def test_translation_mapping_does_not_guess_when_lines_are_split_differently():
    lines = read_ass(ASS)
    lines[0].translations = {}
    sheet = Sheet("Song", "Singer", "site", [], ["kimi wa"], {"en": ["You", "shine"]})
    add_translations(lines, sheet)
    assert not lines[0].translation
    sheet.translations = {"en": ["You shine"], "ru": ["Ты свет"]}
    add_translations(lines, sheet)
    assert lines[0].translation == "Ты свет"


def test_japanese_html_is_utf8_even_without_charset_metadata():
    document = parse_html('<div>強くなれる<br>君を連れて</div>'.encode())
    assert text_lines(document, short=True) == ["強くなれる", "君を連れて"]


def test_ui_settings_roundtrip_and_reverse_disables_recognition(qapp):
    import animepack_tab
    tab = animepack_tab.AnimePackTab()
    try:
        tab.chk_karaoke.setChecked(True)
        tab.sp_karaoke_percent.setValue(100)
        tab.cb_karaoke_effect.setCurrentIndex(tab.cb_karaoke_effect.findData("tempo"))
        tab.sp_karaoke_tempo.setValue(1.25)
        tab.sp_karaoke_crf.setValue(31)
        tab.sp_karaoke_preset.setValue(11)
        assert not tab.collect().karaoke_translations
        tab.chk_karaoke_translations.setChecked(True)
        settings = tab.get_settings()
        tab.apply_settings(settings)
        assert tab.collect().karaoke_enabled
        assert tab.collect().karaoke_tempo == 1.25
        assert tab.collect().karaoke_percent == 100
        assert tab.collect().karaoke_crf == 31
        assert tab.collect().karaoke_preset == 11
        assert tab.collect().karaoke_translations
        assert tab.collect().video_crf == settings["video_crf"]
        tab.cb_karaoke_effect.setCurrentIndex(tab.cb_karaoke_effect.findData("reverse"))
        assert not tab.chk_karaoke_ai.isEnabled()
    finally:
        tab.cleanup()
