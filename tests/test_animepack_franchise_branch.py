# -*- coding: utf-8 -*-
"""Shikimori-кроссовер не должен передавать популярность чужой серии."""
import animepack as ap


def _card(ident, title, completed):
    return {
        "id": ident, "malId": ident, "russian": title, "name": title,
        "kind": "tv", "franchise": "uchitama", "score": 5.95,
        "airedOn": {"year": 2014}, "releasedOn": {"year": 2015},
        "statusesStats": [{"status": "completed", "count": completed}],
    }


def test_neko_no_dayan_does_not_inherit_tamas_popularity():
    dayan = _card(23555, "Котик Даян", 7)
    parts = [
        dayan,
        _card(31562, "Котик Даян: Театр чудес", 6),
        _card(33727, "Котик Даян: Приключения в Японии", 5),
        _card(39942, "Тама: Откуда же он взялся?", 80_000),
        _card(50001, "Тама: Новые друзья", 40_000),
        _card(39351, "Даян и Тама", 100),
    ]
    scoped = ap.franchise_branch_parts(dayan, parts)
    own = ap.branch_franchise_index(dayan, parts)
    merged = ap.franchise_parts_index(parts)
    assert [row["malId"] for row in scoped] == [23555, 31562, 33727]
    assert ap.franchise_branch_key(dayan, parts) == "котик даян"
    assert own < 7_000 < merged
    cand = ap.SongCandidate({}, dayan, franchise_index=own)
    assert cand.level > 7
