# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""TestGraphql. Public namespace: test_shikimori_api."""
import test_shikimori_api as _api


# ── клиент: GraphQL ──────────────────────────────────────────────────────────
class TestGraphql:
    def test_success(self):
        s = _api.FakeSession(routes=[
            ("/api/graphql", _api.FakeResponse(json_data={"data": {"genres": [1]}}))])
        assert _api._client(s)._graphql("query{}") == {"genres": [1]}

    def test_manual_redirect_preserves_post(self):
        seen_urls = []

        def handler(url, **kw):
            seen_urls.append(url)
            if "old-shikimori.example" in url:
                return _api.FakeResponse(status_code=301,
                                    headers={"Location": "https://shikimori.io/api/graphql"},
                                    url=url)
            return _api.FakeResponse(json_data={"data": {"ok": True}}, url=url)
        s = _api.FakeSession(routes=[("graphql", handler)])
        client = _api._client(s)
        client.base_url = "https://old-shikimori.example"
        out = client._graphql("query{}", {"v": 1})
        assert out == {"ok": True}
        assert len(seen_urls) == 2
        # тело POST сохранено при редиректе
        assert s.calls[-1][2]["json"]["query"] == "query{}"

    def test_graphql_errors_raise(self):
        s = _api.FakeSession(routes=[("graphql", _api.FakeResponse(
            json_data={"errors": [{"message": "field unknown"}]}))])
        with _api.pytest.raises(_api.api.ShikimoriError, match="field unknown"):
            _api._client(s)._graphql("query{}")

    def test_4xx_raises(self):
        s = _api.FakeSession(routes=[("graphql", _api.FakeResponse(status_code=400))])
        with _api.pytest.raises(_api.api.ShikimoriError, match="400"):
            _api._client(s)._graphql("query{}")

TestGraphql.__module__ = _api.__name__
_api.TestGraphql = TestGraphql

# ── высокоуровневые методы ───────────────────────────────────────────────────
class TestHighLevel:
    def test_search_titles(self):
        s = _api.FakeSession(routes=[
            ("/api/animes", _api.FakeResponse(json_data=[_api.SAMPLE_JSON, "мусор"]))])
        out = _api._client(s).search_titles("anime", page=1, limit=10, kind="tv")
        assert len(out) == 1 and out[0].id == 42
        params = s.calls[0][2]["params"]
        assert params["page"] == 1 and params["limit"] == 10 and params["kind"] == "tv"

    def test_search_titles_manga_endpoint(self):
        s = _api.FakeSession(routes=[("/api/mangas", _api.FakeResponse(json_data=[]))])
        _api._client(s).search_titles("manga")
        assert "/api/mangas" in s.calls[0][1]

    def test_search_limit_clamped(self):
        s = _api.FakeSession(routes=[("/api/animes", _api.FakeResponse(json_data=[]))])
        _api._client(s).search_titles("anime", page=-5, limit=500)
        params = s.calls[0][2]["params"]
        assert params["page"] == 1 and params["limit"] == 50

    def test_search_empty_params_dropped(self):
        s = _api.FakeSession(routes=[("/api/animes", _api.FakeResponse(json_data=[]))])
        _api._client(s).search_titles("anime", kind="", status=None, genre_v2=[])
        params = s.calls[0][2]["params"]
        assert "kind" not in params and "status" not in params and "genre_v2" not in params

    def test_search_not_list_raises(self):
        s = _api.FakeSession(routes=[("/api/animes", _api.FakeResponse(json_data={"a": 1}))])
        with _api.pytest.raises(_api.api.ShikimoriError, match="список"):
            _api._client(s).search_titles("anime")

    def test_get_anime(self):
        s = _api.FakeSession(routes=[("/api/animes/42", _api.FakeResponse(json_data=_api.SAMPLE_JSON))])
        assert _api._client(s).get_anime(42)["name"] == "Naruto"

    def test_get_anime_not_dict(self):
        s = _api.FakeSession(routes=[("/api/animes/42", _api.FakeResponse(json_data=[1]))])
        with _api.pytest.raises(_api.api.ShikimoriError):
            _api._client(s).get_anime(42)

    def test_genres_graphql(self):
        s = _api.FakeSession(routes=[
            ("graphql", _api.FakeResponse(json_data={"data": {"genres": [
                {"id": "5", "name": "Mecha", "russian": "Меха", "kind": "theme"},
                {"id": "мусор", "name": "x"},
            ]}}))])
        out = _api._client(s).genres("anime")
        assert out == [{"id": 5, "name": "Mecha", "russian": "Меха", "kind": "theme"}]

    def test_genres_fallback_rest(self):
        s = _api.FakeSession(routes=[
            ("graphql", _api.FakeResponse(status_code=400)),
            ("/api/genres", _api.FakeResponse(json_data=[
                {"id": 1, "name": "Action", "entry_type": "anime"},
                {"id": 2, "name": "Josei", "entry_type": "manga"},
                {"id": 3, "name": "Old", "kind": None},
            ]))])
        out = _api._client(s).genres("anime")
        names = [g["name"] for g in out]
        assert "Action" in names and "Old" in names and "Josei" not in names

    def test_genres_rest_not_list(self):
        s = _api.FakeSession(routes=[
            ("graphql", _api.FakeResponse(status_code=400)),
            ("/api/genres", _api.FakeResponse(json_data={"x": 1}))])
        assert _api._client(s).genres("anime") == []

    def test_close_swallows(self):
        class S(_api.FakeSession):
            def close(self):
                raise RuntimeError("boom")
        _api._client(S()).close()  # не должно бросить

    def test_requires_requests(self, monkeypatch):
        monkeypatch.setattr(_api.api, "_HAS_REQUESTS", False)
        with _api.pytest.raises(_api.api.ShikimoriError, match="requests"):
            _api.api.ShikimoriApiClient()

TestHighLevel.__module__ = _api.__name__
_api.TestHighLevel = TestHighLevel

# ── find_anime ───────────────────────────────────────────────────────────────
def _page(ids, per_page=None):
    return [dict(_api.SAMPLE_JSON, id=i, score=8.0) for i in ids]

_page.__module__ = _api.__name__
_api._page = _page

class TestFindAnime:
    def _client_pages(self, pages):
        """Клиент, отдающий подготовленные страницы по номеру page."""
        def handler(url, **kw):
            page = kw["params"]["page"]
            data = pages.get(page, [])
            return _api.FakeResponse(json_data=data)
        s = _api.FakeSession(routes=[("/api/animes", handler)])
        return _api._client(s), s

    def test_pagination_until_short_page(self):
        pages = {1: _api._page(range(1, 51)), 2: _api._page(range(51, 61))}
        c, s = self._client_pages(pages)
        out = _api.api.find_anime(c, _api.api.AnimeFilter(), per_page=50)
        assert len(out) == 60
        assert len([x for x in s.calls]) == 2  # третья страница не запрашивалась

    def test_dedup_across_pages(self):
        pages = {1: _api._page(range(1, 51)), 2: _api._page([50, 51])}
        c, _ = self._client_pages(pages)
        out = _api.api.find_anime(c, _api.api.AnimeFilter(), per_page=50)
        assert len(out) == 51
        assert len({a.id for a in out}) == 51

    def test_local_filter_applied(self):
        pages = {1: [dict(_api.SAMPLE_JSON, id=1, score=9.0),
                     dict(_api.SAMPLE_JSON, id=2, score=5.0)]}
        c, _ = self._client_pages(pages)
        out = _api.api.find_anime(c, _api.api.AnimeFilter(score_min=8.0))
        assert [a.id for a in out] == [1]

    def test_should_stop(self):
        pages = {i: _api._page(range(i * 100, i * 100 + 50)) for i in range(1, 10)}
        c, s = self._client_pages(pages)
        stops = iter([False, True])
        _api.api.find_anime(c, _api.api.AnimeFilter(), per_page=50,
                       should_stop=lambda: next(stops, True))
        assert len(s.calls) == 1

    def test_error_first_page_raises(self):
        s = _api.FakeSession(routes=[("/api/animes", _api.FakeResponse(status_code=403))])
        with _api.pytest.raises(_api.api.ShikimoriError):
            _api.api.find_anime(_api._client(s), _api.api.AnimeFilter())

    def test_error_later_page_returns_partial(self):
        state = {"n": 0}

        def handler(url, **kw):
            state["n"] += 1
            if state["n"] == 1:
                return _api.FakeResponse(json_data=_api._page(range(1, 51)))
            return _api.FakeResponse(status_code=429)
        s = _api.FakeSession(routes=[("/api/animes", handler)])
        # max_retries=0 — чтобы 429 сразу превратился в ошибку страницы
        c = _api.api.ShikimoriApiClient(session=s, max_retries=0)
        out = _api.api.find_anime(c, _api.api.AnimeFilter(), per_page=50)
        assert len(out) == 50

    def test_progress_and_on_batch(self):
        pages = {1: _api._page([1, 2])}
        c, _ = self._client_pages(pages)
        prog, batches = [], []
        _api.api.find_anime(c, _api.api.AnimeFilter(), per_page=50,
                       progress=lambda p, n: prog.append((p, n)),
                       on_batch=lambda b: batches.append(len(b)))
        assert prog == [(1, 2)]
        assert batches == [2]  # один батч из двух новых тайтлов

    def test_callback_errors_swallowed(self):
        pages = {1: _api._page([1])}
        c, _ = self._client_pages(pages)

        def bad_cb(*a):
            raise RuntimeError("плохой колбэк")
        out = _api.api.find_anime(c, _api.api.AnimeFilter(), progress=bad_cb, on_batch=bad_cb)
        assert len(out) == 1

    def test_max_pages_cap(self):
        pages = {i: _api._page(range(i * 1000, i * 1000 + 50)) for i in range(1, 20)}
        c, s = self._client_pages(pages)
        _api.api.find_anime(c, _api.api.AnimeFilter(), per_page=50, max_pages=3)
        assert len(s.calls) == 3

    def test_quick_find_closes_own_client(self, monkeypatch):
        closed = []

        class C(_api.api.ShikimoriApiClient):
            def close(self):
                closed.append(1)
        s = _api.FakeSession(routes=[("/api/animes", _api.FakeResponse(json_data=[]))])
        monkeypatch.setattr(_api.api, "ShikimoriApiClient",
                            lambda *a, **k: C(session=s))
        out = _api.api.quick_find("наруто", max_score=6)
        assert out == []
        assert closed == [1]

    def test_quick_find_external_client_not_closed(self):
        closed = []

        class C(_api.api.ShikimoriApiClient):
            def close(self):
                closed.append(1)
        s = _api.FakeSession(routes=[("/api/animes", _api.FakeResponse(json_data=[]))])
        c = C(session=s)
        _api.api.quick_find("x", client=c)
        assert closed == []

TestFindAnime.__module__ = _api.__name__
_api.TestFindAnime = TestFindAnime
