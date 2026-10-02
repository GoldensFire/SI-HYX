# -*- coding: utf-8 -*-
"""Прерванная первая страница сохраняет детали, но не полное распределение."""
import pytest
import animepack as ap
from si_hyx_parts.animepack import ru_catalog_snapshot as census
from si_hyx_parts.animepack.ru_popularity_math import RuPopularityConfig, SNAPSHOT_GROUP
from test_manga_ru_cache import title
from test_manga_ru_snapshots import Catalog


def test_first_page_cancellation_is_saved_on_disk_and_resumed(tmp_path):
    path = str(tmp_path / "cache.json")
    cache = ap.ShikimoriDbCache(path)
    client = Catalog([title(id=str(i), raw_metric=None) for i in (1, 2, 3)])
    config = RuPopularityConfig(min_samples=2)
    result = census.external_snapshot(client, config, lambda: client.details_calls >= 1, cache)
    assert result is None
    reopened = ap.ShikimoriDbCache(path)
    assert reopened.memo(census.DETAIL_GROUP, "remanga:1")["raw_metric"] == 20
    assert not reopened.memo_group(SNAPSHOT_GROUP)
    assert census.external_snapshot(client, config, lambda: False, reopened)["complete"]
    assert client.details_calls == 3  # первый ответ не спрашивался второй раз


def test_invalid_detail_is_not_cached_and_old_invalid_cache_is_retried(tmp_path):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    client = Catalog([title(id=str(i), raw_metric=None) for i in (1, 2)])
    config = RuPopularityConfig(min_samples=2)
    valid_details = client.details
    client.details = lambda row: row | {"status": "ERROR"}
    with pytest.raises(ValueError, match="missing"):
        census.external_snapshot(client, config, lambda: False, cache)
    assert not cache.memo_group(census.DETAIL_GROUP)
    cache.remember_memo(census.DETAIL_GROUP, "remanga:1", title(id="1", status="ERROR"))
    client.details = valid_details
    assert census.external_snapshot(client, config, lambda: False, cache)["complete"]
    assert client.details_calls == 2


def test_cancel_while_last_page_is_in_flight_cannot_publish_snapshot(tmp_path):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    client = Catalog([title(id=str(i)) for i in (1, 2)])
    original = client.catalog_page
    stopped = False

    def page(number):
        nonlocal stopped
        stopped = number == 2
        return original(number)

    client.catalog_page = page
    assert census.external_snapshot(client, RuPopularityConfig(min_samples=2),
                                    lambda: stopped, cache) is None


def test_progress_is_reported_before_first_page_finishes(tmp_path, monkeypatch):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    client = Catalog([title(id=str(i), raw_metric=None) for i in (1, 2, 3)])
    valid_details = client.details
    tick = 0
    monkeypatch.setattr(census.time, "monotonic", lambda: tick)

    def details(row):
        nonlocal tick
        tick += 31
        return valid_details(row)

    client.details = details
    progress = []
    census.external_snapshot(client, RuPopularityConfig(min_samples=2),
                             lambda: False, cache, progress.append)
    assert "1 тайтлов" in progress[0] and "1 запросов" in progress[0]
    assert "0 из кэша" in progress[0] and "страница 1" in progress[0]
