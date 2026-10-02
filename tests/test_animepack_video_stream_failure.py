# -*- coding: utf-8 -*-
"""An interrupted AnimeThemes stream cannot become a finished quiz video."""
from pathlib import Path

import animepack as ap
from animepack import SongCandidate
from test_animepack_manga_sakuga import generator, make_anime  # noqa: F401


def _candidate():
    return SongCandidate({"songType": "Opening 1"}, make_anime(),
                         kind=ap.VIDEO_KIND)


def test_large_partial_video_is_removed_and_falls_back_to_audio(generator, monkeypatch):
    gen = generator
    monkeypatch.setattr(gen, "_theme_video", lambda c: "https://v/op.webm")
    monkeypatch.setattr(gen, "_video_start", lambda *a: 20)
    monkeypatch.setattr(ap.time, "sleep", lambda *a: None)
    commands, logs = [], []
    gen.log = logs.append

    def run(cmd, timeout=0):
        commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"x" * (ap.MIN_VIDEO_BYTES + 1))
        return 0, "[matroska,webm] File ended prematurely"

    monkeypatch.setattr(gen, "_run_killable", run)
    cand = _candidate()
    assert gen.download_video(cand) is False
    assert len(commands) == ap.VIDEO_RETRIES + 1
    assert not cand.has_video
    assert not Path(commands[-1][-1]).exists()
    assert "поток AnimeThemes оборвался" in logs[-1]
    assert "беру аудио песни" in logs[-1]


def test_complete_retry_is_accepted(generator, monkeypatch):
    gen = generator
    monkeypatch.setattr(gen, "_theme_video", lambda c: "https://v/op.webm")
    monkeypatch.setattr(gen, "_video_start", lambda *a: 20)
    monkeypatch.setattr(ap.time, "sleep", lambda *a: None)
    errors = iter(["File ended prematurely", ""])
    commands = []

    def run(cmd, timeout=0):
        commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"x" * (ap.MIN_VIDEO_BYTES + 1))
        return 0, next(errors)

    monkeypatch.setattr(gen, "_run_killable", run)
    cand = _candidate()
    assert gen.download_video(cand)
    assert cand.has_video and len(commands) == 2
