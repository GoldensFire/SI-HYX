"""Без AI караоке сначала узнаёт, есть ли готовые тайминги, и только потом качает."""
from types import SimpleNamespace

import animepack as ap
from karaoke.model import Track
from karaoke.resolver import Resolver
from si_hyx_parts.animepack import karaoke_processing


def _resolver(tmp_path, tracks, paired=False, broken=False):
    resolver = Resolver(None, ap.PackSettings(karaoke_ai_fallback=False), "ffmpeg", None,
                        cache=tmp_path)

    def search(*a, **k):
        if broken:
            raise OSError("сеть")
        return tracks

    resolver.providers = [SimpleNamespace(search=search)]
    resolver.paired.available = lambda *a: paired
    return resolver


def test_any_matching_title_and_artist_is_enough_to_try(tmp_path):
    other = Track("Other", ["Artist"], 90, "KM", "ass", "audio")
    same = Track("Song", ["Artist"], 90, "KM", "ass", "audio")
    assert _resolver(tmp_path, [other]).authored_available("Song", "Artist") is False
    assert _resolver(tmp_path, [other, same]).authored_available("Song", "Artist") is True
    assert _resolver(tmp_path, [], paired=True).authored_available("Song", "Artist") is True


def test_unanswered_source_is_not_a_proof_of_absence(tmp_path):
    assert _resolver(tmp_path, [], broken=True).authored_available("Song", "Artist") is None


def test_song_without_timings_is_skipped_before_download(tmp_path):
    resolver = _resolver(tmp_path, [])
    cancelled = []
    candidate = ap.SongCandidate(
        song={"songName": "Song", "songArtist": "Artist", "audio": "a.mp3", "songType": 1},
        anime={"malId": 1, "name": "Anime"}, kind="opening")
    candidate._audio_download = SimpleNamespace(cancel=lambda: cancelled.append(True))
    logs = []
    generator = SimpleNamespace(
        s=ap.PackSettings(karaoke_enabled=True, karaoke_ai_fallback=False),
        karaoke_resolver=resolver, log=logs.append, _timed=lambda _stage: _Null())
    assert karaoke_processing.authored_timings_possible(generator, candidate) is False
    assert cancelled == [True] and candidate._audio_download is None
    assert karaoke_processing.known_rejection(generator, candidate)


class _Null:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False
