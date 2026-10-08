"""Audit fixes through the real worker pool and recovery snapshot."""
import os
import threading
import zipfile
from types import SimpleNamespace

import animepack as ap
from storage_guard import StorageError
from si_hyx_parts.animepack import song_downloads, karaoke_processing
from test_animepack_mixed_streams import _generator, make_anime
from test_karaoke_precheck import _resolver, _Null


def test_disk_failure_during_selection_keeps_accepted_question(tmp_path, monkeypatch):
    gen = _generator(tmp_path, monkeypatch, [], [], questions=2, pct_songs=0, pct_frames=100)
    gen.s.validate = lambda: []
    monkeypatch.setattr(gen, "load_exclusions", lambda: None)
    accepted = threading.Event()
    gen._progress = lambda done, *_: accepted.set() if done == 1 else None
    def candidates():
        yield ap.SongCandidate({}, make_anime(1), kind=ap.FRAME_KIND)
        assert accepted.wait(5)
        yield ap.SongCandidate({}, make_anime(2), kind=ap.FRAME_KIND)
    def fetch(candidate):
        if candidate.mal_id == 2:
            raise StorageError(gen.folder, 256 << 20, 80 << 20)
        candidate.frame_name, candidate.has_frame = "ready.jpg", True
        with open(os.path.join(gen.folder, "Images", "ready.jpg"), "wb") as target:
            target.write(b"accepted image")
        return True
    monkeypatch.setattr(gen, "iter_candidates", candidates)
    monkeypatch.setattr(gen, "_fetch_media", fetch)
    # Продолжать нельзя: принятый вопрос сразу пишется аварийным паком.
    result = gen.run(str(tmp_path / "pack.siq"))
    assert result.aborted and result.path
    assert [c.mal_id for c in result.songs] == [1]
    assert any("Освободите место" in w for w in result.warnings)
    with zipfile.ZipFile(result.path) as package:
        assert package.read("Images/ready.jpg") == b"accepted image"


def test_karaoke_prefetch_does_not_download_before_timing_precheck(monkeypatch):
    candidate = ap.SongCandidate({"audio": "song.mp3"}, make_anime(1), kind="opening")
    candidate.music_effect = "karaoke"
    generator = SimpleNamespace(s=ap.PackSettings(karaoke_enabled=True, karaoke_ai_fallback=False))
    def unexpected(*args):
        raise AssertionError("Audio must wait for the authored timing precheck")
    monkeypatch.setattr(song_downloads, "SongDownloads", unexpected)
    song_downloads.prefetch(generator, candidate)
    assert getattr(candidate, "_audio_download", None) is None


def test_unanswered_timing_source_defers_song_without_negative_cache(tmp_path):
    resolver = _resolver(tmp_path, [], broken=True)
    settings = ap.PackSettings(karaoke_enabled=True, karaoke_ai_fallback=False)
    generator = SimpleNamespace(s=settings, folder=str(tmp_path), karaoke_resolver=resolver,
        stopped=lambda: False, log=lambda _: None, _timed=lambda _: _Null())
    candidate = ap.SongCandidate({"songName": "Song", "songArtist": "Artist", "audio": "a.mp3"},
                                 make_anime(1), kind="opening")
    assert not karaoke_processing.download_karaoke(generator, candidate)
    assert candidate._music_temporary
    assert not karaoke_processing.known_rejection(generator, candidate)
