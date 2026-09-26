# -*- coding: utf-8 -*-
"""Политика выбора кавера: разнообразие против «того же места песни».

Числа здесь — свойства, которые держит замер на 52 разыгранных паках
(tools/cover_select_probe.py): все 7.2 подтверждённых кавера песни успевают
прозвучать, типов в паке 6.0 против 5.3 у равновероятного выбора, повторов
подряд ноль, а в запрошенное генератором место попадает 0.954 отрезков.
"""
import random

import cover_match as match
import cover_select as select


def _windows(spots, density=0.9):
    return [{"at": float(at), "density": density,
             "cover": (float(at) + 5.0, float(at) + 25.0)} for at in spots]


def _row(vid="a", norm=6.0, kind="vocal", spots=(0, 20, 40), used=(),
         last_used=0.0, strength="strong"):
    return {"id": vid, "norm": norm, "type": kind, "strength": strength,
            "windows": _windows(spots), "used": list(used),
            "last_used": last_used, "uses": len(used)}


NOW = 1_700_000_000.0


# ── веса ─────────────────────────────────────────────────────────────────
def test_confidence_grows_with_the_score_and_stops_at_the_cap():
    assert select.confidence(_row(norm=3.0)) == 1.0
    assert 1.0 < select.confidence(_row(norm=6.0)) < select.MAX_CONFIDENCE
    assert select.confidence(_row(norm=40.0)) == select.MAX_CONFIDENCE


def test_a_weak_candidate_starts_counting_from_its_own_stricter_floor():
    """Порог у назвавшего только аниме выше — значит и уверенность считается
    от него, иначе слабые кандидаты получали бы вес ни за что."""
    assert (select.confidence(_row(norm=4.0, strength="weak"))
            < select.confidence(_row(norm=4.0)))


def test_cooling_is_full_for_a_new_video_and_lowest_right_after_a_pack():
    assert select.cooling(_row(), NOW) == 1.0
    assert select.cooling(_row(last_used=NOW), NOW) == select.COLD_FLOOR
    old = NOW - select.COOLDOWN_DAYS * select.DAY
    assert select.cooling(_row(last_used=old), NOW) == 1.0


def test_a_type_already_in_the_pack_weighs_less():
    hot = select.weight(_row(kind="piano"), now=NOW, seen_types={"piano": 1})
    cold = select.weight(_row(kind="piano"), now=NOW, seen_types={})
    assert hot == cold / 2


def test_weight_never_reaches_zero_so_a_lone_cover_stays_reachable():
    lonely = _row(norm=3.0, last_used=NOW)
    assert select.weight(lonely, now=NOW, seen_types={"vocal": 9}) > 0


# ── выбор окна ───────────────────────────────────────────────────────────
def test_the_requested_spot_of_the_song_wins_over_the_used_window_filter():
    """Замер: фильтр занятых окон ПЕРЕД prefer ронял попадание с 0.942 до 0.621,
    прибавляя 0.2 участка из восьми. Отрезок оригинала и без того берётся со
    случайного места, поэтому здесь prefer всегда первый."""
    row = _row(spots=(0, 20, 40), used=(20.0,))
    assert select.window(row, rng=random.Random(1), prefer=20.0)["at"] == 20.0


def test_without_a_request_the_used_windows_are_avoided():
    row = _row(spots=(0, 20, 40), used=(0.0, 20.0))
    rng = random.Random(3)
    assert {select.window(row, rng=rng)["at"] for _ in range(20)} == {40.0}


def test_when_every_window_is_used_a_question_is_still_built():
    row = _row(spots=(0, 20), used=(0.0, 20.0))
    assert select.window(row, rng=random.Random(5))["at"] in (0.0, 20.0)


def test_a_far_away_request_falls_back_instead_of_cutting_the_wrong_part():
    row = _row(spots=(0, 20, 40))
    spot = select.window(row, rng=random.Random(7), prefer=90.0)
    assert spot and abs(spot["at"] - 90.0) > match.WINDOW_STEP


# ── выбор кавера ─────────────────────────────────────────────────────────
def test_nothing_to_choose_from_is_an_empty_answer_not_a_crash():
    assert select.pick([], now=NOW) == {}
    assert select.pick([_row(spots=())], now=NOW) == {}


def test_the_cut_is_reported_in_seconds_of_the_cover():
    got = select.pick([_row(spots=(20,))], rng=random.Random(1), now=NOW)
    assert (got["at"], got["length"], got["ref_at"]) == (25.0, 20.0, 20.0)
    assert got["id"] == "a"


def test_the_same_cover_never_goes_two_packs_in_a_row():
    rows = [_row("a"), _row("b")]
    rng = random.Random(11)
    picks = {select.pick(rows, rng=rng, now=NOW, skip="a")["id"]
             for _ in range(30)}
    assert picks == {"b"}


def test_but_a_lone_cover_is_better_than_no_question_at_all():
    got = select.pick([_row("a")], rng=random.Random(13), now=NOW, skip="a")
    assert got["id"] == "a"


def test_types_already_in_the_pack_come_up_less_often():
    rows = [_row("piano", kind="piano"), _row("vocal", kind="vocal")]
    rng = random.Random(17)
    seen = {"piano": 3}
    got = [select.pick(rows, rng=rng, now=NOW, seen_types=seen)["id"]
           for _ in range(400)]
    assert got.count("vocal") > got.count("piano") * 3


def test_a_cover_used_last_week_comes_up_less_often_than_an_untouched_one():
    rows = [_row("fresh"), _row("hot", last_used=NOW - 7 * select.DAY)]
    rng = random.Random(19)
    got = [select.pick(rows, rng=rng, now=NOW)["id"] for _ in range(400)]
    assert got.count("fresh") > got.count("hot") * 2


def test_every_confirmed_cover_of_a_song_eventually_gets_its_turn():
    """Случайно, а не top-1: иначе в каждом паке звучал бы один и тот же ролик."""
    rows = [_row("a", norm=12.0), _row("b", norm=4.0), _row("c", norm=6.0)]
    rng = random.Random(23)
    got = {select.pick(rows, rng=rng, now=NOW)["id"] for _ in range(200)}
    assert got == {"a", "b", "c"}
