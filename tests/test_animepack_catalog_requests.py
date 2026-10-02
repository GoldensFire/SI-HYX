# -*- coding: utf-8 -*-
"""Bulk refresh must gain throughput without skipping pages or losing Stop data."""
import re
from types import SimpleNamespace

import pytest

import animepack as ap
from animepack_api import AnimePackApiError, ShikimoriApi
from si_hyx_parts.animepack.catalog_pages import iter_catalog_pages
from si_hyx_parts.animepack.ru_popularity_math import RuPopularityConfig
from si_hyx_parts.animepack.ru_popularity_refresh import shikimori_snapshot
from si_hyx_parts.animepack_api.ru_manga_clients import ReMangaPopulation


def card(ident):
    return {"id": str(ident), "malId": str(ident), "kind": "manga",
            "score": 8.0, "status": "released", "airedOn": {"year": 2005},
            "releasedOn": {"year": 2010},
            "statusesStats": [{"status": "completed", "count": ident * 100}]}


def api_with(send):
    api = ShikimoriApi()
    api._client = SimpleNamespace(_graphql=send)
    api.limiter = SimpleNamespace(acquire=lambda: None)
    return api


def selections(query):
    return [(int(alias), int(page)) for alias, page in re.findall(
        r"p(\d+): (?:animes|mangas)\(page: (\d+)", query)]


@pytest.mark.parametrize("manga,population,count,cost", [
    (False, False, 2, 67), (True, False, 4, 47), (True, True, 15, 12)])
def test_one_request_returns_the_maximum_full_pages(manga, population, count, cost):
    calls = []

    def send(query, variables):
        calls.append(query)
        # Deliberately reverse JSON key order; caller must retain page order.
        return {f"p{alias}": [card((page - 1) * 50 + i + 1) for i in range(50)]
                for alias, page in reversed(selections(query))}

    result = api_with(send).catalog_pages(3, manga=manga, population=population,
        kinds=iter(["manga"]), season="2000_2026", genres_exclude=(12,), order="id")
    assert len(calls) == 1
    assert len(result) == count and sum(map(len, result)) == count * 50
    assert [rows[0]["id"] for rows in result] == [str(101 + i * 50) for i in range(count)]
    assert calls[0].count('kind: "manga"') == count
    assert calls[0].count('season: "2000_2026"') == count
    assert calls[0].count('genre: "!12"') == count
    assert calls[0].count("limit: 50") == count
    assert count * cost <= 190 < (count + 1) * cost
    if population:
        assert "poster" not in calls[0] and "statusesStats" in calls[0]


def test_lower_query_budget_retries_and_remembers_size_without_skipping_pages():
    calls = []

    def send(query, variables):
        pages = selections(query)
        calls.append([page for _, page in pages])
        if len(pages) > 2:
            raise RuntimeError("Query has complexity of 188, which exceeds max complexity of 100")
        return {f"p{alias}": [card(page)] for alias, page in pages}

    api = api_with(send)
    result = list(iter_catalog_pages(api, 5, lambda: False, manga=True, order="id"))
    assert [page for page, _ in result] == [1, 2, 3, 4, 5]
    assert calls == [[1, 2, 3, 4], [1, 2, 3], [1, 2], [3, 4], [5]]


@pytest.mark.parametrize("data", [{"p0": []}, {"p0": [], "p1": None},
                                   {"p0": [], "p1": [None]}])
def test_missing_or_malformed_alias_is_an_error_instead_of_catalog_end(data):
    with pytest.raises(AnimePackApiError, match="страница"):
        api_with(lambda *args: data).catalog_pages()


def test_network_failure_is_not_retried_as_a_smaller_batch():
    calls = []

    def send(*args):
        calls.append(1)
        raise RuntimeError("network timeout")

    with pytest.raises(AnimePackApiError, match="network timeout"):
        api_with(send).catalog_pages(manga=True)
    assert len(calls) == 1


def test_page_normalization_and_iterable_filters_remain_stable_across_requests():
    calls = []

    def send(query, variables):
        calls.append(query)
        return {f"p{alias}": [card(page)] for alias, page in selections(query)}

    api = api_with(send)
    api.catalog_pages(0)
    assert selections(calls.pop()) == [(0, 1), (1, 2)]
    list(iter_catalog_pages(api, 4, lambda: False, kinds=iter(["tv"])))
    assert len(calls) == 2
    assert all(query.count('kind: "tv"') == 2 for query in calls)


def test_iterator_honors_page_cap_and_stops_at_the_first_empty_page():
    calls = []

    def send(query, variables):
        pages = selections(query)
        calls.append([page for _, page in pages])
        return {f"p{alias}": [card(page)] if page < 6 else [] for alias, page in pages}

    result = list(iter_catalog_pages(api_with(send), 7, lambda: False, manga=True))
    assert [page for page, _ in result] == [1, 2, 3, 4, 5, 6]
    assert calls == [[1, 2, 3, 4], [5, 6, 7]]


@pytest.mark.parametrize("stopping", [False, True])
def test_refresh_saves_all_received_cards_and_completion_only_after_end(tmp_path, stopping):
    stop = [False]
    calls = []

    def send(query, variables):
        pages = selections(query)
        calls.append([page for _, page in pages])
        stop[0] = stopping
        return {f"p{alias}": [card(page)] if page <= 2 else [] for alias, page in pages}

    settings = ap.PackSettings(rounds=1, themes=1, questions=5)
    cache = ap.ShikimoriDbCache(str(tmp_path / "db.json"))
    generator = ap.AnimePackGenerator(settings, shikimori=api_with(send),
                                    db_cache=cache, should_stop=lambda: stop[0])
    assert generator.fetch_full_catalog() == [1, 2]
    saved = ap.ShikimoriDbCache(str(tmp_path / "db.json"))
    signature = ap.shiki_cache_signature(settings)
    assert len(saved.cards("anime", signature)) == 2
    assert saved.is_complete("anime", signature) is (not stopping)
    assert calls == ([[1, 2]] if stopping else [[1, 2], [3, 4]])


def test_population_selection_keeps_the_original_book_index(tmp_path):
    originals = [card(1), card(2)]
    calls = []

    def send(query, variables):
        calls.append(query)
        subset = [{key: value for key, value in row.items() if key != "malId"}
                  for row in originals]
        return {f"p{alias}": subset if page == 1 else []
                for alias, page in selections(query)}

    cache = ap.ShikimoriDbCache(str(tmp_path / "db.json"))
    cache.remember_memo("manga_favorites", 1, 200)
    generator = SimpleNamespace(shikimori=api_with(send), db_cache=cache,
                                stopped=lambda: False, log=lambda message: None)
    snapshot = shikimori_snapshot(generator, RuPopularityConfig(min_samples=2))
    expected = sorted(ap.SongCandidate({}, row, media="manga",
        favorites=200 if row["id"] == "1" else -1).book_index for row in originals)
    assert snapshot["book_index"]["manga"] == expected
    assert snapshot["readership"]["manga"] == [1000, 2000]
    assert len(calls) == 1 and len(selections(calls[0])) == 15
    assert 'kind: "manga,manhwa,manhua"' in calls[0]
    assert "season:" not in calls[0] and "genre:" not in calls[0]


def test_unfiltered_full_catalog_has_no_pack_filters_and_does_not_change_settings(tmp_path):
    calls = []

    def send(query, variables):
        calls.append(query)
        return {f"p{alias}": [card(1)] if page == 1 else []
                for alias, page in selections(query)}

    settings = ap.PackSettings(year_from=2015, year_to=2020, score_from=8,
                               genres_exclude=[12], manga_kinds={"manga": True})
    cache = ap.ShikimoriDbCache(str(tmp_path / "db.json"))
    generator = ap.AnimePackGenerator(settings, shikimori=api_with(send), db_cache=cache)
    assert generator.fetch_full_catalog(manga=True, unfiltered=True) == [1]
    assert 'kind: "manga,manhwa,manhua,one_shot,doujin"' in calls[0]
    assert all(field not in calls[0] for field in ("season:", "score:", "genre:"))
    assert settings.year_from == 2015 and settings.manga_kinds == {"manga": True}
    assert any(complete for _, complete in cache.buckets("manga").values())


def test_repeated_nonempty_page_is_not_a_complete_catalog(tmp_path):
    def send(query, variables):
        return {f"p{alias}": [card(1)] for alias, _ in selections(query)}

    settings = ap.PackSettings()
    cache = ap.ShikimoriDbCache(str(tmp_path / "db.json"))
    generator = ap.AnimePackGenerator(settings, shikimori=api_with(send), db_cache=cache)
    assert generator.fetch_full_catalog(manga=True) == [1]
    assert not cache.is_complete("manga", ap.shiki_cache_signature(settings, True))
    assert "повторил" in generator._catalog_refresh_errors["manga"]


def test_remanga_catalog_requests_its_server_maximum():
    client = ReMangaPopulation()
    calls = []
    client.get = lambda path, params: calls.append((path, params)) or {"content": []}
    assert client.catalog_page(7) == []
    assert calls == [("/api/titles/", {"page": 7, "count": 40,
                      "ordering": "id", "content": "manga"})]
