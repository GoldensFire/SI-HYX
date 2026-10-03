"""Reject only the offending recording; expire at one week without extending."""
from types import SimpleNamespace

import numpy as np
import pytest

import animepack as ap
from karaoke.model import Track
from karaoke.rejections import Rejections, TTL, cache_key
from karaoke.resolver import Resolver
from test_karaoke_timing import ASS


def test_weekly_expiry_is_not_extended_by_reads_or_repeated_rejection(tmp_path):
    now = [1000]
    cache = Rejections(tmp_path, clock=lambda: now[0])
    key = cache_key("recording")
    cache.put(key, "wrong version")
    now[0] += TTL - 1
    cache.put(key, "wrong version again")
    assert cache.get(key) == "wrong version"
    now[0] += 1
    assert not cache.get(key)
    assert not list(cache.root.glob("*.json"))


def test_opening_cache_removes_expired_and_corrupted_entries(tmp_path):
    cache = Rejections(tmp_path, clock=lambda: 100)
    cache.put("old", "old")
    (cache.root / "broken.json").write_text("broken", encoding="utf-8")
    Rejections(tmp_path, clock=lambda: 100 + TTL)
    assert not list(cache.root.glob("*.json"))


def test_wrong_reference_is_skipped_on_retry_but_new_recording_is_checked(tmp_path, monkeypatch):
    import karaoke.resolver as module
    source = tmp_path / "source.mp3"
    source.write_bytes(b"recording")
    resolver = Resolver(None, ap.PackSettings(karaoke_ai_fallback=False), "ffmpeg", None, cache=tmp_path)
    track = Track("Song", ["Artist"], 40, "KM", "ass", "audio")
    resolver.providers = [SimpleNamespace(search=lambda *a: [track])]
    monkeypatch.setattr(resolver.http, "bytes", lambda url, **k: ASS.encode() if url == "ass" else b"audio")
    monkeypatch.setattr(module, "decode", lambda *a: np.zeros(40 * 22050))
    calls = []
    def verify(*args):
        calls.append(1)
        raise ValueError("wrong recording")
    monkeypatch.setattr(module, "verify_audio", verify)
    for _ in range(2):
        with pytest.raises(ValueError):
            resolver.resolve(source, "Song", "Artist")
    assert len(calls) == 1
    source.write_bytes(b"new recording")
    with pytest.raises(ValueError):
        resolver.resolve(source, "Song", "Artist")
    assert len(calls) == 2


def test_transient_provider_failure_is_never_remembered(tmp_path, monkeypatch):
    import karaoke.resolver as module
    source = tmp_path / "source.mp3"
    source.write_bytes(b"recording")
    resolver = Resolver(None, ap.PackSettings(karaoke_ai_fallback=False), "ffmpeg", None, cache=tmp_path)
    calls = []
    def search(*args):
        calls.append(1)
        raise ConnectionError("temporary outage")
    resolver.providers = [SimpleNamespace(search=search)]
    monkeypatch.setattr(module, "decode", lambda *a: np.zeros(40 * 22050))
    for _ in range(2):
        with pytest.raises(ValueError):
            resolver.resolve(source, "Song", "Artist")
    assert len(calls) == 2
    assert not list(resolver.rejections.root.glob("*.json"))
