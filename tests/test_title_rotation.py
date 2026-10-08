# -*- coding: utf-8 -*-
"""Части франшизы: ответвления не наследуют узнаваемость серии целиком,
франшиза выбирается раньше части, недавние части уступают другим."""
import random
from collections import Counter

import animepack as ap
from si_hyx_parts.animepack import franchise_part_weight, title_rotation


def _stats(watching):
    return [{"status": "completed", "count": watching}]


def _card(mal, kind="tv", franchise="overlord", watched=1000, episodes=12):
    return {"malId": mal, "id": mal, "kind": kind, "franchise": franchise,
            "episodes": episodes, "statusesStats": _stats(watched),
            "airedOn": {"year": 2018}, "score": 7.5, "russian": f"T{mal}",
            "name": f"T{mal}"}


def test_side_story_does_not_inherit_the_whole_franchise_index():
    movie = ap.SongCandidate(song={}, anime=_card(1, kind="movie", watched=2000),
                             franchise_index=900000.0)
    season = ap.SongCandidate(song={}, anime=_card(2, kind="tv", watched=2000),
                              franchise_index=900000.0)
    assert season.screen_index == 900000.0
    assert movie.own_index < movie.screen_index < season.screen_index
    assert movie.level > season.level


def test_long_ona_is_main_story_and_short_ona_is_a_special():
    assert franchise_part_weight.is_main_part({"kind": "ona", "episodes": 12})
    assert not franchise_part_weight.is_main_part({"kind": "ona", "episodes": 2})
    assert not franchise_part_weight.is_main_part({"kind": "special"})


def test_franchise_gets_one_place_per_round_regardless_of_its_parts():
    cards = {i: _card(i, kind="movie") for i in range(1, 11)}      # 10 частей
    cards[100] = _card(100, franchise="solo")
    firsts = Counter()
    for seed in range(400):
        order = title_rotation.franchise_first(list(cards), cards, random.Random(seed),
                                               {"seq": 0, "titles": {}})
        firsts["solo" if order[0] == 100 else "overlord"] += 1
        assert sorted(order) == sorted(cards)
        assert 100 in order[:2]                    # первый круг — по одной части
    assert 120 < firsts["solo"] < 280


def test_main_seasons_outweigh_side_stories():
    cards = {1: _card(1, kind="tv"), 2: _card(2, kind="movie"), 3: _card(3, kind="special")}
    picks = Counter(title_rotation.franchise_first(
        [1, 2, 3], cards, random.Random(seed), {"seq": 0, "titles": {}})[0]
        for seed in range(600))
    assert picks[1] > picks[2] + picks[3]


def test_recently_used_part_gives_way_to_another_season(tmp_path):
    cards = {1: _card(1), 2: _card(2)}
    song = ap.SongCandidate(song={}, anime=cards[1], kind=ap.FRAME_KIND)
    assert title_rotation.record([song]) == 1
    history = title_rotation.load()
    assert history["titles"]["1"]["seq"] == 1
    picks = Counter(title_rotation.franchise_first([1, 2], cards, random.Random(seed),
                                                   history)[0]
                    for seed in range(600))
    assert picks[2] > 3 * picks[1]
    # Через несколько паков часть снова на равных.
    assert title_rotation.recency(history["titles"]["1"], 8) > 0.95
