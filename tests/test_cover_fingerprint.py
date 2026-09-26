# -*- coding: utf-8 -*-
"""Отпечаток записи: не играет ли внутри кавера сам оригинал.

Синтетика, как и в test_cover_audio: ровный синтезатор — это «та же самая
запись», а та же последовательность с затуханием у каждой ноты — «сыграли
заново». Числа порога калиброваны на настоящих роликах
(tools/cover_inside_probe.py), здесь проверяются свойства, на которых порог
держится.
"""
import numpy as np
import pytest

import cover_audio as audio
import cover_fingerprint as fingerprint
import cover_match as match
from test_cover_audio import ROOTS, _played, _tune


def _inside(ref, cover):
    ref_points, _frames = fingerprint.marks(ref)
    cover_points, frames = fingerprint.marks(cover)
    return fingerprint.inside(ref_points, cover_points, frames)


# ── созвездие ────────────────────────────────────────────────────────────
def test_marks_are_sparse_peaks_inside_the_band():
    points, frames = fingerprint.marks(_tune(ROOTS))
    assert points.ndim == 2 and points.shape[1] == 2
    assert frames > 0 and 0 < len(points) < frames * 5
    assert points[:, 0].max() < frames


def test_marks_survive_silence_and_a_signal_shorter_than_a_frame():
    for sound in (np.zeros(100, dtype=np.float32),
                  np.zeros(fingerprint.N_FFT * 4, dtype=np.float32)):
        points, frames = fingerprint.marks(sound)
        assert points.shape[1] == 2 and frames >= 0


def test_pairs_are_built_from_neighbours_in_time():
    points, _frames = fingerprint.marks(_tune(ROOTS[:4]))
    keys, starts = fingerprint.pairs(points)
    assert len(keys) == len(starts) and len(keys) > 0
    assert keys.dtype == np.int64 and (starts >= 0).all()


@pytest.mark.parametrize("empty", [None, [], np.empty((0, 2), dtype=np.int64)])
def test_an_empty_constellation_says_nothing(empty):
    """Молчащий признак — не повод выбросить кавер."""
    points, frames = fingerprint.marks(_tune(ROOTS))
    assert fingerprint.inside(empty, points, frames) == (False, 0.0)
    assert fingerprint.inside(points, empty, frames) == (False, 0.0)


# ── сам вердикт ──────────────────────────────────────────────────────────
def test_the_very_same_recording_is_caught():
    caught, score = _inside(_tune(ROOTS), _tune(ROOTS))
    assert caught and score > fingerprint.MAX_OVERLAP * 10


def test_the_same_music_played_again_is_not_caught():
    """Тот же самый набор аккордов, но сыгранный: отпечаток расходится."""
    caught, score = _inside(_tune(ROOTS), _played(ROOTS))
    assert not caught and score < fingerprint.MAX_OVERLAP


def test_the_chroma_still_calls_the_played_version_the_same_song():
    """Признаки отвечают на РАЗНЫЕ вопросы и не должны подменять друг друга."""
    verdict = match.verify(audio.chroma(_tune(ROOTS)),
                           audio.chroma(_played(ROOTS)), want=5)
    assert verdict["ok"] and verdict["norm"] >= match.MIN_SCORE


def test_a_different_song_matches_nothing():
    caught, score = _inside(_tune(ROOTS), _played([61, 63, 66, 70] * 3))
    assert not caught and score < fingerprint.MAX_OVERLAP


def test_the_threshold_is_read_from_the_shared_place():
    assert match.original_inside(fingerprint.MAX_OVERLAP + 0.01)
    assert not match.original_inside(fingerprint.MAX_OVERLAP)
    assert not match.original_inside(None)
