# -*- coding: utf-8 -*-
"""Параллельный census соблюдает предел, сохраняет ответы и не публикует пробелы."""
from types import SimpleNamespace
import threading

import pytest
import animepack as ap
from si_hyx_parts.animepack.ru_catalog_snapshot import external_snapshot, DETAIL_GROUP
from si_hyx_parts.animepack.ru_popularity_math import RuPopularityConfig
from test_manga_ru_cache import title
from test_manga_ru_snapshots import Catalog


class ParallelCatalog(Catalog):
    detail_workers = 2

    def __init__(self, rows, missing=False, cancel=None):
        super().__init__(rows)
        self.active = self.peak = 0
        self.lock = threading.Lock()
        self.barrier = threading.Barrier(2)
        self.missing, self.cancel = missing, cancel

    def detail_client(self):
        return SimpleNamespace(details=self.details)

    def details(self, row):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            self.barrier.wait(timeout=3)
            if self.cancel:
                self.cancel.set()
            if self.missing and row["id"] == "1":
                return None
            return row | {"raw_metric": 20}
        finally:
            with self.lock:
                self.active -= 1
                self.details_calls += 1


def test_parallel_details_are_bounded_and_cache_is_written_by_the_catalog_thread(tmp_path):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    client = ParallelCatalog([title(id=str(i), raw_metric=None) for i in range(6)])
    config = RuPopularityConfig(min_samples=2)
    main = threading.get_ident()
    remember = cache.remember_memo
    threads = []

    def record(*args):
        threads.append(threading.get_ident())
        remember(*args)

    cache.remember_memo = record
    snapshot = external_snapshot(client, config, lambda: False, cache)
    assert snapshot["complete"] and len(snapshot["titles"]) == 6
    assert client.peak == 2 and client.details_calls == 6
    assert set(threads) == {main}
    external_snapshot(client, config, lambda: False, cache)
    assert client.details_calls == 6


def test_missing_parallel_detail_cannot_create_complete_distribution(tmp_path):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    client = ParallelCatalog([title(id=str(i), raw_metric=None) for i in range(2)], missing=True)
    with pytest.raises(ValueError, match="missing"):
        external_snapshot(client, RuPopularityConfig(min_samples=2), lambda: False, cache)
    assert cache.memo(DETAIL_GROUP, "remanga:0")["raw_metric"] == 20


def test_cancellation_drains_only_inflight_requests_and_saves_them(tmp_path):
    path = str(tmp_path / "cache.json")
    cache = ap.ShikimoriDbCache(path)
    stop = threading.Event()
    client = ParallelCatalog([title(id=str(i), raw_metric=None) for i in range(6)], cancel=stop)
    assert external_snapshot(client, RuPopularityConfig(min_samples=2), stop.is_set, cache) is None
    assert client.details_calls == 2
    reopened = ap.ShikimoriDbCache(path)
    assert len(reopened.memo_group(DETAIL_GROUP)) == 2
