# -*- coding: utf-8 -*-
"""Оба внешних источника получают популярность из пакетных каталогов."""
import httpx
import animepack as ap
from si_hyx_parts.animepack_api.ru_manga_clients import ReMangaPopulation, MangaLibPopulation
from si_hyx_parts.animepack.ru_catalog_snapshot import external_snapshot
from si_hyx_parts.animepack.ru_popularity_math import RuPopularityConfig


def test_remanga_title_batches_need_no_detail_requests(tmp_path):
    calls = []
    client = ReMangaPopulation()
    rows = [{"id": i, "dir": f"title-{i}", "type": "Манга",
             "is_licensed": False, "count_bookmarks": i * 10}
            for i in range(1, 41)]
    rows[0]["type"] = "Западный комикс"

    def get(path, params=None):
        calls.append((path, params))
        assert path == "/api/titles/"
        assert params == {"page": len(calls), "count": 40,
                          "ordering": "id", "content": "manga"}
        return {"content": rows if len(calls) == 1 else [],
                "props": {"total_items": 60000, "total_pages": 1500}}

    client.get = get
    progress = []
    try:
        snapshot = external_snapshot(client, RuPopularityConfig(min_samples=2),
            lambda: False, ap.ShikimoriDbCache(str(tmp_path / "cache.json")), progress.append)
    finally:
        client.session.close()
    assert len(snapshot["titles"]) == 39 and snapshot["complete"]
    assert snapshot["distributions"] == {"manga": [i * 10 for i in range(2, 41)]}
    assert len(calls) == 2  # Фиктивному total_pages не доверяем: идём до пустой страницы.
    assert "каталог: 2 запросов, 39 готовых карточек" in progress[-1]
    assert "детали: 0 запросов, 0 из кэша" in progress[-1]
    assert "другие типы: 1" in progress[-1]


def test_mangalib_uses_60_title_pages_with_votes_without_details(tmp_path):
    calls = []
    catalog = [{"id": i, "slug_url": f"{i}--title", "type": {"label": "Манга"},
                "releaseDate": "2005", "rating": {"votes": (i - 1) * 10,
                "average": "10", "votesFormated": "999 K"}}
               for i in range(1, 61)]

    class Session:
        def get(self, url, params):
            calls.append((url, params))
            assert url.endswith("/api/manga"), "complete catalog must not fetch details"
            assert params["limit"] == 60 and params["fields[]"] == ["releaseDate", "rate"]
            data = catalog if params["page"] == 1 else []
            return httpx.Response(200, json={"data": data}, request=httpx.Request("GET", url))

    client = MangaLibPopulation(session=Session())
    client.detail_workers = 1
    client.limiter.acquire = lambda stopped=None: None
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    config = RuPopularityConfig(min_samples=2)
    progress = []
    snapshot = external_snapshot(client, config, lambda: False, cache, progress.append)
    assert snapshot["complete"] and snapshot["metric"] == "rating.votes"
    assert snapshot["distributions"] == {"manga": [i * 10 for i in range(60)]}
    assert len(snapshot["titles"]) == 60 and len(calls) == 2
    assert "каталог: 2 запросов, 60 готовых карточек" in progress[-1]
    assert "детали: 0 запросов, 0 из кэша" in progress[-1]
    external_snapshot(client, config, lambda: False, cache)
    assert len(calls) == 4
