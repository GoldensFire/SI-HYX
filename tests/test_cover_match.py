# -*- coding: utf-8 -*-
"""Решение по кандидату: та ли композиция и какие двадцать секунд резать.

Синтетика, как и в test_cover_audio: ни сети, ни ffmpeg. Числовые пороги
калиброваны на настоящих записях (tools/cover_audio_probe.py), здесь проверяются
СВОЙСТВА, от которых эти числа зависят, и разобранные на стенде случаи.
"""
import random

import numpy as np
import pytest

import cover_audio as audio
import cover_match as match
from test_cover_audio import ROOTS, _tune


def _pair(cover_roots=None, seconds=1.5, lead=()):
    """(хрома эталона, хрома кавера); lead — чужой кусок перед совпадением."""
    reference = audio.chroma(_tune(ROOTS))
    parts = [_tune(list(lead))] if lead else []
    parts.append(_tune(cover_roots or ROOTS, seconds=seconds))
    return reference, audio.chroma(np.concatenate(parts))


# ── пороги и мера близости ───────────────────────────────────────────────
def test_weak_candidates_are_held_to_a_stricter_threshold():
    """У кандидата, назвавшего только аниме, тождество доказывает один звук."""
    assert match.floor_for("weak") > match.floor_for("strong")
    assert match.floor_for("") == match.MIN_SCORE


def test_normalized_score_scales_with_reference_length():
    """Нормировка на корень длины: вдвое длиннее эталон — вдвое ниже цена очка
    случайного совпадения, а не вчетверо."""
    assert match.normalized(60, 400) == pytest.approx(3.0, abs=0.01)
    assert match.normalized(120, 1600) == pytest.approx(3.0, abs=0.01)


def test_closeness_grows_with_the_score_and_drops_on_transposition():
    far = match.closeness(match.CLOSE_LOW)
    near = match.closeness(match.CLOSE_HIGH)
    assert far == 0.0 and near == 1.0
    assert 0.0 < match.closeness(8.0) < 1.0
    # Другая тональность и другой темп узнаются хуже — это и есть сложность.
    assert match.closeness(8.0, shift=3) < match.closeness(8.0)
    assert match.closeness(8.0, tempo=1.3) < match.closeness(8.0)
    assert match.closeness(8.0, shift=12) == match.closeness(8.0, shift=0)
    assert match.closeness(100.0) == 1.0 and match.closeness(-5.0) == 0.0


# ── окна ─────────────────────────────────────────────────────────────────
def test_windows_cover_the_reference_and_carry_cover_times():
    reference, cover = _pair()
    result = audio.align(reference, cover)
    found = match.windows(result["path"], len(reference) / audio.FPS, want=8.0)
    assert found, "у самосовпадения обязаны найтись окна"
    assert all(w["density"] >= match.MIN_DENSITY for w in found)
    assert all(w["cover"][1] > w["cover"][0] for w in found)
    # Окна идут по эталону слева направо с шагом WINDOW_STEP.
    assert found[0]["at"] == 0.0
    assert found[1]["at"] == pytest.approx(match.WINDOW_STEP)
    assert match.windows([], 90.0) == []


def test_choose_prefers_the_window_the_generator_asked_for():
    good = [{"at": 0.0, "density": 0.9, "cover": (0.0, 20.0)},
            {"at": 30.0, "density": 0.6, "cover": (31.0, 51.0)}]
    assert match.choose(good, prefer=30.0)["at"] == 30.0
    # Просили место, где окна нет вовсе — берём из годных.
    assert match.choose(good, random.Random(1), prefer=300.0)["at"] in (0.0, 30.0)
    assert match.choose([], prefer=0.0) == {}


def test_choice_is_reproducible_with_a_seeded_generator():
    good = [{"at": float(n), "density": 0.9, "cover": (n, n + 20.0)}
            for n in range(40)]
    first = [match.choose(good, random.Random(5))["at"] for _ in range(6)]
    second = [match.choose(good, random.Random(5))["at"] for _ in range(6)]
    assert first == second
    # И при этом не всегда одно и то же окно: паку нужен разный кусок.
    assert len({match.choose(good, random.Random(n))["at"] for n in range(12)}) > 1


# ── вердикт ──────────────────────────────────────────────────────────────
def test_same_tune_is_accepted_with_a_window():
    reference, cover = _pair()
    verdict = match.verify(reference, cover, want=8.0, rng=random.Random(3))
    assert verdict["ok"] and verdict["reason"] == ""
    assert verdict["norm"] >= match.MIN_SCORE
    assert verdict["windows"] > 0 and verdict["density"] >= match.MIN_DENSITY
    assert 4.0 < verdict["length"] < 14.0
    assert 0.0 <= verdict["closeness"] <= 1.0


def test_unrelated_noise_is_rejected_as_a_different_song():
    reference = audio.chroma(_tune(ROOTS))
    rng = np.random.default_rng(11)
    noise = audio.chroma(rng.standard_normal(
        len(reference) * audio.HOP * audio.DOWN).astype(np.float32))
    verdict = match.verify(reference, noise, want=8.0)
    assert not verdict["ok"] and verdict["reason"] == "not_the_song"
    # Счёт всё равно сообщается: по нему вкладка объясняет отказ.
    assert verdict["score"] >= 0.0


def test_missing_audio_is_reported_and_not_a_match():
    reference = audio.chroma(_tune(ROOTS))
    for empty in (None, np.zeros((0, 12), dtype=np.float32)):
        verdict = match.verify(reference, empty)
        assert not verdict["ok"] and verdict["reason"] == "no_audio"


def test_window_lands_inside_the_matching_part_of_a_long_cover():
    """Главный случай стенда: эталон TV-size, кавер — полная версия. На
    настоящих записях окно уезжало с начала файла у 64 каверов из 74."""
    lead = [61, 63, 66, 68, 70, 61, 63, 66]
    reference, cover = _pair(lead=lead)
    verdict = match.verify(reference, cover, want=8.0, rng=random.Random(2))
    assert verdict["ok"]
    # Вступление кавера (8 аккордов по 1.5 с) в окно попасть не должно.
    assert verdict["at"] > len(lead) * 1.5 * 0.6
