# -*- coding: utf-8 -*-
"""Пригодность карточек и полнота объединённой базы — разные проверки."""
import animepack as ap
from si_hyx_parts.animepack.catalog_superset import cached_catalog
from test_animepack_catalog_superset import _card


def test_full_narrow_catalog_is_reused_but_does_not_cover_wider_request(tmp_path):
    db = ap.ShikimoriDbCache(str(tmp_path / "db.json"))
    wide = "1944-2026|tv,movie|0|"
    narrow = wide + "106,130"
    db.add_cards("anime", narrow, [_card(1), _card(2)])
    db.mark_complete("anime", narrow)
    db.add_cards("anime", wide, [_card(2, score=8), _card(3)])
    cards, complete = cached_catalog(db, "anime", wide)
    assert {c["malId"] for c in cards} == {1, 2, 3}
    assert len(cards) == 3
    assert next(c for c in cards if c["malId"] == 2)["score"] == 8
    assert not complete


def test_separate_complete_book_kinds_cover_the_combined_request(tmp_path):
    db = ap.ShikimoriDbCache(str(tmp_path / "db.json"))
    for sig, card in (("1944-2026|manga,one_shot,doujin|0|", _card(1, kind="manga")),
                      ("1944-2026|manhwa,manhua|0|", _card(2, kind="manhwa"))):
        db.add_cards("manga", sig, [card])
        db.mark_complete("manga", sig)
    sig = "1944-2026|manga,manhwa,one_shot,doujin|0|"
    cards, complete = cached_catalog(db, "manga", sig)
    assert {c["malId"] for c in cards} == {1, 2}
    assert complete


def test_union_keeps_all_current_filters_and_missing_kind_incomplete(tmp_path):
    db = ap.ShikimoriDbCache(str(tmp_path / "db.json"))
    sig = "1944-2026|tv|0|"
    db.add_cards("anime", sig, [
        _card(1), _card(2, genres=(130,)), _card(3, year=2000),
        _card(4, score=5), _card(5, kind="movie"),
    ])
    db.mark_complete("anime", sig)
    cards, complete = cached_catalog(db, "anime", "2010-2020|tv,movie|7|130")
    assert {c["malId"] for c in cards} == {1, 5}
    assert not complete
