# -*- coding: utf-8 -*-
"""A completed command requires all three saved sources and the actual catalog."""
import animepack as api
from si_hyx_parts.animepack.ru_popularity_math import SNAPSHOT_GROUP
from tools.manga_db_refresh import audit


def database(tmp_path):
    cache = api.ShikimoriDbCache(str(tmp_path / "db.json"))
    cache.add_cards("manga", "catalog", [{"id": "1", "kind": "manga"}])
    cache.mark_complete("manga", "catalog")
    for source in ("shikimori", "remanga", "mangalib"):
        cache.remember_memo(SNAPSHOT_GROUP, source, {
            "version": 1, "complete": True, "timestamp": 100,
            "readership": {"manga": [1, 2]}, "distributions": {"manga": [1, 2]},
            "titles": [{"id": "1", "status": "NORMAL"}],
        })
        cache.remember_memo("ru_population_refresh_status_v1", source,
                            {"status": "NORMAL", "timestamp": 100})
    return cache


def test_audit_requires_a_fresh_complete_snapshot_from_every_source(tmp_path):
    cache = database(tmp_path)
    assert audit(cache, 90)["success"]
    old = cache.memo(SNAPSHOT_GROUP, "mangalib")
    cache.remember_memo(SNAPSHOT_GROUP, "mangalib", old | {"timestamp": 80})
    assert not audit(cache, 90)["success"]


def test_old_snapshot_cannot_hide_a_failed_refresh(tmp_path):
    cache = database(tmp_path)
    cache.remember_memo("ru_population_refresh_status_v1", "mangalib",
                        {"status": "ERROR", "reason": "502"})
    assert not audit(cache, 90)["success"]


def test_population_snapshots_cannot_hide_missing_catalog_cards(tmp_path):
    cache = database(tmp_path)
    cache.clear_part("manga")
    assert not audit(cache, 90)["success"]


def test_resume_can_keep_other_sources_but_still_requires_the_resumed_source(tmp_path):
    cache = database(tmp_path)
    row = cache.memo(SNAPSHOT_GROUP, "mangalib")
    cache.remember_memo(SNAPSHOT_GROUP, "mangalib", row | {"timestamp": 150})
    assert audit(cache, 140, ["mangalib"])["success"]
    assert not audit(cache, 140)["success"]
