# -*- coding: utf-8 -*-
"""Reference censuses are complete, resumable and immune to partial failures."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
import animepack as ap
from si_hyx_parts.animepack.ru_popularity_math import RuPopularityConfig, SNAPSHOT_GROUP
from si_hyx_parts.animepack.ru_popularity_refresh import (
    external_snapshot, shikimori_snapshot, refresh_ru_popularity)
from si_hyx_parts.animepack.ru_popularity_store import RuPopularityStore
from test_manga_ru_cache import title, populate
from test_manga_ru_popularity import manga


class Catalog:
    source, metric = "remanga", "count_bookmarks"

    def __init__(self, rows, error_page=None):
        self.rows, self.error_page = rows, error_page
        self.details_calls = 0

    def catalog_page(self, page):
        if page == self.error_page:
            raise TimeoutError("catalog timeout")
        return deepcopy(self.rows) if page == 1 else []

    def details(self, row):
        self.details_calls += 1
        return row | {"raw_metric": 20}


def test_snapshots_use_separate_types_and_only_reliable_signals(tmp_path):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    rows = [title(id=f"{kind}{i}", kind=kind, raw_metric=i * scale)
            for kind, scale in (("manga", 1000), ("manhwa", 10), ("manhua", 1))
            for i in (1, 2)]
    rows.append(title(id="licensed", status="RIGHTS_RESTRICTED", raw_metric=0))
    snapshot = external_snapshot(Catalog(rows), RuPopularityConfig(min_samples=2),
                                 lambda: False, cache)
    assert snapshot["complete"]
    assert snapshot["distributions"] == {"manga": [1000, 2000],
        "manhwa": [10, 20], "manhua": [1, 2]}
    assert not snapshot["type_fallback"]


def test_missing_catalog_bookmarks_are_resumed_from_detail_cache(tmp_path):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    client = Catalog([title(id=str(i), raw_metric=None) for i in (1, 2)])
    config = RuPopularityConfig(min_samples=2)
    assert external_snapshot(client, config, lambda: False, cache)
    assert client.details_calls == 2
    assert external_snapshot(client, config, lambda: False, cache)
    assert client.details_calls == 2


def test_unresolved_types_declare_whole_site_fallback(tmp_path):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    client = Catalog([title(id="a", kind="", raw_metric=1),
                      title(id="b", raw_metric=2)])
    snapshot = external_snapshot(client, RuPopularityConfig(min_samples=2), lambda: False, cache)
    assert snapshot["type_fallback"] == "complete_site_catalog_types_unresolved"
    assert snapshot["distributions"] == {"all_types": [1, 2]}


def test_cancellation_page_limit_and_repeated_page_never_create_complete_snapshot(tmp_path):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    client = Catalog([title(id=str(i)) for i in (1, 2)])
    assert external_snapshot(client, RuPopularityConfig(min_samples=2), lambda: True, cache) is None
    with pytest.raises(ValueError, match="incomplete"):
        external_snapshot(client, RuPopularityConfig(min_samples=2, max_catalog_pages=1),
                          lambda: False, cache)
    client.catalog_page = lambda page: [title(id="repeated")]
    with pytest.raises(ValueError, match="repeated"):
        external_snapshot(client, RuPopularityConfig(min_samples=2), lambda: False, cache)


def test_failure_retains_previous_external_and_shiki_snapshots(tmp_path):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    populate(cache)
    old = cache.memo_group(SNAPSHOT_GROUP)
    client = Catalog([title(id=str(i)) for i in (1, 2)], error_page=2)
    service = RuPopularityStore(cache, {"remanga": client, "mangalib": client},
                                RuPopularityConfig(min_samples=2))
    class Shiki:
        def random_mangas(self, *args, **kwargs):
            raise TimeoutError("shiki timeout")
    generator = SimpleNamespace(_ru_popularity_service=service, db_cache=cache,
                                shikimori=Shiki(), stopped=lambda: False, log=lambda message: None)
    refresh_ru_popularity(generator)
    assert cache.memo_group(SNAPSHOT_GROUP) == old
    assert cache.memo("ru_population_refresh_status_v1", "remanga")["status"] == "ERROR"


def test_shiki_census_is_unfiltered_raw_and_full_book_index(tmp_path):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    cache.remember_memo("manga_favorites", "1", 200)
    cards = [manga(id=str(i + 1), kind=kind,
                   statusesStats=[{"status": "completed", "count": i + 1}])
             for i, kind in enumerate(("manga", "manhwa", "manhua"))]
    calls = []
    class Shiki:
        def random_mangas(self, page, **kwargs):
            calls.append(kwargs)
            return cards if page == 1 else []
    generator = SimpleNamespace(db_cache=cache, shikimori=Shiki(), stopped=lambda: False,
                                log=lambda message: None)
    snapshot = shikimori_snapshot(generator, RuPopularityConfig(min_samples=2))
    assert calls[0] == {"limit": 50, "order": "id", "kinds": ("manga", "manhwa", "manhua")}
    assert snapshot["readership"] == {"manga": [10], "manhwa": [20], "manhua": [30]}
    original = ap.SongCandidate({}, cards[0], media="manga", favorites=200).book_index
    assert snapshot["book_index"]["manga"] == [original]
