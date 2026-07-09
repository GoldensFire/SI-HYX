# -*- coding: utf-8 -*-
"""Тесты shikimori_api.py: модель, фильтр, клиент с ретраями, find_anime."""
import datetime

import pytest

import shikimori_api as api
from conftest import FakeResponse, FakeSession


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Ретраи не должны реально спать."""
    monkeypatch.setattr(api.time, "sleep", lambda s: None)


# ── views_from_card / index_base_from_card ───────────────────────────────────
class TestViewsFromCard:
    def test_english_keys(self):
        card = {"rates_statuses_stats": [
            {"name": "completed", "value": 100},
            {"name": "watching", "value": 50},
            {"name": "dropped", "value": 10},
            {"name": "planned", "value": 999},
        ]}
        assert api.views_from_card(card) == 160

    def test_russian_labels(self):
        card = {"rates_statuses_stats": [
            {"name": "Просмотрено", "value": 5},
            {"name": "Смотрю", "value": 3},
            {"name": "Брошено", "value": 2},
            {"name": "Запланировано", "value": 100},
            {"name": "Отложено", "value": 50},
        ]}
        assert api.views_from_card(card) == 10

    def test_manga_labels(self):
        card = {"rates_statuses_stats": [
            {"name": "Прочитано", "value": 7},
            {"name": "Читаю", "value": 3},
        ]}
        assert api.views_from_card(card) == 10

    def test_not_dict(self):
        assert api.views_from_card(None) == 0
        assert api.views_from_card("мусор") == 0

    def test_missing_stats(self):
        assert api.views_from_card({}) == 0

    def test_bad_values_skipped(self):
        card = {"rates_statuses_stats": [
            {"name": "completed", "value": "не число"},
            {"name": "watching", "value": 4},
            "мусор",
        ]}
        assert api.views_from_card(card) == 4


class TestIndexBase:
    def test_weights(self):
        card = {"rates_statuses_stats": [
            {"name": "completed", "value": 1},   # 10
            {"name": "watching", "value": 1},    # 8
            {"name": "dropped", "value": 1},     # 6
            {"name": "on_hold", "value": 1},     # 6
            {"name": "planned", "value": 1},     # 2
        ]}
        assert api.index_base_from_card(card) == 32.0

    def test_empty(self):
        assert api.index_base_from_card({}) == 0.0
        assert api.index_base_from_card(None) == 0.0

    def test_components_sorted_and_sum(self):
        card = {"rates_statuses_stats": [
            {"name": "Просмотрено", "value": 2},   # 20
            {"name": "запланировано", "value": 10},  # 20
            {"name": "Смотрю", "value": 1},        # 8
            {"name": "нулевой", "value": 0},
        ]}
        comps = api.index_components_from_card(card)
        labels = [c[0] for c in comps]
        assert set(labels) == {"Просмотрено", "В планах", "Смотрю"}
        assert sum(c[1] for c in comps) == api.index_base_from_card(card)
        # убывание по взвешенному вкладу
        weights = [c[1] for c in comps]
        assert weights == sorted(weights, reverse=True)

    def test_components_empty(self):
        assert api.index_components_from_card(None) == []


# ── kind/status helpers ──────────────────────────────────────────────────────
class TestKindStatusHelpers:
    def test_kinds_for(self):
        assert api.kinds_for("anime") == api.KINDS
        assert api.kinds_for("manga") == api.MANGA_KINDS

    def test_statuses_for(self):
        assert api.statuses_for("manga") == api.MANGA_STATUSES
        assert api.statuses_for("anime") == api.STATUSES

    def test_kind_label(self):
        assert api.kind_label("anime", "tv") == "ТВ-сериал"
        assert api.kind_label("manga", "manhwa") == "Манхва"
        assert api.kind_label("anime", "неизвестный") == "неизвестный"

    def test_status_label(self):
        assert api.status_label("anime", "ongoing") == "Онгоинг"
        assert api.status_label("manga", "paused") == "Пауза"
        assert api.status_label("manga", "x") == "x"


class TestGenreGroup:
    def test_kind_from_api_trusted(self):
        assert api.genre_group({"kind": "theme", "name": "whatever"}) == "theme"
        assert api.genre_group({"kind": "demographic", "name": "x"}) == "demographic"

    def test_by_name_demographic(self):
        assert api.genre_group({"kind": "genre", "name": "Shounen"}) == "demographic"

    def test_by_name_theme(self):
        assert api.genre_group({"kind": "", "name": "Mecha"}) == "theme"

    def test_default_genre(self):
        assert api.genre_group({"name": "Comedy"}) == "genre"

    def test_none_input(self):
        assert api.genre_group(None) == "genre"
        assert api.genre_group({}) == "genre"


# ── Anime model ──────────────────────────────────────────────────────────────
SAMPLE_JSON = {
    "id": "42", "name": "Naruto", "russian": "Наруто", "kind": "tv",
    "score": "8.12", "status": "released", "episodes": "220",
    "episodes_aired": 220, "aired_on": "2002-10-03", "released_on": None,
    "image": {"preview": "/system/animes/preview/42.jpg"},
    "url": "/animes/42-naruto",
}


class TestAnimeModel:
    def test_from_json(self):
        a = api.Anime.from_json(SAMPLE_JSON)
        assert a.id == 42
        assert a.score == pytest.approx(8.12)
        assert a.episodes == 220
        assert a.image_url == api.DEFAULT_BASE_URL + "/system/animes/preview/42.jpg"
        assert a.url == api.DEFAULT_BASE_URL + "/animes/42-naruto"

    def test_title_prefers_russian(self):
        a = api.Anime.from_json(SAMPLE_JSON)
        assert a.title == "Наруто"

    def test_title_fallback_name(self):
        d = dict(SAMPLE_JSON, russian="")
        assert api.Anime.from_json(d).title == "Naruto"

    def test_year(self):
        assert api.Anime.from_json(SAMPLE_JSON).year == 2002

    def test_year_from_released(self):
        d = dict(SAMPLE_JSON, aired_on=None, released_on="2010-01-01")
        assert api.Anime.from_json(d).year == 2010

    def test_year_none(self):
        d = dict(SAMPLE_JSON, aired_on=None, released_on=None)
        assert api.Anime.from_json(d).year is None

    def test_year_garbage(self):
        d = dict(SAMPLE_JSON, aired_on="абвг-10-03", released_on=None)
        assert api.Anime.from_json(d).year is None

    def test_air_date_full(self):
        a = api.Anime.from_json(SAMPLE_JSON)
        assert a.air_date == datetime.date(2002, 10, 3)

    def test_air_date_year_only(self):
        d = dict(SAMPLE_JSON, aired_on="2002")
        assert api.Anime.from_json(d).air_date == datetime.date(2002, 1, 1)

    def test_air_date_feb_clamped(self):
        d = dict(SAMPLE_JSON, aired_on="2020-02-31")
        assert api.Anime.from_json(d).air_date == datetime.date(2020, 2, 28)

    def test_air_date_none(self):
        d = dict(SAMPLE_JSON, aired_on=None, released_on=None)
        assert api.Anime.from_json(d).air_date is None

    def test_date_label_full(self):
        assert api.Anime.from_json(SAMPLE_JSON).date_label == "3 октября 2002"

    def test_date_label_season(self):
        d = dict(SAMPLE_JSON, aired_on="2019-04")
        assert api.Anime.from_json(d).date_label == "Весна 2019"

    def test_date_label_year(self):
        d = dict(SAMPLE_JSON, aired_on="2019")
        assert api.Anime.from_json(d).date_label == "2019"

    def test_date_label_empty(self):
        d = dict(SAMPLE_JSON, aired_on=None, released_on=None)
        assert api.Anime.from_json(d).date_label == ""

    def test_chapters_mapped_to_episodes(self):
        d = dict(SAMPLE_JSON, episodes=None, chapters="120")
        assert api.Anime.from_json(d).episodes == 120

    def test_bad_numbers_default(self):
        d = dict(SAMPLE_JSON, id="мусор", score=None, episodes="x")
        a = api.Anime.from_json(d)
        assert a.id == 0 and a.score == 0.0 and a.episodes == 0

    def test_absolute_image_url_kept(self):
        d = dict(SAMPLE_JSON, image={"preview": "https://cdn.x/im.jpg"})
        assert api.Anime.from_json(d).image_url == "https://cdn.x/im.jpg"

    def test_as_row(self):
        row = api.Anime.from_json(SAMPLE_JSON).as_row()
        assert row["id"] == 42
        assert row["title"] == "Наруто"
        assert row["year"] == 2002
        assert row["url"].endswith("/animes/42-naruto")


# ── AnimeFilter ──────────────────────────────────────────────────────────────
class TestAnimeFilter:
    def test_server_params_full(self):
        f = api.AnimeFilter(query=" наруто ", kind="tv", status="released",
                            score_min=7.5, genres=[1, 2], exclude_genres=[3],
                            order="popularity")
        p = f.to_server_params()
        assert p["search"] == "наруто"
        assert p["kind"] == "tv"
        assert p["status"] == "released"
        assert p["order"] == "popularity"
        assert p["genre_v2"] == "1,2,!3"
        assert p["score"] == "7"  # сервер принимает целое

    def test_invalid_kind_status_skipped(self):
        f = api.AnimeFilter(kind="фильм", status="вышло", order="хаос")
        p = f.to_server_params()
        assert "kind" not in p and "status" not in p and "order" not in p

    def test_manga_kinds_accepted(self):
        f = api.AnimeFilter(kind="manhwa", content_type="manga")
        assert f.to_server_params()["kind"] == "manhwa"

    def test_season_both_years(self):
        f = api.AnimeFilter(year_from=2010, year_to=2015)
        assert f.to_server_params()["season"] == "2010_2015"

    def test_season_swapped_years(self):
        f = api.AnimeFilter(year_from=2015, year_to=2010)
        assert f._season_param() == "2010_2015"

    def test_season_open_upper(self):
        f = api.AnimeFilter(year_from=2017)
        season = f._season_param()
        lo, hi = season.split("_")
        assert lo == "2017"
        assert int(hi) >= datetime.date.today().year + 1

    def test_season_open_lower(self):
        f = api.AnimeFilter(year_to=2017)
        assert f._season_param() == "1900_2017"

    def test_season_empty(self):
        assert api.AnimeFilter()._season_param() == ""

    def _anime(self, **kw):
        base = dict(SAMPLE_JSON)
        base.update(kw)
        return api.Anime.from_json(base)

    def test_matches_local_score(self):
        f = api.AnimeFilter(score_min=8.0, score_max=9.0)
        assert f.matches_local(self._anime(score=8.5))
        assert not f.matches_local(self._anime(score=7.9))
        assert not f.matches_local(self._anime(score=9.1))

    def test_matches_local_episodes(self):
        f = api.AnimeFilter(episodes_min=10, episodes_max=30)
        assert f.matches_local(self._anime(episodes=20))
        assert not f.matches_local(self._anime(episodes=5))
        assert not f.matches_local(self._anime(episodes=100))
        # episodes==0 (неизвестно) не отфильтровывается по максимуму
        assert not f.matches_local(self._anime(episodes=0))  # но min=10 режет

    def test_matches_local_zero_episodes_max_only(self):
        f = api.AnimeFilter(episodes_max=30)
        assert f.matches_local(self._anime(episodes=0))

    def test_matches_local_years(self):
        f = api.AnimeFilter(year_from=2000, year_to=2005)
        assert f.matches_local(self._anime(aired_on="2002-01-01"))
        assert not f.matches_local(self._anime(aired_on="1999-01-01"))
        assert not f.matches_local(self._anime(aired_on="2006-01-01"))

    def test_matches_local_year_unknown_rejected(self):
        f = api.AnimeFilter(year_from=2000)
        assert not f.matches_local(self._anime(aired_on=None, released_on=None))

    def test_validate_ok(self):
        assert api.AnimeFilter(score_min=5, score_max=9).validate() is None

    def test_validate_score(self):
        assert "оценка" in api.AnimeFilter(score_min=9, score_max=5).validate()

    def test_validate_episodes(self):
        assert "эпизодов" in api.AnimeFilter(
            episodes_min=50, episodes_max=10).validate()

    def test_validate_years(self):
        assert "Год" in api.AnimeFilter(year_from=2020, year_to=2010).validate()


# ── клиент: _get с ретраями ──────────────────────────────────────────────────
def _client(session):
    return api.ShikimoriApiClient(session=session, max_retries=2)


class TestClientGet:
    def test_success(self):
        s = FakeSession(routes=[("/api/animes", FakeResponse(json_data=[]))])
        c = _client(s)
        assert c._get("/api/animes") == []

    def test_retry_on_429_then_success(self):
        responses = [FakeResponse(status_code=429, headers={"Retry-After": "0"}),
                     FakeResponse(json_data={"ok": 1})]

        def handler(url, **kw):
            return responses.pop(0)
        s = FakeSession(routes=[("/api/x", handler)])
        assert _client(s)._get("/api/x") == {"ok": 1}

    def test_gives_up_after_retries(self):
        s = FakeSession(routes=[("/api/x", FakeResponse(status_code=503))])
        with pytest.raises(api.ShikimoriError):
            _client(s)._get("/api/x")
        # 1 попытка + 2 ретрая
        assert len(s.calls) == 3

    def test_4xx_no_retry(self):
        s = FakeSession(routes=[("/api/x", FakeResponse(status_code=403))])
        with pytest.raises(api.ShikimoriError, match="403"):
            _client(s)._get("/api/x")
        assert len(s.calls) == 1

    def test_bad_json(self):
        s = FakeSession(routes=[("/api/x", FakeResponse(text="html", raise_json=True))])
        with pytest.raises(api.ShikimoriError, match="JSON"):
            _client(s)._get("/api/x")

    def test_network_error(self):
        import requests as req

        class BoomSession(FakeSession):
            def get(self, url, **kw):
                self.calls.append(("GET", url, kw))
                raise req.ConnectionError("нет сети")
        s = BoomSession()
        with pytest.raises(api.ShikimoriError, match="Сетевая"):
            _client(s)._get("/api/x")
        assert len(s.calls) == 3

    def test_timeout_error(self):
        import requests as req

        class SlowSession(FakeSession):
            def get(self, url, **kw):
                self.calls.append(("GET", url, kw))
                raise req.Timeout("долго")
        with pytest.raises(api.ShikimoriError, match="Таймаут"):
            _client(SlowSession())._get("/api/x")

    def test_backoff_growth(self):
        assert api.ShikimoriApiClient._backoff(0) == 0.5
        assert api.ShikimoriApiClient._backoff(1) == 1.0
        assert api.ShikimoriApiClient._backoff(10) == 8.0  # потолок

    def test_retry_delay_uses_header(self):
        c = _client(FakeSession())
        resp = FakeResponse(status_code=429, headers={"Retry-After": "3"})
        assert c._retry_delay(resp, 0) == 3.0

    def test_retry_delay_header_capped(self):
        c = _client(FakeSession())
        resp = FakeResponse(status_code=429, headers={"Retry-After": "9999"})
        assert c._retry_delay(resp, 0) == 15.0

    def test_retry_delay_bad_header(self):
        c = _client(FakeSession())
        resp = FakeResponse(status_code=429, headers={"Retry-After": "потом"})
        assert c._retry_delay(resp, 1) == api.ShikimoriApiClient._backoff(1)

    def test_headers_set(self):
        s = FakeSession()
        api.ShikimoriApiClient(session=s, token="секрет", user_agent="UA-Test/1.0")
        assert s.headers["User-Agent"] == "UA-Test/1.0"
        assert s.headers["Authorization"] == "Bearer секрет"

    def test_base_url_trailing_slash(self):
        s = FakeSession(routes=[("/api/z", FakeResponse(json_data=1))])
        c = api.ShikimoriApiClient(base_url="https://shikimori.one/", session=s)
        c._get("/api/z")
        assert s.calls[0][1] == "https://shikimori.one/api/z"


# ── клиент: GraphQL ──────────────────────────────────────────────────────────
class TestGraphql:
    def test_success(self):
        s = FakeSession(routes=[
            ("/api/graphql", FakeResponse(json_data={"data": {"genres": [1]}}))])
        assert _client(s)._graphql("query{}") == {"genres": [1]}

    def test_manual_redirect_preserves_post(self):
        seen_urls = []

        def handler(url, **kw):
            seen_urls.append(url)
            if "shikimori.one" in url:
                return FakeResponse(status_code=301,
                                    headers={"Location": "https://shikimori.io/api/graphql"},
                                    url=url)
            return FakeResponse(json_data={"data": {"ok": True}}, url=url)
        s = FakeSession(routes=[("graphql", handler)])
        out = _client(s)._graphql("query{}", {"v": 1})
        assert out == {"ok": True}
        assert len(seen_urls) == 2
        # тело POST сохранено при редиректе
        assert s.calls[-1][2]["json"]["query"] == "query{}"

    def test_graphql_errors_raise(self):
        s = FakeSession(routes=[("graphql", FakeResponse(
            json_data={"errors": [{"message": "field unknown"}]}))])
        with pytest.raises(api.ShikimoriError, match="field unknown"):
            _client(s)._graphql("query{}")

    def test_4xx_raises(self):
        s = FakeSession(routes=[("graphql", FakeResponse(status_code=400))])
        with pytest.raises(api.ShikimoriError, match="400"):
            _client(s)._graphql("query{}")


# ── высокоуровневые методы ───────────────────────────────────────────────────
class TestHighLevel:
    def test_search_titles(self):
        s = FakeSession(routes=[
            ("/api/animes", FakeResponse(json_data=[SAMPLE_JSON, "мусор"]))])
        out = _client(s).search_titles("anime", page=1, limit=10, kind="tv")
        assert len(out) == 1 and out[0].id == 42
        params = s.calls[0][2]["params"]
        assert params["page"] == 1 and params["limit"] == 10 and params["kind"] == "tv"

    def test_search_titles_manga_endpoint(self):
        s = FakeSession(routes=[("/api/mangas", FakeResponse(json_data=[]))])
        _client(s).search_titles("manga")
        assert "/api/mangas" in s.calls[0][1]

    def test_search_limit_clamped(self):
        s = FakeSession(routes=[("/api/animes", FakeResponse(json_data=[]))])
        _client(s).search_titles("anime", page=-5, limit=500)
        params = s.calls[0][2]["params"]
        assert params["page"] == 1 and params["limit"] == 50

    def test_search_empty_params_dropped(self):
        s = FakeSession(routes=[("/api/animes", FakeResponse(json_data=[]))])
        _client(s).search_titles("anime", kind="", status=None, genre_v2=[])
        params = s.calls[0][2]["params"]
        assert "kind" not in params and "status" not in params and "genre_v2" not in params

    def test_search_not_list_raises(self):
        s = FakeSession(routes=[("/api/animes", FakeResponse(json_data={"a": 1}))])
        with pytest.raises(api.ShikimoriError, match="список"):
            _client(s).search_titles("anime")

    def test_search_animes_compat(self):
        s = FakeSession(routes=[("/api/animes", FakeResponse(json_data=[]))])
        assert _client(s).search_animes() == []

    def test_get_anime(self):
        s = FakeSession(routes=[("/api/animes/42", FakeResponse(json_data=SAMPLE_JSON))])
        assert _client(s).get_anime(42)["name"] == "Naruto"

    def test_get_anime_not_dict(self):
        s = FakeSession(routes=[("/api/animes/42", FakeResponse(json_data=[1]))])
        with pytest.raises(api.ShikimoriError):
            _client(s).get_anime(42)

    def test_genres_graphql(self):
        s = FakeSession(routes=[
            ("graphql", FakeResponse(json_data={"data": {"genres": [
                {"id": "5", "name": "Mecha", "russian": "Меха", "kind": "theme"},
                {"id": "мусор", "name": "x"},
            ]}}))])
        out = _client(s).genres("anime")
        assert out == [{"id": 5, "name": "Mecha", "russian": "Меха", "kind": "theme"}]

    def test_genres_fallback_rest(self):
        s = FakeSession(routes=[
            ("graphql", FakeResponse(status_code=400)),
            ("/api/genres", FakeResponse(json_data=[
                {"id": 1, "name": "Action", "entry_type": "anime"},
                {"id": 2, "name": "Josei", "entry_type": "manga"},
                {"id": 3, "name": "Old", "kind": None},
            ]))])
        out = _client(s).genres("anime")
        names = [g["name"] for g in out]
        assert "Action" in names and "Old" in names and "Josei" not in names

    def test_genres_rest_not_list(self):
        s = FakeSession(routes=[
            ("graphql", FakeResponse(status_code=400)),
            ("/api/genres", FakeResponse(json_data={"x": 1}))])
        assert _client(s).genres("anime") == []

    def test_close_swallows(self):
        class S(FakeSession):
            def close(self):
                raise RuntimeError("boom")
        _client(S()).close()  # не должно бросить

    def test_requires_requests(self, monkeypatch):
        monkeypatch.setattr(api, "_HAS_REQUESTS", False)
        with pytest.raises(api.ShikimoriError, match="requests"):
            api.ShikimoriApiClient()


# ── find_anime ───────────────────────────────────────────────────────────────
def _page(ids, per_page=None):
    return [dict(SAMPLE_JSON, id=i, score=8.0) for i in ids]


class TestFindAnime:
    def _client_pages(self, pages):
        """Клиент, отдающий подготовленные страницы по номеру page."""
        def handler(url, **kw):
            page = kw["params"]["page"]
            data = pages.get(page, [])
            return FakeResponse(json_data=data)
        s = FakeSession(routes=[("/api/animes", handler)])
        return _client(s), s

    def test_pagination_until_short_page(self):
        pages = {1: _page(range(1, 51)), 2: _page(range(51, 61))}
        c, s = self._client_pages(pages)
        out = api.find_anime(c, api.AnimeFilter(), per_page=50)
        assert len(out) == 60
        assert len([x for x in s.calls]) == 2  # третья страница не запрашивалась

    def test_dedup_across_pages(self):
        pages = {1: _page(range(1, 51)), 2: _page([50, 51])}
        c, _ = self._client_pages(pages)
        out = api.find_anime(c, api.AnimeFilter(), per_page=50)
        assert len(out) == 51
        assert len({a.id for a in out}) == 51

    def test_local_filter_applied(self):
        pages = {1: [dict(SAMPLE_JSON, id=1, score=9.0),
                     dict(SAMPLE_JSON, id=2, score=5.0)]}
        c, _ = self._client_pages(pages)
        out = api.find_anime(c, api.AnimeFilter(score_min=8.0))
        assert [a.id for a in out] == [1]

    def test_should_stop(self):
        pages = {i: _page(range(i * 100, i * 100 + 50)) for i in range(1, 10)}
        c, s = self._client_pages(pages)
        stops = iter([False, True])
        api.find_anime(c, api.AnimeFilter(), per_page=50,
                       should_stop=lambda: next(stops, True))
        assert len(s.calls) == 1

    def test_error_first_page_raises(self):
        s = FakeSession(routes=[("/api/animes", FakeResponse(status_code=403))])
        with pytest.raises(api.ShikimoriError):
            api.find_anime(_client(s), api.AnimeFilter())

    def test_error_later_page_returns_partial(self):
        state = {"n": 0}

        def handler(url, **kw):
            state["n"] += 1
            if state["n"] == 1:
                return FakeResponse(json_data=_page(range(1, 51)))
            return FakeResponse(status_code=429)
        s = FakeSession(routes=[("/api/animes", handler)])
        # max_retries=0 — чтобы 429 сразу превратился в ошибку страницы
        c = api.ShikimoriApiClient(session=s, max_retries=0)
        out = api.find_anime(c, api.AnimeFilter(), per_page=50)
        assert len(out) == 50

    def test_progress_and_on_batch(self):
        pages = {1: _page([1, 2])}
        c, _ = self._client_pages(pages)
        prog, batches = [], []
        api.find_anime(c, api.AnimeFilter(), per_page=50,
                       progress=lambda p, n: prog.append((p, n)),
                       on_batch=lambda b: batches.append(len(b)))
        assert prog == [(1, 2)]
        assert batches == [2]  # один батч из двух новых тайтлов

    def test_callback_errors_swallowed(self):
        pages = {1: _page([1])}
        c, _ = self._client_pages(pages)

        def bad_cb(*a):
            raise RuntimeError("плохой колбэк")
        out = api.find_anime(c, api.AnimeFilter(), progress=bad_cb, on_batch=bad_cb)
        assert len(out) == 1

    def test_max_pages_cap(self):
        pages = {i: _page(range(i * 1000, i * 1000 + 50)) for i in range(1, 20)}
        c, s = self._client_pages(pages)
        api.find_anime(c, api.AnimeFilter(), per_page=50, max_pages=3)
        assert len(s.calls) == 3

    def test_quick_find_closes_own_client(self, monkeypatch):
        closed = []

        class C(api.ShikimoriApiClient):
            def close(self):
                closed.append(1)
        s = FakeSession(routes=[("/api/animes", FakeResponse(json_data=[]))])
        monkeypatch.setattr(api, "ShikimoriApiClient",
                            lambda *a, **k: C(session=s))
        out = api.quick_find("наруто", max_score=6)
        assert out == []
        assert closed == [1]

    def test_quick_find_external_client_not_closed(self):
        closed = []

        class C(api.ShikimoriApiClient):
            def close(self):
                closed.append(1)
        s = FakeSession(routes=[("/api/animes", FakeResponse(json_data=[]))])
        c = C(session=s)
        api.quick_find("x", client=c)
        assert closed == []
