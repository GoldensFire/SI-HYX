# -*- coding: utf-8 -*-
"""Contracts observed on the official mirrors, without live network in tests."""
from copy import deepcopy
import httpx
import pytest

import animepack as ap
from animepack_api import MangaLibApi, MangaPageSources, ReMangaApi
from si_hyx_parts.animepack_api.remanga_reader import publicly_released
from si_hyx_parts.animepack_api.ru_manga_clients import (
    MangaLibPopulation, ReMangaPopulation)
from si_hyx_parts.animepack.ru_popularity_math import RuPopularityConfig
from si_hyx_parts.animepack.ru_popularity_refresh import external_snapshot
from test_manga_ru_cache import title
from test_manga_ru_pages import Population
from test_manga_ru_popularity import manga


def test_mangalib_uses_frontend_host_http2_and_required_referer(monkeypatch):
    calls = []
    class Client:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def get(self, url, **kwargs):
            calls.append((url, kwargs))
            return httpx.Response(200, json={"data": []}, request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx, "Client", Client)
    MangaLibPopulation().catalog_page(2)
    assert calls[0]["http2"] is True
    assert calls[0]["headers"]["Site-Id"] == "1"
    assert calls[0]["headers"]["Referer"] == "https://mangalib.org/ru"
    assert calls[1] == ("https://api.cdnlibs.org/api/manga", {"params": {
        "site_id[]": 1, "page": 2, "limit": 60,
        "sort_by": "created_at", "sort_type": "asc",
        "fields[]": ["releaseDate", "rate"]}})


@pytest.mark.parametrize("kind", ["Манхва", {"id": 2, "name": "Манхва"}, 2])
def test_remanga_current_catalog_and_detail_types(kind):
    row = ReMangaPopulation().normalize({"id": 2, "dir": "diet", "type": kind,
        "is_licensed": False, "count_bookmarks": 30})
    assert row["kind"] == "manhwa" and row["raw_metric"] == 30
    assert ReMangaPopulation.base_url == "https://xn--80aaig9ahr.xn--c1avg"


@pytest.mark.parametrize("label", ["Западный комикс", "Рукомикс", "Индонезийский комикс"])
def test_remanga_known_other_type_labels_are_excluded_without_details(label):
    client = ReMangaPopulation()
    try:
        row = client.normalize({"id": 132, "dir": "western", "type": label,
                                "is_licensed": False, "count_bookmarks": 10}, catalog=True)
        assert row["kind"] == "other" and row["status"] == "NORMAL"
        detail = client.normalize({"id": 132, "dir": "western",
                                   "type": {"id": 4, "name": "Западный комикс"},
                                   "is_licensed": False, "count_bookmarks": 10})
        assert detail["kind"] == "other"
    finally:
        client.session.close()


def test_remanga_unknown_catalog_type_still_requires_details():
    client = ReMangaPopulation()
    try:
        row = client.normalize({"id": 132, "dir": "unknown", "type": "Новый тип",
                                "is_licensed": False, "count_bookmarks": 10}, catalog=True)
        assert row["kind"] == "" and row["status"] == "ERROR"
    finally:
        client.session.close()


def test_current_mangalib_votes_ignore_views_average_and_formatted_text():
    row = MangaLibPopulation().normalize({"id": 2, "slug_url": "2--07-ghost",
        "type": {"label": "Манга"}, "close_view": 0, "is_licensed": False,
        "views": {"total": 209301, "short": "209.3 K"}, "rate": 10,
        "rating": {"votes": 614, "votesFormated": "999 K", "average": "9.45"}})
    assert row["raw_metric"] == 614 and row["metric"] == "rating.votes"
    assert row["status"] == "NORMAL" and row["fields"]["is_licensed"] is False
    row = MangaLibPopulation().normalize({"id": 2, "slug_url": "2--07-ghost",
        "close_view": 0, "is_licensed": True, "views": {"total": 209301}})
    assert row["raw_metric"] is None and row["status"] == "RIGHTS_RESTRICTED"


def test_naive_release_dates_and_live_remanga_page_arrays():
    assert publicly_released({"delay_pub_date": "2020-02-03T02:39:10.994532"})
    assert not publicly_released({"delay_pub_date": "2999-02-03T02:39:10.994532"})
    population = Population()
    population.detail["delay_pub_date"] = "2020-02-03T02:39:10.994532"
    population.detail["pages"] = [[{"link": f"https://cdn.test/{i}.webp"}]
                                  for i in range(12)]
    reader = ReMangaApi(population=population)
    assert reader.panel_url(manga()).startswith("https://cdn.test/")
    population.detail["is_paid"] = True
    assert reader.pages({"id": "10", "free": True}) == []


def test_noisy_searches_keep_exact_candidates_and_still_validate_details():
    client = ReMangaPopulation()
    def get(path, params=None):
        if path == "/api/search/":
            return {"content": [{"dir": "wanted", "main_name": manga()["name"]}] + [
                {"dir": f"{params['query']}-{i}", "main_name": f"Unrelated result {i}"}
                for i in range(5)]}
        assert path == "/api/titles/wanted/"
        return {"content": {"id": 1, "dir": "wanted", "type": {"id": 2},
            "main_name": manga()["name"], "secondary_name": manga()["russian"],
            "issue_year": 2015, "is_licensed": False, "count_bookmarks": 30}}
    client.get = get
    assert [row["id"] for row in client.search(manga())] == ["1"]


def test_mangalib_census_enriches_catalog_without_metric_or_restrictions(tmp_path):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    class Catalog:
        source, metric = "mangalib", "views"
        def catalog_page(self, page):
            return [title("mangalib", id=str(i), status="ERROR", raw_metric=None)
                    for i in (1, 2)] if page == 1 else []

        def details(self, row):
            return row | {"status": "NORMAL", "raw_metric": 209301}
    snapshot = external_snapshot(Catalog(), RuPopularityConfig(min_samples=2),
                                 lambda: False, cache)
    assert snapshot["distributions"] == {"manhwa": [209301, 209301]}


class LibPopulation:
    def __init__(self):
        self.row = title("mangalib", fields={"is_licensed": False})
        self.branch = {"id": 10, "branch_id": None, "expired_type": 0,
                       "created_at": "2020-01-01T00:00:00Z"}
        self.detail = {"id": 10, "manga_id": "ext", "expired_type": 0,
                       "bundle_id": None, "pages": [
                           {"url": f"//manga/title/{i}.png", "external": 0, "chunks": 0}
                           for i in range(12)]}
        self.calls = []

    def search(self, card):
        return [deepcopy(self.row)]

    def get(self, path, params=None):
        self.calls.append((path, params))
        if path.endswith("/chapters"):
            return {"data": [{"volume": "0", "number": "0", "bundle_id": None,
                              "branches": [deepcopy(self.branch)]}]}
        if path.endswith("/chapter"):
            return {"data": deepcopy(self.detail)}
        assert path == "/api/constants"
        return {"data": {"imageServers": [
            {"id": "main", "site_ids": [2], "url": "https://wrong.test"},
            {"id": "main", "site_ids": [1, 3], "url": "https://img.test"}]}}


def test_mangalib_pages_join_live_server_and_enter_existing_source_pool():
    population = LibPopulation()
    reader = MangaLibApi(population=population, language="ru")
    sources = MangaPageSources(sources={"mangalib": True}, clients={"mangalib": reader})
    url = sources.panel_url(manga())
    assert url.startswith("https://img.test//manga/title/")
    assert sources.last_source == "MangaLib" and sources.last_chapter == "10"
    assert sources.last_source_link == "https://mangalib.org/ru/external-title"
    assert sources.panel_url(manga(), {f"https://img.test//manga/title/{i}.png"
                                      for i in range(12)}) == ""
    assert sum(path == "/api/constants" for path, _ in population.calls) == 1


@pytest.mark.parametrize("change", [{"expired_type": 1}, {"bundle_id": 123},
    {"publish_at": "2999-01-01T00:00:00Z"}])
def test_mangalib_paid_or_future_list_entries_never_fetch_detail(change):
    population = LibPopulation()
    population.branch.update(change)
    assert MangaLibApi(population=population).panel_url(manga()) == ""
    assert len(population.calls) == 1


@pytest.mark.parametrize("change", [{"expired_type": 1}, {"bundle_id": 123},
    {"bundle": {"price": 100}}, {"id": 99}, {"manga_id": "wrong"},
    {"publish_at": "2999-01-01T00:00:00Z"}])
def test_mangalib_rechecks_detail_access_identity_and_publication(change):
    population = LibPopulation()
    population.detail.update(change)
    assert MangaLibApi(population=population).panel_url(manga()) == ""
    assert all(path != "/api/constants" for path, _ in population.calls)


def test_mangalib_rejects_restricted_adult_unknown_and_foreign_language_titles():
    for fields, status in [({"is_licensed": True}, "NORMAL"),
                           ({"is_licensed": False}, "RIGHTS_RESTRICTED"),
                           ({}, "NORMAL"), ({"is_licensed": False,
                               "ageRestriction": {"label": "18+"}}, "NORMAL")]:
        population = LibPopulation()
        population.row.update(fields=fields, status=status)
        assert MangaLibApi(population=population).panel_url(manga()) == ""
        assert not population.calls
    population = LibPopulation()
    assert MangaLibApi(population=population, language="en").panel_url(manga()) == ""
    assert not population.calls


def test_mangalib_source_accepts_explicit_russian_language():
    settings = ap.PackSettings(manga_sources={"mangalib": True}, manga_lang="ru",
                              pack_manga=True, pct_manga=100, pct_songs=0)
    assert not any("язык глав" in message for message in settings.validate())
