# -*- coding: utf-8 -*-
"""A complete reader census must help random generation find translations."""
import time
from types import SimpleNamespace

import animepack as api
from si_hyx_parts.animepack.manga_source_candidates import prefer_reader_matches
from si_hyx_parts.animepack.ru_popularity_math import SNAPSHOT_GROUP


def setup_pool(tmp_path, **settings):
    cards = {ident: {"id": str(ident), "malId": ident, "kind": "manga",
                     "name": f"Distinctive manga title {ident}",
                     "airedOn": {"year": 2000}} for ident in range(1, 7)}
    rows = [{"id": str(ident), "slug": f"title-{ident}", "kind": "manga",
             "year": 2000, "titles": [cards[ident]["name"]],
             "fields": {"is_licensed": False}, "status": "NORMAL"}
            for ident in (2, 3, 4, 5, 6)]
    rows[1]["fields"]["is_licensed"] = True
    rows[2]["fields"]["is_erotic"] = True
    rows[3]["year"] = 2001
    rows[4]["fields"].pop("is_licensed")
    cache = api.ShikimoriDbCache(str(tmp_path / "db.json"))
    cache.remember_memo(SNAPSHOT_GROUP, "remanga", {
        "version": 1, "complete": True, "timestamp": time.time(),
        "titles": rows, "distributions": {"manga": [1, 2]}})
    options = dict(manga_sources={"remanga": True}, manga_lang="ru")
    options.update(settings)
    return SimpleNamespace(s=SimpleNamespace(**options), db_cache=cache,
                           _manga_cache=cards, log=lambda *_: None)


def test_known_public_match_goes_first_without_losing_other_candidates(tmp_path):
    generator = setup_pool(tmp_path)
    assert prefer_reader_matches(generator, [1, 3, 5, 2, 6, 4]) == [2, 1, 3, 5, 6, 4]
    assert generator._manga_catalog_matches == 1


def test_adult_option_and_random_relative_order_are_preserved(tmp_path):
    generator = setup_pool(tmp_path, manga_allow_erotica=True)
    assert prefer_reader_matches(generator, [4, 1, 2, 3]) == [4, 2, 1, 3]


def test_wrong_language_or_disabled_reader_does_not_bias_selection(tmp_path):
    for settings in ({"manga_lang": "en"}, {"manga_sources": {"mangadex": True}}):
        generator = setup_pool(tmp_path, **settings)
        assert prefer_reader_matches(generator, [1, 2]) == [1, 2]
        assert generator._manga_catalog_matches == 0


def test_incomplete_census_does_not_change_selection(tmp_path):
    generator = setup_pool(tmp_path)
    row = generator.db_cache.memo(SNAPSHOT_GROUP, "remanga")
    row["complete"] = False
    generator.db_cache.remember_memo(SNAPSHOT_GROUP, "remanga", row)
    assert prefer_reader_matches(generator, [1, 2]) == [1, 2]


def test_closed_mangalib_title_or_adult_rating_is_not_preferred(tmp_path):
    generator = setup_pool(tmp_path, manga_sources={"mangalib": True})
    snapshot = generator.db_cache.memo(SNAPSHOT_GROUP, "remanga")
    snapshot["titles"][0]["status"] = "RIGHTS_RESTRICTED"
    snapshot["titles"][2]["fields"] = {
        "is_licensed": False, "ageRestriction": {"label": "18+"}}
    generator.db_cache.remember_memo(SNAPSHOT_GROUP, "mangalib", snapshot)
    assert prefer_reader_matches(generator, [1, 2, 4]) == [1, 2, 4]
