# -*- coding: utf-8 -*-
"""Каталог из мешка с фильтрами шире нынешних и бонус «в избранном»."""
import random
from types import SimpleNamespace

import pytest

import animepack as ap
from animepack import PackSettings
from si_hyx_parts.animepack import catalog_superset
from test_animepack_new_kinds import make_anime


def _card(mal, genres=(), year=2015, kind="tv", score=7.5):
    return make_anime(malId=mal, id=mal, kind=kind, score=score,
                      airedOn={"year": year},
                      genres=[{"id": str(g), "name": f"g{g}"} for g in genres])


def _gen(tmp_path, settings):
    gen = ap.AnimePackGenerator(
        settings, frames_history_path=str(tmp_path / "f.json"))
    gen.db_cache = ap.ShikimoriDbCache(str(tmp_path / "db.json"))
    gen.log = lambda *_a, **_k: None
    gen.rng = random.Random(1)
    return gen


def test_excluded_genre_is_served_from_the_full_catalog(tmp_path):
    """Жалоба пользователя: полный каталог уже лежал в базе, а после
    исключения жанра генератор заводил новый мешок и черпал сервер заново."""
    wide = PackSettings(questions=1, rounds=1, themes=1)
    narrow = PackSettings(questions=1, rounds=1, themes=1,
                          genres_exclude=[130])
    cards = [_card(i, genres=(130,) if i % 4 == 0 else (1,))
             for i in range(1, 401)]
    gen = _gen(tmp_path, narrow)
    gen.db_cache.add_cards("anime", ap.shiki_cache_signature(wide), cards)
    fetched = []
    gen._fetch_random_cards = lambda *a, **k: fetched.append(a)
    ids = gen._random_shikimori_ids()
    assert sorted(ids) == [i for i in range(1, 401) if i % 4]
    assert fetched == []           # на сервер за каталогом не ходили


def test_complete_bucket_stops_fetching_even_when_small(tmp_path):
    settings = PackSettings(questions=6, rounds=1, themes=1)
    gen = _gen(tmp_path, settings)
    sig = ap.shiki_cache_signature(settings)
    gen.db_cache.add_cards("anime", sig, [_card(1), _card(2)])
    gen.db_cache.mark_complete("anime", sig)
    fetched = []
    gen._fetch_random_cards = lambda *a, **k: fetched.append(a)
    assert sorted(gen._random_shikimori_ids()) == [1, 2]
    assert fetched == []


def test_cached_manga_is_not_topped_up_during_generation(tmp_path):
    settings = PackSettings(questions=4, rounds=6, themes=6,
                            pct_songs=0, pack_manga=True, pct_manga=100,
                            manga_pct_manhwa=50)
    gen = _gen(tmp_path, settings)
    sig = ap.shiki_cache_signature(settings, manga=True)
    gen.db_cache.add_cards("manga", sig, [_card(1, kind="manga")])
    gen._fetch_random_cards = lambda *a: pytest.fail("cached catalog refetched")
    gen.shikimori = SimpleNamespace(
        random_mangas=lambda *a, **k: pytest.fail("edition catalog refetched"))
    assert gen._random_shikimori_ids(manga=True) == [1]


def test_first_manga_catalog_uses_its_question_quota(tmp_path):
    settings = PackSettings(questions=4, rounds=6, themes=6,
                            pct_songs=75, pack_manga=True, pct_manga=25)
    assert settings.total_questions == 144
    assert settings.question_quotas[ap.MANGA_KIND] == 36
    gen = _gen(tmp_path, settings)
    fetched = []
    gen._fetch_random_cards = lambda manga, want, *a: fetched.append((manga, want))
    assert gen._random_shikimori_ids(manga=True) == []
    assert fetched == [(True, 36 * gen.RANDOM_OVERSHOOT_MANGA)]


def test_no_manga_quota_does_not_load_its_catalog(tmp_path):
    gen = _gen(tmp_path, PackSettings(pack_manga=False))
    gen._fetch_random_cards = lambda *a: pytest.fail("unneeded manga catalog")
    assert gen._random_shikimori_ids(manga=True) == []
    assert not gen._manga_cache


def test_narrower_bucket_serves_cards_without_claiming_completeness(tmp_path):
    """Мешок с исключённым жанром не выдаётся за полный каталог."""
    narrow = PackSettings(genres_exclude=[130])
    wide = PackSettings()
    db = ap.ShikimoriDbCache(str(tmp_path / "db.json"))
    db.add_cards("anime", ap.shiki_cache_signature(narrow), [_card(1)])
    cards, complete = catalog_superset.cached_catalog(
        db, "anime", ap.shiki_cache_signature(wide))
    assert [c["malId"] for c in cards] == [1] and complete is False


def test_year_score_and_kind_are_filtered_locally():
    outer = catalog_superset.parse_signature("1944-2026|tv,movie|0|")
    inner = catalog_superset.parse_signature("2010-2020|tv|7|5")
    assert catalog_superset.covers(outer, inner)
    assert catalog_superset.card_fits(_card(1, year=2015), outer, inner)
    assert not catalog_superset.card_fits(_card(1, year=2005), outer, inner)
    assert not catalog_superset.card_fits(_card(1, kind="movie"), outer, inner)
    assert not catalog_superset.card_fits(_card(1, score=6.9), outer, inner)
    assert not catalog_superset.card_fits(_card(1, genres=(5,)), outer, inner)


def test_eviction_keeps_the_biggest_bucket(tmp_path, monkeypatch):
    monkeypatch.setattr(ap, "SHIKI_CACHE_BUCKETS", 2)
    db = ap.ShikimoriDbCache(str(tmp_path / "db.json"))
    db.add_cards("anime", "full", [_card(i) for i in range(1, 50)])
    for n, sig in enumerate(("a", "b", "c")):
        db.add_cards("anime", sig, [_card(100 + n)])
    assert "full" in db.buckets("anime")


# ── «в избранном» по соседям по индексу ──────────────────────────────────
@pytest.fixture
def norm():
    ap.clear_favorites_norms()
    yield
    ap.clear_favorites_norms()


def _install(pairs):
    from si_hyx_parts.animepack import favorites_norm
    with favorites_norm._LOCK:
        favorites_norm._NORMS["anime"] = ap.FavoritesNorm(pairs)


def test_bonus_comes_from_neighbours_not_a_fixed_share(norm):
    # Соседи с индексом около 100 000 держат по 100 избранных.
    _install([(90_000 + i * 300, 100) for i in range(100)])
    # Раньше надбавке нужна была доля 2,4 на тысячу базы (≈ 2 400 избранных
    # при базе в миллион) — теперь хватает перевеса над соседями.
    assert ap.index_favorites_factor(1_000_000, 500) == 1.0
    assert ap.title_favorites_factor(100_000, 1_000_000, 500) > 1.2
    # Как у соседей или чуть больше — надбавки нет.
    assert ap.title_favorites_factor(100_000, 1_000_000, 100) == 1.0
    assert ap.title_favorites_factor(100_000, 1_000_000, 190) == 1.0
    assert ap.title_favorites_factor(100_000, 1_000_000, 10 ** 6) == 1.5


def test_without_enough_neighbours_the_old_rule_applies(norm):
    assert (ap.title_favorites_factor(50_000, 74_480, 523)
            == ap.index_favorites_factor(74_480, 523))


# ── средняя сложность и загрузки «в полёте» ──────────────────────────────
def test_average_counts_candidates_still_downloading(tmp_path):
    """До двух десятков кандидатов качаются одновременно. Середина считалась
    без них — и паки при просимой четвёрке выходили в среднем 4.5."""
    from types import SimpleNamespace
    gen = _gen(tmp_path, PackSettings(level_avg=4))
    levels = [4, 4, 4]

    def cand(level):
        return SimpleNamespace(kind=ap.FRAME_KIND, level=level)

    hard = cand(6)
    # Без загрузок «в полёте» шестёрка — допустимый разброс вокруг четвёрки.
    assert gen._level_fits(hard, levels, ap.FRAME_KIND) is True
    assert gen._level_fits(cand(4), levels, ap.FRAME_KIND) is True
    flying = [cand(7), cand(7), cand(7)]
    assert gen._level_fits(hard, levels, ap.FRAME_KIND, flying) is False
    assert gen._level_fits(cand(2), levels, ap.FRAME_KIND, flying) is True


def test_removed_stretch_effect_falls_back_in_old_settings():
    from frame_reveal import EFFECT_LABELS
    assert "stretch" not in EFFECT_LABELS
    s = PackSettings.from_dict({"frame_effect": "stretch",
                                "frame_effects": ["stretch", "waves"]})
    assert s.frame_effect == "pixelize"
    assert "stretch" not in s.frame_effects and "waves" in s.frame_effects
