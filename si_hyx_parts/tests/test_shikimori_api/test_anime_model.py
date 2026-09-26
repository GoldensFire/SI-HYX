# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""TestAnimeModel. Public namespace: test_shikimori_api."""
import test_shikimori_api as _api


class TestAnimeModel:
    def test_from_json(self):
        a = _api.api.Anime.from_json(_api.SAMPLE_JSON)
        assert a.id == 42
        assert a.score == _api.pytest.approx(8.12)
        assert a.episodes == 220
        assert a.image_url == _api.api.DEFAULT_BASE_URL + "/system/animes/preview/42.jpg"
        assert a.url == _api.api.DEFAULT_BASE_URL + "/animes/42-naruto"

    def test_title_prefers_russian(self):
        a = _api.api.Anime.from_json(_api.SAMPLE_JSON)
        assert a.title == "Наруто"

    def test_title_fallback_name(self):
        d = dict(_api.SAMPLE_JSON, russian="")
        assert _api.api.Anime.from_json(d).title == "Naruto"

    def test_year(self):
        assert _api.api.Anime.from_json(_api.SAMPLE_JSON).year == 2002

    def test_year_from_released(self):
        d = dict(_api.SAMPLE_JSON, aired_on=None, released_on="2010-01-01")
        assert _api.api.Anime.from_json(d).year == 2010

    def test_year_none(self):
        d = dict(_api.SAMPLE_JSON, aired_on=None, released_on=None)
        assert _api.api.Anime.from_json(d).year is None

    def test_year_garbage(self):
        d = dict(_api.SAMPLE_JSON, aired_on="абвг-10-03", released_on=None)
        assert _api.api.Anime.from_json(d).year is None

    def test_air_date_full(self):
        a = _api.api.Anime.from_json(_api.SAMPLE_JSON)
        assert a.air_date == _api.datetime.date(2002, 10, 3)

    def test_air_date_year_only(self):
        d = dict(_api.SAMPLE_JSON, aired_on="2002")
        assert _api.api.Anime.from_json(d).air_date == _api.datetime.date(2002, 1, 1)

    def test_air_date_feb_clamped(self):
        d = dict(_api.SAMPLE_JSON, aired_on="2020-02-31")
        assert _api.api.Anime.from_json(d).air_date == _api.datetime.date(2020, 2, 28)

    def test_air_date_none(self):
        d = dict(_api.SAMPLE_JSON, aired_on=None, released_on=None)
        assert _api.api.Anime.from_json(d).air_date is None

    def test_date_label_full(self):
        assert _api.api.Anime.from_json(_api.SAMPLE_JSON).date_label == "3 октября 2002"

    def test_date_label_season(self):
        d = dict(_api.SAMPLE_JSON, aired_on="2019-04")
        assert _api.api.Anime.from_json(d).date_label == "Весна 2019"

    def test_date_label_year(self):
        d = dict(_api.SAMPLE_JSON, aired_on="2019")
        assert _api.api.Anime.from_json(d).date_label == "2019"

    def test_date_label_empty(self):
        d = dict(_api.SAMPLE_JSON, aired_on=None, released_on=None)
        assert _api.api.Anime.from_json(d).date_label == ""

    def test_chapters_mapped_to_episodes(self):
        d = dict(_api.SAMPLE_JSON, episodes=None, chapters="120")
        assert _api.api.Anime.from_json(d).episodes == 120

    def test_bad_numbers_default(self):
        d = dict(_api.SAMPLE_JSON, id="мусор", score=None, episodes="x")
        a = _api.api.Anime.from_json(d)
        assert a.id == 0 and a.score == 0.0 and a.episodes == 0

    def test_absolute_image_url_kept(self):
        d = dict(_api.SAMPLE_JSON, image={"preview": "https://cdn.x/im.jpg"})
        assert _api.api.Anime.from_json(d).image_url == "https://cdn.x/im.jpg"

    def test_as_row(self):
        row = _api.api.Anime.from_json(_api.SAMPLE_JSON).as_row()
        assert row["id"] == 42
        assert row["title"] == "Наруто"
        assert row["year"] == 2002
        assert row["url"].endswith("/animes/42-naruto")

TestAnimeModel.__module__ = _api.__name__
_api.TestAnimeModel = TestAnimeModel

# ── AnimeFilter ──────────────────────────────────────────────────────────────
class TestAnimeFilter:
    def test_server_params_full(self):
        f = _api.api.AnimeFilter(query=" наруто ", kind="tv", status="released",
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
        f = _api.api.AnimeFilter(kind="фильм", status="вышло", order="хаос")
        p = f.to_server_params()
        assert "kind" not in p and "status" not in p and "order" not in p

    def test_manga_kinds_accepted(self):
        f = _api.api.AnimeFilter(kind="manhwa", content_type="manga")
        assert f.to_server_params()["kind"] == "manhwa"

    def test_season_both_years(self):
        f = _api.api.AnimeFilter(year_from=2010, year_to=2015)
        assert f.to_server_params()["season"] == "2010_2015"

    def test_season_swapped_years(self):
        f = _api.api.AnimeFilter(year_from=2015, year_to=2010)
        assert f._season_param() == "2010_2015"

    def test_season_open_upper(self):
        f = _api.api.AnimeFilter(year_from=2017)
        season = f._season_param()
        lo, hi = season.split("_")
        assert lo == "2017"
        assert int(hi) >= _api.datetime.date.today().year + 1

    def test_season_open_lower(self):
        f = _api.api.AnimeFilter(year_to=2017)
        assert f._season_param() == "1900_2017"

    def test_season_empty(self):
        assert _api.api.AnimeFilter()._season_param() == ""

    def _anime(self, **kw):
        base = dict(_api.SAMPLE_JSON)
        base.update(kw)
        return _api.api.Anime.from_json(base)

    def test_matches_local_score(self):
        f = _api.api.AnimeFilter(score_min=8.0, score_max=9.0)
        assert f.matches_local(self._anime(score=8.5))
        assert not f.matches_local(self._anime(score=7.9))
        assert not f.matches_local(self._anime(score=9.1))

    def test_matches_local_episodes(self):
        f = _api.api.AnimeFilter(episodes_min=10, episodes_max=30)
        assert f.matches_local(self._anime(episodes=20))
        assert not f.matches_local(self._anime(episodes=5))
        assert not f.matches_local(self._anime(episodes=100))
        # episodes==0 (неизвестно) не отфильтровывается по максимуму
        assert not f.matches_local(self._anime(episodes=0))  # но min=10 режет

    def test_matches_local_zero_episodes_max_only(self):
        f = _api.api.AnimeFilter(episodes_max=30)
        assert f.matches_local(self._anime(episodes=0))

    def test_matches_local_years(self):
        f = _api.api.AnimeFilter(year_from=2000, year_to=2005)
        assert f.matches_local(self._anime(aired_on="2002-01-01"))
        assert not f.matches_local(self._anime(aired_on="1999-01-01"))
        assert not f.matches_local(self._anime(aired_on="2006-01-01"))

    def test_matches_local_year_unknown_rejected(self):
        f = _api.api.AnimeFilter(year_from=2000)
        assert not f.matches_local(self._anime(aired_on=None, released_on=None))

    def test_validate_ok(self):
        assert _api.api.AnimeFilter(score_min=5, score_max=9).validate() is None

    def test_validate_score(self):
        assert "оценка" in _api.api.AnimeFilter(score_min=9, score_max=5).validate()

    def test_validate_episodes(self):
        assert "эпизодов" in _api.api.AnimeFilter(
            episodes_min=50, episodes_max=10).validate()

    def test_validate_years(self):
        assert "Год" in _api.api.AnimeFilter(year_from=2020, year_to=2010).validate()

TestAnimeFilter.__module__ = _api.__name__
_api.TestAnimeFilter = TestAnimeFilter

# ── клиент: _get с ретраями ──────────────────────────────────────────────────
def _client(session):
    return _api.api.ShikimoriApiClient(session=session, max_retries=2)

_client.__module__ = _api.__name__
_api._client = _client

class TestClientGet:
    def test_success(self):
        s = _api.FakeSession(routes=[("/api/animes", _api.FakeResponse(json_data=[]))])
        c = _api._client(s)
        assert c._get("/api/animes") == []

    def test_retry_on_429_then_success(self):
        responses = [_api.FakeResponse(status_code=429, headers={"Retry-After": "0"}),
                     _api.FakeResponse(json_data={"ok": 1})]

        def handler(url, **kw):
            return responses.pop(0)
        s = _api.FakeSession(routes=[("/api/x", handler)])
        assert _api._client(s)._get("/api/x") == {"ok": 1}

    def test_gives_up_after_retries(self):
        s = _api.FakeSession(routes=[("/api/x", _api.FakeResponse(status_code=503))])
        with _api.pytest.raises(_api.api.ShikimoriError):
            _api._client(s)._get("/api/x")
        # 1 попытка + 2 ретрая
        assert len(s.calls) == 3

    def test_4xx_no_retry(self):
        s = _api.FakeSession(routes=[("/api/x", _api.FakeResponse(status_code=403))])
        with _api.pytest.raises(_api.api.ShikimoriError, match="403"):
            _api._client(s)._get("/api/x")
        assert len(s.calls) == 1

    def test_bad_json(self):
        s = _api.FakeSession(routes=[("/api/x", _api.FakeResponse(text="html", raise_json=True))])
        with _api.pytest.raises(_api.api.ShikimoriError, match="JSON"):
            _api._client(s)._get("/api/x")

    def test_network_error(self):
        import requests as req

        class BoomSession(_api.FakeSession):
            def get(self, url, **kw):
                self.calls.append(("GET", url, kw))
                raise req.ConnectionError("нет сети")
        s = BoomSession()
        with _api.pytest.raises(_api.api.ShikimoriError, match="Сетевая"):
            _api._client(s)._get("/api/x")
        assert len(s.calls) == 3

    def test_timeout_error(self):
        import requests as req

        class SlowSession(_api.FakeSession):
            def get(self, url, **kw):
                self.calls.append(("GET", url, kw))
                raise req.Timeout("долго")
        with _api.pytest.raises(_api.api.ShikimoriError, match="Таймаут"):
            _api._client(SlowSession())._get("/api/x")

    def test_backoff_growth(self):
        assert _api.api.ShikimoriApiClient._backoff(0) == 0.5
        assert _api.api.ShikimoriApiClient._backoff(1) == 1.0
        assert _api.api.ShikimoriApiClient._backoff(10) == 8.0  # потолок

    def test_retry_delay_uses_header(self):
        c = _api._client(_api.FakeSession())
        resp = _api.FakeResponse(status_code=429, headers={"Retry-After": "3"})
        assert c._retry_delay(resp, 0) == 3.0

    def test_retry_delay_header_capped(self):
        c = _api._client(_api.FakeSession())
        resp = _api.FakeResponse(status_code=429, headers={"Retry-After": "9999"})
        assert c._retry_delay(resp, 0) == 15.0

    def test_retry_delay_bad_header(self):
        c = _api._client(_api.FakeSession())
        resp = _api.FakeResponse(status_code=429, headers={"Retry-After": "потом"})
        assert c._retry_delay(resp, 1) == _api.api.ShikimoriApiClient._backoff(1)

    def test_headers_set(self):
        s = _api.FakeSession()
        _api.api.ShikimoriApiClient(session=s, token="секрет", user_agent="UA-Test/1.0")
        assert s.headers["User-Agent"] == "UA-Test/1.0"
        assert s.headers["Authorization"] == "Bearer секрет"

    def test_base_url_trailing_slash(self):
        s = _api.FakeSession(routes=[("/api/z", _api.FakeResponse(json_data=1))])
        c = _api.api.ShikimoriApiClient(base_url="https://shikimori.io/", session=s)
        c._get("/api/z")
        assert s.calls[0][1] == "https://shikimori.io/api/z"

TestClientGet.__module__ = _api.__name__
_api.TestClientGet = TestClientGet
