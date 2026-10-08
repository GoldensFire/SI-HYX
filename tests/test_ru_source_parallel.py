# -*- coding: utf-8 -*-
"""Все три источника начинают обход вместе; сбой и остановка не теряют кэш."""
from types import SimpleNamespace
import threading
import time

import pytest
import animepack as ap
from si_hyx_parts.animepack import ru_popularity_refresh as refresh
from si_hyx_parts.animepack.ru_popularity_math import RuPopularityConfig, SNAPSHOT_GROUP
from si_hyx_parts.animepack.ru_popularity_store import RuPopularityStore
from test_manga_ru_cache import title


class Catalog:
    metric = "views"

    def __init__(self, source, barrier, fail=False):
        self.source, self.barrier, self.fail = source, barrier, fail
        self.calls = []

    def catalog_page(self, page):
        self.calls.append(page)
        if page == 1:
            self.barrier.wait(timeout=5)
            if self.fail:
                raise TimeoutError("source unavailable")
            return [title(self.source, id=str(i)) for i in (1, 2)]
        return []


def store(cache, barrier, fail=False):
    clients = {source: Catalog(source, barrier, fail and source == "remanga")
               for source in ("remanga", "mangalib")}
    return RuPopularityStore(cache, clients, RuPopularityConfig(min_samples=2))


@pytest.mark.parametrize("fail", [False, True])
def test_three_censuses_run_together_and_failure_is_local(tmp_path, monkeypatch, fail):
    path = str(tmp_path / "cache.json")
    cache = ap.ShikimoriDbCache(path)
    previous = {"previous": "remanga"}
    cache.remember_memo(SNAPSHOT_GROUP, "remanga", previous)
    barrier = threading.Barrier(3)
    current = store(cache, barrier, fail)
    gen = SimpleNamespace(_ru_popularity_service=current, db_cache=cache,
                          stopped=lambda: False, log=lambda message: None)

    def shiki(generator, config, stopped=None):
        barrier.wait(timeout=5)
        return {"complete": True, "source": "shikimori"}

    monkeypatch.setattr(refresh, "shikimori_snapshot", shiki)
    refresh.refresh_ru_popularity(gen)
    saved = ap.ShikimoriDbCache(path)
    assert saved.memo(SNAPSHOT_GROUP, "mangalib")["complete"]
    assert saved.memo(SNAPSHOT_GROUP, "shikimori")["complete"]
    if fail:
        assert saved.memo(SNAPSHOT_GROUP, "remanga") == previous
        assert saved.memo("ru_population_refresh_status_v1", "remanga")["status"] == "ERROR"
    else:
        assert saved.memo(SNAPSHOT_GROUP, "remanga")["complete"]
    assert current.snapshots == saved.memo_group(SNAPSHOT_GROUP)


@pytest.mark.parametrize("parts", [None, ("manga", "remanga", "mangalib")])
def test_full_database_and_all_manga_start_external_sources_with_shiki(
        tmp_path, monkeypatch, parts):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    barrier = threading.Barrier(3)
    settings = ap.PackSettings(pack_manga=True, pct_manga=50)
    gen = ap.AnimePackGenerator(settings, db_cache=cache)
    gen._ru_popularity_service = store(cache, barrier)
    gen.shikimori = SimpleNamespace()
    catalog_calls = []

    def catalog(manga=False, **kwargs):
        if not catalog_calls:
            barrier.wait(timeout=5)
        catalog_calls.append(manga)
        from si_hyx_parts.animepack.db_settings import database_settings
        cache.mark_complete("manga" if manga else "anime",
                            ap.shiki_cache_signature(database_settings(), manga))
        return []

    def shiki(generator, config, stopped=None):
        assert catalog_calls  # Census Shikimori follows its fresh catalog/favorites.
        return {"complete": True, "source": "shikimori", "timestamp": time.time()}

    gen.fetch_full_catalog = catalog
    monkeypatch.setattr(refresh, "shikimori_snapshot", shiki)
    gen.refresh_db(parts)
    assert catalog_calls == ([False, True] if parts is None else [True])
    assert all(cache.memo(SNAPSHOT_GROUP, source)["complete"]
               for source in ("remanga", "mangalib", "shikimori"))
    assert all(client.calls == [1, 2] for client in gen._ru_popularity_service.clients.values())


def test_primary_failure_cancels_external_work_and_preserves_old_snapshots(tmp_path):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    barrier = threading.Barrier(3)
    gen = ap.AnimePackGenerator(ap.PackSettings(), db_cache=cache)
    gen._ru_popularity_service = store(cache, barrier)
    previous = {source: {"previous": source} for source in ("remanga", "mangalib")}
    for source, snapshot in previous.items():
        cache.remember_memo(SNAPSHOT_GROUP, source, snapshot)

    def catalog(manga=False, **kwargs):
        barrier.wait(timeout=5)
        raise RuntimeError("primary catalog failed")

    class WaitingCatalog(Catalog):
        stopped = staticmethod(lambda: False)

        def catalog_page(self, page):
            self.barrier.wait(timeout=5)
            while not self.stopped():
                threading.Event().wait(.01)
            return []

    gen._ru_popularity_service.clients = {
        source: WaitingCatalog(source, barrier) for source in previous}
    gen.fetch_full_catalog = catalog
    with pytest.raises(RuntimeError, match="primary catalog"):
        gen.refresh_db(("manga", "remanga", "mangalib"))
    saved = ap.ShikimoriDbCache(cache.path)
    assert saved.memo_group(SNAPSHOT_GROUP) == previous
    assert not saved.memo_group("ru_population_refresh_status_v1")
