# -*- coding: utf-8 -*-
"""Votes census, incomplete cards and migration from cached MangaLib views."""
import pytest

import animepack as ap
from si_hyx_parts.animepack_api.ru_manga_clients import MangaLibPopulation
from si_hyx_parts.animepack.ru_catalog_details import DETAIL_GROUP
from si_hyx_parts.animepack.ru_catalog_snapshot import external_snapshot
from si_hyx_parts.animepack.ru_popularity_math import (
    OBSERVATION_GROUP, SNAPSHOT_GROUP, RuPopularityConfig)
from si_hyx_parts.animepack.ru_popularity_store import RuPopularityStore
from test_manga_ru_cache import title
from test_manga_ru_popularity import manga


def test_incomplete_catalog_retries_old_views_cache_then_reuses_votes(tmp_path):
    client = MangaLibPopulation()
    client.detail_workers = 1
    calls = []
    rows = [{"id": i, "slug_url": f"{i}--title", "type": {"label": "Манга"},
             "rating": {"votes": i * 10}} for i in (1, 2)]
    rows[0].pop("rating")

    def get(path, params=None):
        calls.append((path, params))
        if path == "/api/manga":
            assert "rate" in params["fields[]"]
            return {"data": rows if params["page"] == 1 else []}
        assert path == "/api/manga/1--title" and "rate" in params["fields[]"]
        return {"data": rows[0] | {"rating": {"votes": 120}, "close_view": 0}}

    client.get = get
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    cache.remember_memo(DETAIL_GROUP, "mangalib:1", title("mangalib", id="1",
        slug="1--title", kind="manga", metric="views", raw_metric=999999))
    config = RuPopularityConfig(min_samples=2)
    snapshot = external_snapshot(client, config, lambda: False, cache)
    assert snapshot["distributions"] == {"manga": [20, 120]}
    assert len(calls) == 3
    assert cache.memo(DETAIL_GROUP, "mangalib:1")["metric"] == "rating.votes"
    external_snapshot(client, config, lambda: False, cache)
    assert len(calls) == 5


@pytest.mark.parametrize("votes", [None, True, -1, "1.5 K", float("nan")])
def test_invalid_votes_never_fall_back_to_views_or_formatted_count(votes):
    row = MangaLibPopulation().normalize({"id": 1, "slug_url": "1--title",
        "rating": {"votes": votes, "votesFormated": "123 K", "average": "10"},
        "views": {"total": 999999}}, catalog=True)
    assert row["raw_metric"] is None and row["status"] == "ERROR"


def test_public_votes_do_not_claim_chapter_access_or_hide_known_restrictions():
    client = MangaLibPopulation()
    data = {"id": 1, "slug_url": "1--title", "rating": {"votes": 0}}
    public = client.normalize(data, catalog=True)
    assert public["status"] == "NORMAL" and public["raw_metric"] == 0
    assert "is_licensed" not in public["fields"]
    assert client.normalize(data)["status"] == "ERROR"
    for restrictions in ({"close_view": 1}, {"is_licensed": True}):
        assert client.normalize(data | restrictions, catalog=True)["status"] == "RIGHTS_RESTRICTED"


def votes_store(tmp_path, *, metric="rating.votes", status="NORMAL"):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    row = title("mangalib", metric=metric, raw_metric=20, status=status)
    cache.remember_memo(SNAPSHOT_GROUP, "mangalib", {
        "version": 1, "complete": True, "timestamp": 1000, "metric": metric,
        "titles": [row], "distributions": {"manhwa": list(range(101))}})
    client = MangaLibPopulation()
    client.details = lambda row: pytest.fail("offline evaluation must not request details")
    store = RuPopularityStore(cache, {"mangalib": client}, clock=lambda: 1000)
    return store, cache


def old_observation():
    return {"source": "mangalib", "source_title_id": "ext", "type": "manhwa",
        "status": "NORMAL", "metric": "views", "raw_metric": 999999,
        "percentile": .99, "timestamp": 1000, "snapshot_timestamp": 1000,
        "last_normal": {"source_title_id": "ext", "type": "manhwa",
                        "metric": "views", "percentile": .99}}


def test_old_views_snapshot_and_observation_cannot_boost_votes(tmp_path):
    store, cache = votes_store(tmp_path, metric="views")
    cache.remember_memo(OBSERVATION_GROUP, "mangalib:77", old_observation())
    observation = store.observe("mangalib", manga(), network=False)
    assert observation["status"] == "ERROR" and observation["percentile"] is None
    assert "last_normal" not in observation
    assert observation["reason"] == "missing_or_expired_complete_distribution"


def test_new_votes_snapshot_recomputes_even_fresh_views_observation(tmp_path):
    store, cache = votes_store(tmp_path)
    cache.remember_memo(OBSERVATION_GROUP, "mangalib:77", old_observation())
    observation = store.observe("mangalib", manga(), network=False)
    assert observation["metric"] == "rating.votes" and observation["percentile"] == .2
    assert observation["last_normal"]["metric"] == "rating.votes"


def test_restricted_votes_never_inherit_old_views_history(tmp_path):
    store, cache = votes_store(tmp_path, status="RIGHTS_RESTRICTED")
    previous = old_observation()
    previous.update(metric="rating.votes", timestamp=1, snapshot_timestamp=999)
    cache.remember_memo(OBSERVATION_GROUP, "mangalib:77", previous)
    observation = store.observe("mangalib", manga(), network=False)
    assert observation["status"] == "RIGHTS_RESTRICTED"
    assert observation["percentile"] is None and "last_normal" not in observation


def test_detail_cannot_rank_views_against_votes_distribution(tmp_path):
    store, _ = votes_store(tmp_path)
    store.clients["mangalib"].details = lambda row: row | {"metric": "views"}
    observation = store.observe("mangalib", manga())
    assert observation["status"] == "ERROR" and observation["percentile"] is None
    assert observation["reason"] == "population_metric_mismatch"
