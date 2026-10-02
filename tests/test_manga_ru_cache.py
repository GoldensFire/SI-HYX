# -*- coding: utf-8 -*-
"""Persistent reliable history, distinct cohorts and zero generation traffic."""
from copy import deepcopy
from types import SimpleNamespace

import animepack as ap
from si_hyx_parts.animepack.ru_popularity_math import (
    SNAPSHOT_GROUP, OBSERVATION_GROUP, RuPopularityConfig)
from si_hyx_parts.animepack.ru_popularity_store import RuPopularityStore, apply_ru_popularity
from test_manga_ru_popularity import manga


def title(source="remanga", **extra):
    return {"id": "ext", "slug": "external-title", "kind": "manhwa",
            "titles": [manga()["name"], manga()["russian"]], "year": 2015,
            "metric": "count_bookmarks" if source == "remanga" else "views",
            "raw_metric": 97, "status": "NORMAL", "fields": {}, **extra}


def populate(cache, now=1000, external=None):
    cache.remember_memo(SNAPSHOT_GROUP, "shikimori", {
        "version": 1, "complete": True, "timestamp": now,
        "readership": {"manhwa": list(range(101)), "manga": [0, 100000]},
        "book_index": {"manhwa": [i * 200 for i in range(101)], "manga": [0, 1]}})
    cache.remember_memo(SNAPSHOT_GROUP, "remanga", {
        "version": 1, "complete": True, "timestamp": now,
        "distributions": {"manhwa": list(range(101)), "manga": [0, 100000]},
        "titles": [external or title()]})


class Client:
    def __init__(self, row):
        self.row, self.calls = row, 0

    def details(self, row):
        self.calls += 1
        if isinstance(self.row, Exception):
            raise self.row
        return deepcopy(self.row)


def test_licensing_history_survives_restart_and_low_current_metric(tmp_path):
    path = str(tmp_path / "cache.json")
    cache = ap.ShikimoriDbCache(path)
    populate(cache)
    client = Client(title())
    first = RuPopularityStore(cache, {"remanga": client}, clock=lambda: 1000)
    normal = first.observe("remanga", manga())
    assert normal["percentile"] == .97
    cache.save()
    cache = ap.ShikimoriDbCache(path)
    client.row = title(status="RIGHTS_RESTRICTED", raw_metric=1,
                       fields={"is_licensed": True})
    after = RuPopularityStore(cache, {"remanga": client}, clock=lambda: 1000 + 8 * 86400)
    restricted = after.observe("remanga", manga())
    assert restricted["status"] == "RIGHTS_RESTRICTED"
    assert restricted["percentile"] is None
    assert restricted["last_normal"]["percentile"] == .97
    assert restricted["raw_metric"] == 1
    candidate = ap.SongCandidate({}, manga(), media="manga")
    assert after.evaluate(candidate)["P_ru"] > .3
    assert cache.memo(OBSERVATION_GROUP, "remanga:77")["last_normal"]["percentile"] == .97


def test_normal_decline_replaces_last_normal_instead_of_all_time_max(tmp_path):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    populate(cache)
    first = RuPopularityStore(cache, {"remanga": Client(title())}, clock=lambda: 1000)
    first.observe("remanga", manga())
    later = RuPopularityStore(cache, {"remanga": Client(title(raw_metric=20))},
                             clock=lambda: 1000 + 8 * 86400)
    record = later.observe("remanga", manga())
    assert record["percentile"] == record["last_normal"]["percentile"] == .2


def test_errors_disable_source_without_destroying_history_or_using_it(tmp_path):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    populate(cache)
    normal = RuPopularityStore(cache, {"remanga": Client(title())}, clock=lambda: 1000)
    normal.observe("remanga", manga())
    client = Client(TimeoutError("timeout"))
    later = RuPopularityStore(cache, {"remanga": client}, clock=lambda: 1000 + 8 * 86400)
    result = later.evaluate(ap.SongCandidate({}, manga(), media="manga"))
    assert "P_ru" not in result
    assert result["sources"]["remanga"]["last_normal"]["percentile"] == .97
    later.observe("remanga", manga(id="78"))
    assert client.calls == 1


def test_missing_snapshots_do_not_fetch_catalog_or_titles(tmp_path):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    client = Client(AssertionError("must not request network"))
    store = RuPopularityStore(cache, {"remanga": client})
    result = store.evaluate(ap.SongCandidate({}, manga(), media="manga"))
    assert "P_ru" not in result and client.calls == 0
    assert result["sources"]["remanga"]["status"] == "ERROR"


def test_generation_uses_only_local_snapshots_and_matching_is_memoized(tmp_path):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    populate(cache)
    client = Client(AssertionError("generation must not request population APIs"))
    store = RuPopularityStore(cache, {"remanga": client}, clock=lambda: 1000)
    gen = SimpleNamespace(_ru_popularity_service=store)
    for _ in range(5):
        candidate = ap.SongCandidate({}, manga(), media="manga")
        apply_ru_popularity(gen, candidate)
        assert candidate.ru_popularity["P_shiki"] == .3
        assert candidate.effective_book_index > candidate.book_index
    assert client.calls == 0


def test_ambiguous_snapshot_gets_no_external_boost(tmp_path):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    populate(cache)
    snapshot = cache.memo(SNAPSHOT_GROUP, "remanga")
    snapshot["titles"].append(title(id="another"))
    cache.remember_memo(SNAPSHOT_GROUP, "remanga", snapshot)
    client = Client(AssertionError("ambiguous title must not query detail"))
    store = RuPopularityStore(cache, {"remanga": client}, clock=lambda: 1000)
    candidate = ap.SongCandidate({}, manga(), media="manga")
    result = store.evaluate(candidate)
    assert result["sources"]["remanga"]["status"] == "AMBIGUOUS"
    assert result["effective_book_index"] == candidate.book_index
    assert client.calls == 0


def test_type_fallback_is_explicit_and_does_not_fabricate_classification(tmp_path):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    populate(cache)
    row = title("mangalib", kind="", shiki_id=77)
    cache.remember_memo(SNAPSHOT_GROUP, "mangalib", {
        "version": 1, "complete": True, "timestamp": 1000,
        "type_fallback": "complete_site_catalog_types_unresolved",
        "titles": [row], "distributions": {"all_types": list(range(101))}})
    store = RuPopularityStore(cache, {"mangalib": Client(row)}, clock=lambda: 1000)
    result = store.observe("mangalib", manga())
    assert result["percentile"] == .97
    assert result["type"] == "manhwa"
    assert result["cohort"] == "all_types"
    assert result["type_fallback"]


def test_insufficient_or_expired_baseline_gives_exact_fallback(tmp_path):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    populate(cache)
    candidate = ap.SongCandidate({}, manga(), media="manga")
    store = RuPopularityStore(cache, {"remanga": Client(title())},
                             RuPopularityConfig(snapshot_ttl=1), clock=lambda: 1002)
    assert store.evaluate(candidate)["effective_book_index"] == candidate.book_index


def test_corrupted_snapshot_values_fail_closed_to_original_index(tmp_path):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    populate(cache)
    baseline = cache.memo(SNAPSHOT_GROUP, "shikimori")
    baseline["readership"]["manhwa"] = [0, "changed-schema", 100]
    cache.remember_memo(SNAPSHOT_GROUP, "shikimori", baseline)
    candidate = ap.SongCandidate({}, manga(), media="manga")
    store = RuPopularityStore(cache, {"remanga": None}, clock=lambda: 1000)
    assert store.evaluate(candidate, network=False)["effective_book_index"] == candidate.book_index


def test_offline_licensing_update_preserves_reliable_history(tmp_path):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    populate(cache)
    candidate = ap.SongCandidate({}, manga(), media="manga")
    before = RuPopularityStore(cache, {"remanga": None}, clock=lambda: 1000)
    before.evaluate(candidate, network=False)
    snapshot = cache.memo(SNAPSHOT_GROUP, "remanga")
    snapshot["timestamp"] = 2000
    snapshot["titles"] = [title(status="RIGHTS_RESTRICTED", raw_metric=1)]
    cache.remember_memo(SNAPSHOT_GROUP, "remanga", snapshot)
    after = RuPopularityStore(cache, {"remanga": None}, clock=lambda: 2000)
    result = after.evaluate(candidate, network=False)
    assert result["sources"]["remanga"]["last_normal"]["percentile"] == .97
    assert result["P_ru"] > .3


def test_database_preview_is_read_only(tmp_path):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    populate(cache)
    previous = cache.memo_group(OBSERVATION_GROUP)
    store = RuPopularityStore(cache, {"remanga": None}, clock=lambda: 1000, persist=False)
    result = store.evaluate(ap.SongCandidate({}, manga(), media="manga"), network=False)
    assert "P_ru" in result
    assert cache.memo_group(OBSERVATION_GROUP) == previous
