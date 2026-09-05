# -*- coding: utf-8 -*-
"""Общая кладовая обложек (poster_cache) и запасной источник TMDB.

Проверяется то, ради чего всё затевалось: постер, скачанный ОДНОЙ вкладкой,
берётся из кладовой ДРУГОЙ и заново не качается; без ссылки на Shikimori
обложка ищется на themoviedb.org; папка не растёт без предела.

Сети тут нет: TMDB отвечает заглушкой (см. FakeSession в conftest).
"""
import os

import pytest

import animepack
import poster_cache
from animepack import PLOT_KIND, PackSettings, SongCandidate
from animepack_api import TMDB_IMG, AnimePackApiError, TmdbApi

from test_animepack_new_kinds import make_anime


# ── Сама кладовая ────────────────────────────────────────────────────────────
def test_put_and_find_round_trip():
    key = poster_cache.anime_key(1535)
    assert key == "anime_1535"
    assert poster_cache.find(key) == (b"", "")
    poster_cache.put(key, b"jpegbytes", ".jpg")
    assert poster_cache.find(key) == (b"jpegbytes", ".jpg")


def test_anime_and_manga_do_not_share_a_poster():
    """Номера у аниме и манги свои и сплошь и рядом совпадают."""
    poster_cache.put(poster_cache.anime_key(20), b"anime", ".jpg")
    poster_cache.put(poster_cache.anime_key(20, book=True), b"manga", ".png")
    assert poster_cache.find(poster_cache.anime_key(20))[0] == b"anime"
    assert poster_cache.find(poster_cache.anime_key(20, book=True))[0] == b"manga"


def test_no_key_no_cache():
    assert poster_cache.anime_key(0) == "" and poster_cache.anime_key(None) == ""
    assert poster_cache.put("", b"x") == "" and poster_cache.find("") == (b"", "")


def test_prune_drops_the_oldest_first():
    for num in range(1, 6):
        poster_cache.put(poster_cache.anime_key(num), b"x" * 300_000, ".jpg")
    # Обращаемся к первой — она должна пережить чистку.
    poster_cache.find(poster_cache.anime_key(1))
    assert poster_cache.prune(limit_mb=1) > 0
    assert poster_cache.size_bytes() <= 1024 * 1024
    assert poster_cache.find(poster_cache.anime_key(1))[0]


def test_clear_empties_the_shelf():
    poster_cache.put(poster_cache.anime_key(7), b"x", ".jpg")
    assert poster_cache.clear() == 1
    assert poster_cache.stats() == (0, 0)


# ── TMDB ─────────────────────────────────────────────────────────────────────
def _tmdb_session(fake_session, fake_response, results):
    return fake_session([("api.themoviedb.org",
                          fake_response(json_data={"results": results}))])


def test_tmdb_prefers_the_exact_title(fake_session, fake_response):
    """По запросу «Bleach» TMDB первой строкой отдаёт документалку про моющее
    средство — берём ту строку, где название совпало."""
    rows = [{"name": "Bleach: the whitening", "poster_path": "/junk.jpg",
             "popularity": 99.0},
            {"name": "Bleach", "poster_path": "/right.jpg", "popularity": 5.0}]
    api = TmdbApi(_tmdb_session(fake_session, fake_response, rows), key="k")
    assert api.poster_url(["Bleach"]) == f"{TMDB_IMG}/right.jpg"


def test_tmdb_skips_results_without_a_poster(fake_session, fake_response):
    rows = [{"name": "Bleach", "popularity": 99.0}]
    api = TmdbApi(_tmdb_session(fake_session, fake_response, rows), key="k")
    assert api.poster_url(["Bleach"]) == ""


def test_tmdb_without_a_key_never_goes_to_the_net(fake_session, fake_response):
    session = _tmdb_session(fake_session, fake_response, [])
    api = TmdbApi(session, key="")
    assert api.enabled is False and api.poster_url(["Bleach"]) == ""
    assert session.calls == []


def test_tmdb_says_plainly_that_the_key_was_refused(fake_session, fake_response):
    session = fake_session([("api.themoviedb.org",
                             fake_response(status_code=401, text="bad key"))])
    with pytest.raises(AnimePackApiError) as e:
        TmdbApi(session, key="k").poster_url(["Bleach"])
    assert "ключ" in str(e.value)


def test_v4_token_goes_into_the_header(fake_session, fake_response):
    session = _tmdb_session(fake_session, fake_response, [])
    TmdbApi(session, key="ey.J.token").poster_url(["Bleach"])
    _method, _url, kw = session.calls[0]
    assert kw["headers"]["Authorization"] == "Bearer ey.J.token"
    assert "api_key" not in kw["params"]


# ── Генератор: кладовая → Shikimori → TMDB ───────────────────────────────────
def _generator(**over):
    s = PackSettings(**over)
    return animepack.AnimePackGenerator(s, session=object(), amq=object(),
                                        anisong=object(), mal=object(),
                                        shikimori=object(), tmdb=object())


def test_generator_takes_the_poster_from_the_shelf(monkeypatch):
    gen = _generator()
    cand = SongCandidate(song={}, anime=make_anime(), kind=PLOT_KIND)
    poster_cache.put(poster_cache.anime_key(cand.mal_id), b"cached", ".png")

    def boom(url, timeout=None):
        raise AssertionError("постер лежит в кладовой — качать его незачем")

    monkeypatch.setattr(gen, "_get_bytes", boom)
    assert gen._poster_bytes(cand, "https://shiki/poster.jpg") == (b"cached",
                                                                  ".png")
    assert gen._poster_hits == 1


def test_generator_puts_what_it_downloaded_on_the_shelf(monkeypatch):
    gen = _generator()
    cand = SongCandidate(song={}, anime=make_anime(), kind=PLOT_KIND)
    monkeypatch.setattr(gen, "_get_bytes", lambda url, timeout=None: b"fresh")
    assert gen._poster_bytes(cand, "https://shiki/poster.jpg") == (b"fresh",
                                                                  ".jpg")
    assert poster_cache.find(poster_cache.anime_key(cand.mal_id)) == (b"fresh",
                                                                     ".jpg")


def test_generator_falls_back_to_tmdb_without_a_shikimori_poster(monkeypatch):
    gen = _generator(tmdb_key="k")
    anime = make_anime(poster={})
    cand = SongCandidate(song={}, anime=anime, kind=PLOT_KIND)

    class FakeTmdb:
        enabled = True

        def poster_url(self, names, year=0, movie=False):
            assert "Death Note" in names and year == 2006
            return f"{TMDB_IMG}/dn.jpg"

    gen.tmdb = FakeTmdb()
    monkeypatch.setattr(gen, "_get_bytes", lambda url, timeout=None: b"tmdb")
    assert gen._poster_bytes(cand, "") == (b"tmdb", ".jpg")
    assert gen._poster_tmdb == 1
    # И на полку легло — второй раз к TMDB не пойдём ни здесь, ни в апгрейде.
    assert poster_cache.find(poster_cache.anime_key(cand.mal_id))[0] == b"tmdb"


def test_cache_can_be_switched_off(monkeypatch):
    gen = _generator(poster_cache=False)
    cand = SongCandidate(song={}, anime=make_anime(), kind=PLOT_KIND)
    monkeypatch.setattr(gen, "_get_bytes", lambda url, timeout=None: b"fresh")
    gen._poster_bytes(cand, "https://shiki/poster.jpg")
    assert poster_cache.find(poster_cache.anime_key(cand.mal_id)) == (b"", "")


def test_the_shelf_is_shared_with_the_upgrade_tab(monkeypatch):
    """Ключ у обеих вкладок один и тот же — в этом весь смысл общей папки."""
    import animepack_upgrade as up

    gen = _generator()
    cand = SongCandidate(song={}, anime=make_anime(), kind=PLOT_KIND)
    monkeypatch.setattr(gen, "_get_bytes", lambda url, timeout=None: b"shared")
    gen._poster_bytes(cand, "https://shiki/poster.jpg")

    job = up._PosterJob(ref="p.avif", url="https://shiki/poster.jpg",
                        title="Тетрадь смерти",
                        key=poster_cache.anime_key(cand.mal_id))
    upgrader = up.PackUpgrader.__new__(up.PackUpgrader)
    upgrader._tmdb = False
    assert upgrader._poster_bytes(job) == (b"shared", ".jpg")
