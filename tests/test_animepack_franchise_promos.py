# -*- coding: utf-8 -*-
"""Проморолики не создают второй корень той же франшизы в базе."""
import animepack as ap
from si_hyx_parts.animepack_tab.db_title_tree import group_title_rows


def _part(ident, title):
    return {"id": ident, "malId": ident, "russian": title, "kind": "movie"}


PARTS = [
    _part(1, "Клинок, рассекающий демонов"),
    _part(2, "Клинок, рассекающий демонов: Бесконечный поезд"),
    _part(3, "Клинок, рассекающий демонов: Бесконечный замок 2"),
    _part(4, "Клинок, рассекающий демонов: Бесконечный замок 3"),
    _part(5, "Академия клинка: День святого Валентина"),
    _part(6, "Академия клинка: Банкет демона"),
]


def test_main_seasons_and_missing_promos_have_one_branch():
    lead = dict(PARTS[0], franchise="demon_slayer")
    crossover = _part(7, "Клинок, рассекающий демонов x Главная лига бейсбола")
    promo = {"id": 8, "malId": 8, "name": "Game no Eiyuu",
             "franchise": "demon_slayer"}
    key = ap.franchise_branch_key(lead, PARTS)
    assert key
    assert ap.franchise_branch_key(crossover, PARTS) == key
    assert ap.franchise_branch_key(promo, PARTS) == key
    assert ap.franchise_branch_key(PARTS[4], PARTS) != key


def test_tree_merges_missing_promos_and_counts_union_of_known_parts():
    cards = [PARTS[0], PARTS[1], _part(7, "Game no Eiyuu"),
             _part(8, "Клинок, рассекающий демонов x MLB")]
    rows = [{"id": c["id"], "title": c["russian"], "index": 100 - i,
             "franchise": "demon_slayer", "card": c,
             "franchise_branch": ap.franchise_branch_key(c, PARTS)}
            for i, c in enumerate(cards)]
    grouped, parents = group_title_rows(rows, lambda _: PARTS)
    assert parents.count(-1) == 1
    assert "4 из 6 в каталоге" in grouped[0]["title"]
    assert {r["id"] for r in grouped if not r.get("_franchise_header")} == {1, 2, 7, 8}
