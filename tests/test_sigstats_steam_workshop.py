# -*- coding: utf-8 -*-
"""Тесты sigstats/steam_workshop.py — Steam Web API (только метаданные, без
скачивания depot-файлов) на синтетических JSON-ответах."""
import pytest

from sigstats import steam_workshop as sw
from sigstats import config as scfg
from conftest import FakeResponse, FakeSession


def _raw_item(pid="111", title="Стим пак", creator="7656119", subs=42,
             created=1700000000, tags=("Аниме",), desc="Описание пака"):
    return {
        "publishedfileid": pid,
        "title": title,
        "creator": creator,
        "subscriptions": subs,
        "time_created": created,
        "tags": [{"tag": t} for t in tags],
        "file_description": desc,
    }


# ── _parse_item ──────────────────────────────────────────────────────────────
class TestParseItem:
    def test_basic(self):
        item = sw._parse_item(_raw_item())
        assert item.steam_id == "111"
        assert item.name == "Стим пак"
        assert item.name_norm == "стим пак"
        assert item.subscriptions == 42
        assert item.date_published == "2023-11-14"
        assert item.tags == ["Аниме"]
        assert item.description == "Описание пака"
        assert item.authors == []

    def test_missing_title_skipped(self):
        assert sw._parse_item({"publishedfileid": "1", "title": ""}) is None

    def test_missing_id_skipped(self):
        assert sw._parse_item({"title": "x"}) is None

    def test_missing_optional_fields(self):
        item = sw._parse_item({"publishedfileid": "9", "title": "Минимальный"})
        assert item.date_published is None
        assert item.tags == []
        assert item.description is None
        assert item.subscriptions is None

    def test_as_package(self):
        item = sw._parse_item(_raw_item())
        pkg = item.as_package()
        assert pkg["source"] == "steam"
        assert pkg["steam_id"] == "111"
        assert pkg["sibrowser_id"] is None
        assert pkg["download_count"] == 42
        assert pkg["length_group"] == "Неизвестно"  # question_count неизвестен
        assert pkg["description"] == "Описание пака"


# ── query_files ──────────────────────────────────────────────────────────────
class TestQueryFiles:
    def test_basic_request(self):
        resp = FakeResponse(json_data={"response": {
            "total": 1, "publishedfiledetails": [_raw_item()]}})
        s = FakeSession(routes=[("IPublishedFileService", resp)])
        items, total = sw.query_files(s, "APIKEY", page=1, numperpage=50)
        assert total == 1
        assert items[0]["publishedfileid"] == "111"
        method, url, kw = s.calls[0]
        assert kw["params"]["key"] == "APIKEY"
        assert kw["params"]["appid"] == sw.SIGAME_APP_ID

    def test_empty_response(self):
        resp = FakeResponse(json_data={"response": {}})
        s = FakeSession(routes=[("IPublishedFileService", resp)])
        items, total = sw.query_files(s, "APIKEY")
        assert items == [] and total == 0

    def test_http_error(self):
        resp = FakeResponse(status_code=403)
        s = FakeSession(routes=[("IPublishedFileService", resp)])
        import requests
        with pytest.raises(requests.HTTPError):
            sw.query_files(s, "BADKEY")


# ── resolve_creator_names ────────────────────────────────────────────────────
class TestResolveCreatorNames:
    def test_basic(self):
        resp = FakeResponse(json_data={"response": {"players": [
            {"steamid": "111", "personaname": "Вася"},
            {"steamid": "222", "personaname": "Петя"},
        ]}})
        s = FakeSession(routes=[("GetPlayerSummaries", resp)])
        names = sw.resolve_creator_names(s, "APIKEY", ["111", "222"])
        assert names == {"111": "Вася", "222": "Петя"}

    def test_dedup_and_empty(self):
        resp = FakeResponse(json_data={"response": {"players": []}})
        s = FakeSession(routes=[("GetPlayerSummaries", resp)])
        names = sw.resolve_creator_names(s, "APIKEY", ["1", "1", "", None])
        assert names == {}
        assert len(s.calls) == 1  # дедуп по id и без пустых

    def test_request_failure_tolerated(self):
        s = FakeSession(default=FakeResponse(status_code=500))
        names = sw.resolve_creator_names(s, "APIKEY", ["1"])
        assert names == {}


# ── iter_items ───────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def fast_scrape(monkeypatch):
    monkeypatch.setattr(scfg, "SCRAPE_DELAY", 0)


class TestIterItems:
    def _session(self, pages, players=None):
        def query_route(url, **kw):
            page = kw["params"]["page"]
            items = pages.get(page, [])
            total = sum(len(v) for v in pages.values())
            return FakeResponse(json_data={"response": {
                "total": total, "publishedfiledetails": items}})
        routes = [("IPublishedFileService", query_route)]
        if players is not None:
            routes.append(("GetPlayerSummaries", FakeResponse(
                json_data={"response": {"players": players}})))
        else:
            routes.append(("GetPlayerSummaries", FakeResponse(
                json_data={"response": {"players": []}})))
        return FakeSession(routes=routes)

    def test_basic_yield_with_author(self):
        s = self._session({1: [_raw_item(pid="1", title="Пак А", creator="700")]},
                          players=[{"steamid": "700", "personaname": "Автор"}])
        out = list(sw.iter_items(s, "KEY", skip_norms=set(), numperpage=50))
        assert len(out) == 1
        assert out[0].name == "Пак А"
        assert out[0].authors == ["Автор"]

    def test_skip_norms_dedup(self):
        s = self._session({1: [_raw_item(pid="1", title="Пак")]})
        out = list(sw.iter_items(s, "KEY", skip_norms={"пак"}, numperpage=50))
        assert out == []

    def test_pagination_stops_at_total(self):
        s = self._session({1: [_raw_item(pid="1", title="Пак 1")]})
        out = list(sw.iter_items(s, "KEY", skip_norms=set(), numperpage=50))
        assert [i.name for i in out] == ["Пак 1"]
        # только один запрос страницы — total достигнут после первой страницы
        query_calls = [c for c in s.calls if "IPublishedFileService" in c[1]]
        assert len(query_calls) == 1

    def test_should_stop(self):
        s = self._session({1: [_raw_item(pid="1", title="Пак")]})
        out = list(sw.iter_items(s, "KEY", skip_norms=set(),
                                 should_stop=lambda: True))
        assert out == []

    def test_query_error_stops(self):
        s = FakeSession(default=FakeResponse(status_code=500))
        msgs = []
        out = list(sw.iter_items(s, "KEY", skip_norms=set(),
                                 progress_cb=msgs.append))
        assert out == []
        assert any("Ошибка" in m for m in msgs)

    def test_empty_page_stops(self):
        s = self._session({})
        out = list(sw.iter_items(s, "KEY", skip_norms=set()))
        assert out == []


class TestWorkshopUrl:
    def test_url(self):
        assert sw.workshop_url("123") == \
            "https://steamcommunity.com/sharedfiles/filedetails/?id=123"
