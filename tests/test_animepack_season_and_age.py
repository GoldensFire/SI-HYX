# -*- coding: utf-8 -*-
"""Сезон серии, порядок частей серии и возраст выходящего тайтла.

Три жалобы одного разбора (просьба пользователя):
  • «Episode 73» у «Моей геройской академии» — это десятая серия ЧЕТВЁРТОГО
    сезона, а вопрос приписывался первому и объявлял серию 73;
  • «Царство» раз за разом доставалось паку шестым сезоном — потому что
    остальных сезонов в каталоге не было; сам выбор части остаётся жребием;
  • «Ван-Пис» идёт с 1999 года и не кончился — штраф за старость ему не по
    возрасту.
"""
import random

import pytest
import shikimori_api as shiki
import animepack as ap
from animepack import PackSettings
from si_hyx_parts.animepack import plot_season

from test_animepack_new_kinds import make_anime

INFOBOX = """{{Episode Infobox
|season number=4
|ep number=73
|ep title =Temp Squad
}}
==Summary==
Что-то произошло."""


def _season(number, mal, episodes, year, russian, name):
    return make_anime(malId=mal, id=mal, russian=russian, name=name,
                      kind="tv", episodes=episodes, franchise="hero",
                      airedOn={"year": year})


HERO = [
    _season(1, 31964, 13, 2016, "Моя геройская академия",
            "Boku no Hero Academia"),
    _season(2, 33486, 25, 2017, "Моя геройская академия 2",
            "Boku no Hero Academia 2nd Season"),
    _season(3, 36456, 25, 2018, "Моя геройская академия 3",
            "Boku no Hero Academia 3rd Season"),
    _season(4, 38408, 25, 2019, "Моя геройская академия 4",
            "Boku no Hero Academia 4th Season"),
]


class _Shikimori:
    """Отдаёт части франшизы и полные карточки — без всякой сети."""

    def __init__(self, parts):
        self.parts = list(parts)
        self.asked = []

    def franchise_parts(self, keys):
        return {str(key): list(self.parts) for key in keys}

    def animes_by_ids(self, ids):
        self.asked.append(list(ids))
        by_id = {int(card["malId"]): card for card in self.parts}
        return [by_id[int(i)] for i in ids if int(i) in by_id]


class _Gen:
    def __init__(self, parts, tmp_path):
        self.shikimori = _Shikimori(parts)
        self.db_cache = ap.ShikimoriDbCache(str(tmp_path / "db.json"))
        self.lines = []

    def log(self, message):
        self.lines.append(str(message))


# ── сезон серии ──────────────────────────────────────────────────────────────
def test_the_infobox_tells_the_season_and_the_number():
    assert plot_season.season_of_page(INFOBOX) == 4
    assert plot_season.episode_of_page(INFOBOX) == "73"
    assert plot_season.season_of_page("==Summary==\nбез инфобокса") == 0


def test_a_running_number_becomes_the_number_inside_the_season():
    assert plot_season.episode_in_season("73", 63) == "10"
    # Вики уже считает посезонно — пересчитывать нечего.
    assert plot_season.episode_in_season("10", 63) == ""
    assert plot_season.episode_in_season("73", 0) == ""


def test_the_card_of_the_right_season_replaces_the_first_one(tmp_path):
    gen = _Gen(HERO, tmp_path)
    cand = ap.SongCandidate(song={}, anime=HERO[0], kind=ap.PLOT_KIND)
    episode = plot_season.apply_season(gen, cand, INFOBOX, "Episode 73")
    assert episode == "10"
    assert cand.anime["malId"] == 38408
    assert cand.title_ru == "Моя геройская академия 4"
    assert any("4-й сезон" in line for line in gen.lines)


def test_an_unconfirmed_order_changes_nothing(tmp_path):
    """Названия частей не подтверждают порядок — не трогаем ничего."""
    muddle = [dict(card) for card in HERO]
    muddle[2]["russian"] = muddle[2]["name"] = "Моя геройская академия: Финал"
    gen = _Gen(muddle, tmp_path)
    cand = ap.SongCandidate(song={}, anime=muddle[0], kind=ap.PLOT_KIND)
    assert plot_season.apply_season(gen, cand, INFOBOX, "Episode 73") == "73"
    assert cand.anime["malId"] == 31964


def test_a_missing_season_changes_nothing(tmp_path):
    """Частей франшизы меньше, чем сезонов, — сезон не подставляем."""
    gen = _Gen(HERO[:2], tmp_path)
    cand = ap.SongCandidate(song={}, anime=HERO[0], kind=ap.PLOT_KIND)
    assert plot_season.apply_season(gen, cand, INFOBOX, "Episode 73") == "73"
    assert cand.anime["malId"] == 31964


def test_movies_are_not_seasons():
    parts = list(HERO) + [make_anime(malId=999, id=999, kind="movie",
                                     russian="Моя геройская академия: Фильм",
                                     airedOn={"year": 2018})]
    tv = plot_season.ordered_tv_parts(parts)
    assert [card["malId"] for card in tv] == [31964, 33486, 36456, 38408]


# ── какая часть серии достанется паку ────────────────────────────────────────
def test_parts_of_one_franchise_come_in_random_order(tmp_path):
    """Сезон выбирается жребием — иначе одна и та же часть попадалась бы из
    пака в пак (просьба пользователя).

    «Царство» приходило шестым сезоном не из-за выбора: остальных сезонов не
    было в каталоге, потому что автодобор во время генерации ходит
    `order: random` и целиком его не вычерпывает."""
    def part(mal, completed):
        return make_anime(malId=mal, id=mal, kind="tv", franchise="kingdom",
                          russian=f"Царство {mal}", airedOn={"year": 2020},
                          statusesStats=[{"status": "completed",
                                          "count": completed}])

    # Числа зрителей нарочно очень разные: известность на порядок жребия влиять
    # не должна.
    cards = [part(1, 90000), part(2, 60000), part(3, 40000),
             part(4, 30000), part(5, 20000), part(6, 10000)]
    settings = PackSettings(questions=1, rounds=1, themes=1)
    firsts = set()
    for seed in range(15):
        gen = ap.AnimePackGenerator(
            settings, frames_history_path=str(tmp_path / "f.json"))
        gen.db_cache = ap.ShikimoriDbCache(str(tmp_path / "db.json"))
        gen.db_cache.add_cards("anime", ap.shiki_cache_signature(settings),
                               cards)
        gen.log = lambda *_a, **_k: None
        gen.rng = random.Random(seed)
        # Сети в тестах нет: каталога из шести карточек нам и хватит.
        gen._fetch_random_cards = lambda *_a, **_k: None
        ids = gen._random_shikimori_ids()
        assert sorted(ids) == [1, 2, 3, 4, 5, 6]
        firsts.add(ids[0])
    # Первым бывает не один и тот же сезон, и самый известный не закреплён.
    assert len(firsts) >= 4


# ── возраст выходящего тайтла ────────────────────────────────────────────────
def test_a_running_title_ages_half_as_fast():
    started = 2000
    old = shiki.effective_age(started, until=started)
    still = shiki.effective_age(started, ongoing=True)
    assert still == old / 2
    # Про окончание ничего не известно (старая база) — считаем как раньше.
    assert shiki.effective_age(started) == old


def test_a_running_title_keeps_more_of_its_index():
    stats = [{"status": "completed", "count": 100000}]
    card = make_anime(malId=1, id=1, airedOn={"year": 2000},
                      releasedOn={"year": 2000}, status="released",
                      statusesStats=stats)
    running = make_anime(malId=2, id=2, airedOn={"year": 2000},
                         status="ongoing", statusesStats=stats)
    ended = ap.SongCandidate(song={}, anime=card)
    goes = ap.SongCandidate(song={}, anime=running)
    assert goes.own_index > ended.own_index


def test_year_penalty_uses_the_gentler_half_lives():
    year = shiki.datetime.date.today().year
    anime, _score = shiki.index_factors(year - 6, 7.0)
    manga, _score = shiki.index_factors(year - 14, 7.0, manga=True)
    assert anime == pytest.approx(0.5)
    assert manga == pytest.approx(0.5)
