# -*- coding: utf-8 -*-
"""Неполный каталог догружает недостающие части известных франшиз."""
from types import SimpleNamespace

import animepack as ap
from animepack import PackSettings
from si_hyx_parts.animepack import franchise_part_topup
from test_animepack_catalog_superset import _card, _gen


def _part(mal, kind="tv", year=2015, score=7.5, status="released"):
    return {"id": mal, "malId": mal, "kind": kind, "score": score,
            "airedOn": {"year": year}, "status": status}


def test_missing_first_seasons_are_fetched_into_the_pool(tmp_path):
    settings = PackSettings(questions=1, rounds=1, themes=1)
    gen = _gen(tmp_path, settings)
    sig = ap.shiki_cache_signature(settings)
    overlord4 = dict(_card(48895), franchise="overlord")
    filler = [_card(i) for i in range(1000, 1300)]
    gen.db_cache.add_cards("anime", sig, [overlord4] + filler)
    gen.db_cache.add_franchises({"overlord": [
        _part(29803), _part(35073), _part(48895),
        _part(36497, kind="special"),            # тип выключен фильтром
        _part(99999, status="anons")]})          # анонс не берём
    asked = []

    def animes_by_ids(ids):
        asked.append(list(ids))
        return [dict(_card(i), franchise="overlord") for i in ids]

    gen.shikimori = SimpleNamespace(animes_by_ids=animes_by_ids)
    gen.s.kinds = dict(gen.s.kinds, special=False)
    gen._fetch_random_cards = lambda *a, **k: None
    logs = []
    gen.log = logs.append
    ids = gen._random_shikimori_ids()
    assert asked == [[29803, 35073]]
    assert {29803, 35073, 48895} <= set(ids)
    assert any("НЕПОЛНЫЙ" in line for line in logs)
    # Догруженное лежит в мешке текущих фильтров: повторно не спрашивается.
    again = _gen(tmp_path, settings)
    again.db_cache = gen.db_cache
    again._fetch_random_cards = lambda *a, **k: None
    again.shikimori = SimpleNamespace(animes_by_ids=animes_by_ids)
    again._random_shikimori_ids()
    assert asked == [[29803, 35073]]


def test_complete_catalog_is_not_topped_up(tmp_path):
    settings = PackSettings(questions=1, rounds=1, themes=1)
    gen = _gen(tmp_path, settings)
    sig = ap.shiki_cache_signature(settings)
    gen.db_cache.add_cards("anime", sig, [dict(_card(48895), franchise="overlord")])
    gen.db_cache.mark_complete("anime", sig)
    gen.db_cache.add_franchises({"overlord": [_part(29803)]})
    gen.shikimori = SimpleNamespace(
        animes_by_ids=lambda ids: (_ for _ in ()).throw(AssertionError("сеть")))
    assert gen._random_shikimori_ids() == [48895]


def test_part_filters_follow_pack_settings():
    settings = PackSettings(year_from=2010, year_to=2020, score_from=6)
    assert franchise_part_topup.part_fits(_part(1), settings)
    assert not franchise_part_topup.part_fits(_part(1, year=2005), settings)
    assert not franchise_part_topup.part_fits(_part(1, score=5), settings)
    assert not franchise_part_topup.part_fits({"kind": "tv"}, settings)
