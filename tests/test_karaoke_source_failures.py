"""Broken reference media must not poison the verified or weekly reject caches."""
from types import SimpleNamespace

import numpy as np
import pytest

import animepack as ap
from karaoke.http import Http, MediaUnavailable
from karaoke.model import Track
from karaoke.resolver import Resolver
from test_karaoke_timing import ASS


class Response:
    headers = {}
    def __init__(self, body):
        self.body = body
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def raise_for_status(self):
        pass
    def iter_content(self, size):
        yield self.body


def test_html_in_audio_cache_is_refetched_and_bad_response_is_not_cached(tmp_path):
    calls = []
    session = SimpleNamespace(get=lambda *a, **k: calls.append(k) or Response(b"RIFF recording"))
    http = Http(session, cache=tmp_path)
    assert http.bytes("audio") == b"RIFF recording"
    cached = next(tmp_path.iterdir())
    cached.write_bytes(b"<!doctype html><html>error</html>")
    assert http.bytes("audio", media=True) == b"RIFF recording"
    assert len(calls) == 2 and calls[-1]["timeout"] == (5, 10)
    http.invalidate("audio")
    session.get = lambda *a, **k: Response(b'{"error":"expired"}')
    with pytest.raises(MediaUnavailable):
        http.bytes("audio", media=True)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("reason", ["Не удалось прочитать аудио: broken", "Аудио слишком короткое или повреждено."])
def test_decode_failure_and_temporary_skip_never_reject_song_for_week(tmp_path, monkeypatch, reason):
    import karaoke.resolver as module
    source = tmp_path / "source.mp3"
    source.write_bytes(b"source")
    resolver = Resolver(None, ap.PackSettings(karaoke_ai_fallback=False), "ffmpeg", None, cache=tmp_path)
    resolver.providers = [SimpleNamespace(search=lambda *a: [Track("Song", ["Artist"], 40, "KM", "ass", "audio")])]
    resolver.paired.resolve = lambda *a: None
    calls, invalidated = [], []
    resolver.http.bytes = lambda url, **k: ASS.encode() if url == "ass" else b"broken"
    resolver.http.invalidate = invalidated.append
    def decode(path, *args):
        if path == source:
            return np.zeros(40 * 22050)
        calls.append(1)
        raise ValueError(reason)
    monkeypatch.setattr(module, "decode", decode)
    for _ in range(2):
        with pytest.raises(ValueError):
            resolver.resolve(source, "Song", "Artist")
    assert calls == [1] and invalidated == ["audio"]
    assert not list(resolver.rejections.root.glob("*.json"))
