# -*- coding: utf-8 -*-
"""Варианты ответа и независимые ветки Science Adventure."""
import animepack as ap

from si_hyx_parts.animepack.popular_franchise_title import (
    popular_franchise_title,
)


def _card(ident, title, viewers, franchise="science_adventure"):
    return {
        "id": str(ident), "malId": str(ident), "russian": title,
        "name": title, "kind": "tv", "franchise": franchise,
        "airedOn": {"year": 2011}, "score": 8.0,
        "statusesStats": [{"status": "completed", "count": viewers}],
    }


def test_science_adventure_titles_keep_their_own_popularity_and_key():
    gate = _card(9253, "Врата Штейна", 200_000)
    gate_zero = _card(30484, "Врата Штейна 0", 100_000)
    robotics = _card(13599, "Записки о робототехнике", 10_000)
    parts = [gate, gate_zero, robotics]

    assert ap.franchise_key(gate) != ap.franchise_key(robotics)
    assert ap.franchise_branch_parts(robotics, parts) == [robotics]
    assert ap.branch_franchise_index(robotics, parts) < 50_000
    assert ap.branch_franchise_index(gate, parts) > 50_000


def test_popular_answer_uses_index_within_the_same_series():
    earlier = _card(1, "Врата Штейна 0", 100)
    popular = _card(2, "Врата Штейна", 5000)
    robotics = _card(3, "Записки о робототехнике", 100_000)
    assert popular_franchise_title(earlier, [earlier, popular, robotics]) == (
        "Врата Штейна")
    cand = ap.SongCandidate({}, earlier, popular_franchise_title=
                            popular_franchise_title(earlier, [earlier, popular]))
    assert cand.answer_variants()[0] == cand.main_answer
    assert "Врата Штейна" in cand.answer_variants()


def test_plot_title_explanation_is_first_and_contains_title():
    cand = ap.SongCandidate({}, _card(9253, "Врата Штейна", 200_000),
                            kind=ap.PLOT_KIND)
    cand.plot_explanation = "Герой отправляет сообщение в прошлое."
    answers = cand.answer_variants()
    assert answers[0].startswith("Врата Штейна — ")
    assert cand.main_answer in answers
