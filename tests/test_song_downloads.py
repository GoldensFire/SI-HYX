"""The next source loads while a single selection worker encodes the first."""
import threading

import animepack as ap
from si_hyx_parts.animepack.song_downloads import source_bytes
from test_animepack_mixed_streams import _generator, make_anime, make_song


def test_selection_overlaps_next_download_with_encoding_at_parallel_one(tmp_path, monkeypatch):
    gen = _generator(tmp_path, monkeypatch, [], [], pct_songs=100, pct_frames=0,
                     questions=2, parallel=1, karaoke_enabled=True, karaoke_percent=100)
    monkeypatch.setattr(gen, "iter_candidates", lambda: (
        ap.SongCandidate(make_song(i), make_anime(i), kind="opening") for i in (1, 2)))
    encoding, next_download = threading.Event(), threading.Event()
    downloaded = []

    def download(url, *args):
        downloaded.append(url)
        if "2.mp3" in url:
            assert encoding.wait(5)
            next_download.set()
        return b"audio"

    def fetch(candidate):
        assert source_bytes(gen, candidate) == b"audio"
        if candidate.mal_id == 1:
            with gen._runtime.encoding():
                encoding.set()
                assert next_download.wait(5), "Загрузка второй песни ждала кодировщика"
        return True

    monkeypatch.setattr(gen, "_cached_bytes", download)
    monkeypatch.setattr(gen, "_fetch_media", fetch)
    assert len(gen.select_songs()) == 2
    assert len(downloaded) == 2
    assert gen._song_downloads is None


def test_known_rejection_skips_source_download_even_when_crop_changes(tmp_path, monkeypatch):
    from si_hyx_parts.animepack.karaoke_processing import download_karaoke, rejection_key
    gen = _generator(tmp_path, monkeypatch, [], [], karaoke_enabled=True)
    candidate = ap.SongCandidate(make_song(1), make_anime(1), kind="opening", music_effect="karaoke")
    from karaoke.rejections import Rejections
    gen.karaoke_resolver.rejections = Rejections(tmp_path)
    gen.karaoke_resolver.rejections.put(rejection_key(gen, candidate, source=True), "wrong recording")
    candidate.trim_start = 30
    def unexpected(*args):
        raise AssertionError("Rejected song must not download again")
    monkeypatch.setattr(gen, "_cached_bytes", unexpected)
    assert not download_karaoke(gen, candidate)


def test_transient_resolver_failure_does_not_reject_source(tmp_path, monkeypatch):
    from si_hyx_parts.animepack.karaoke_processing import download_karaoke
    from karaoke.rejections import Rejections
    gen = _generator(tmp_path, monkeypatch, [], [], karaoke_enabled=True)
    gen.folder = str(tmp_path)
    gen.karaoke_resolver.rejections = Rejections(tmp_path)
    monkeypatch.setattr(gen, "_cached_bytes", lambda *a: b"a" * 50000)
    def failure(*args):
        raise ValueError("Provider temporarily unavailable")
    monkeypatch.setattr(gen.karaoke_resolver, "resolve", failure)
    candidate = ap.SongCandidate(make_song(1), make_anime(1), kind="opening", music_effect="karaoke")
    assert not download_karaoke(gen, candidate)
    assert not list(gen.karaoke_resolver.rejections.root.glob("*.json"))
