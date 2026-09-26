# -*- coding: utf-8 -*-
"""Часть франшизы для вопроса по сюжету — по дате выхода серии.

Живая жалоба (просьба пользователя): страница «Sword Art Online Alicization
Episode 45» попала в пак под названием «Мастера Меча Онлайн» с постером первого
сезона и репликой «Серия 45». На самом деле это 9-я серия «Войны в Подмирье 2».
Ни номер сезона из инфобокса («3» стоит у всей «Алисизации» разом), ни сверка
названий по порядку такую франшизу разобрать не могут: у «Алисизации» номера в
названии нет вовсе, а между вторым сезоном и ею вышел спин-офф «Призрачная
пуля». Разбирает её дата показа.
"""
import animepack as ap
from si_hyx_parts.animepack import plot_air_date, plot_season

from test_animepack_new_kinds import make_anime

# Инфобокс с живой страницы вики, урезанный до нужных полей.
SAO_45 = """{{Episode Infobox
|Name = Beyond Time
|Air Date = September 5, 2020
|English Air Date =
|Arc = Alicization
|Season = 3
|Episode = 45}}
==Plot==
Нападающие оставляют бомбу в главном двигателе «Океанской черепахи»."""


def _tv(mal, russian, name, episodes, aired, released):
    return make_anime(malId=mal, id=mal, russian=russian, name=name, kind="tv",
                      episodes=episodes, franchise="sword_art_online",
                      airedOn=dict(zip(("year", "month", "day"), aired)),
                      releasedOn=dict(zip(("year", "month", "day"), released)))


# Порядок нарочно «как в базе»: по году спин-офф и «Алисизация» неразличимы.
SAO = [
    _tv(11757, "Мастера Меча Онлайн", "Sword Art Online",
        25, (2012, 7, 8), (2012, 12, 23)),
    _tv(21881, "Мастера Меча Онлайн II", "Sword Art Online II",
        24, (2014, 7, 5), (2014, 12, 20)),
    _tv(36474, "Мастера Меча Онлайн: Алисизация", "Sword Art Online: Alicization",
        24, (2018, 10, 7), (2019, 3, 31)),
    _tv(36475, "Мастера Меча Онлайн: Альтернативная «Призрачная пуля»",
        "Sword Art Online Alternative: Gun Gale Online",
        12, (2018, 4, 8), (2018, 6, 30)),
    _tv(39597, "Мастера Меча Онлайн: Алисизация — Война в Подмирье",
        "Sword Art Online: Alicization - War of Underworld",
        12, (2019, 10, 12), (2019, 12, 28)),
    _tv(40540, "Мастера Меча Онлайн: Алисизация — Война в Подмирье 2",
        "Sword Art Online: Alicization - War of Underworld 2nd Season",
        11, (2020, 7, 12), (2020, 9, 20)),
]

TOKYO_41 = """{{Episode Infobox
| season = 3
| number = 4
| overall = 41
| jp. air date = October 24, 2023
}}"""

TOKYO = [
    _tv(42249, "Токийские мстители", "Tokyo Revengers", 24,
        (2021, 4, 11), (2021, 9, 19)),
    _tv(50608, "Токийские мстители: Рождественская битва",
        "Tokyo Revengers: Seiya Kessen-hen", 13,
        (2023, 1, 8), (2023, 4, 2)),
    _tv(54918, "Токийские мстители: Поднебесье",
        "Tokyo Revengers: Tenjiku-hen", 13,
        (2023, 10, 4), (2023, 12, 27)),
]
for _card in TOKYO:
    _card["franchise"] = "tokyo_revengers"


class _Shikimori:
    def __init__(self, parts):
        self.parts = list(parts)

    def franchise_parts(self, keys):
        return {str(key): list(self.parts) for key in keys}

    def animes_by_ids(self, ids):
        by_id = {int(card["malId"]): card for card in self.parts}
        return [by_id[int(i)] for i in ids if int(i) in by_id]


def test_jp_dot_air_date_moves_episode_41_to_tokyo_revengers_season_3(tmp_path):
    assert plot_air_date.air_date_of_page(TOKYO_41) == (2023, 10, 24)
    gen = _Gen(TOKYO, tmp_path)
    cand = ap.SongCandidate({}, TOKYO[0], kind=ap.PLOT_KIND)
    episode = plot_season.apply_season(gen, cand, TOKYO_41, "Episode 41")
    assert episode == "4"
    assert cand.anime["malId"] == 54918
    assert cand.title_ru == "Токийские мстители: Поднебесье"


class _Gen:
    def __init__(self, parts, tmp_path):
        self.shikimori = _Shikimori(parts)
        self.db_cache = ap.ShikimoriDbCache(str(tmp_path / "db.json"))
        self.lines = []

    def log(self, message):
        self.lines.append(str(message))


def test_the_air_date_is_read_from_the_infobox():
    assert plot_air_date.air_date_of_page(SAO_45) == (2020, 9, 5)
    # Английская дата не в счёт: она пустая или отстаёт на годы.
    assert plot_air_date.air_date_of_page("|English Air Date = May 1, 2021") == ()
    assert plot_air_date.air_date_of_page("==Plot==\nбез инфобокса") == ()


def test_dates_are_read_in_every_common_spelling():
    assert plot_air_date.parse_date("September 5, 2020") == (2020, 9, 5)
    assert plot_air_date.parse_date("5 September 2020") == (2020, 9, 5)
    assert plot_air_date.parse_date("2020-09-05") == (2020, 9, 5)
    assert plot_air_date.parse_date("[[September 5]], 2020") == (2020, 9, 5)
    assert plot_air_date.parse_date("скоро") == ()


def test_the_part_that_was_airing_that_day_wins():
    parts = sorted(SAO, key=lambda c: plot_air_date.card_date(c))
    assert plot_air_date.part_for_date(parts, (2020, 9, 5)) == 5
    assert plot_air_date.part_for_date(parts, (2018, 5, 1)) == 2
    # Между частями не шло ничего — и приписывать серию предыдущей нельзя.
    assert plot_air_date.part_for_date(parts, (2016, 1, 1)) == -1
    # Раньше самой первой части — тоже мимо.
    assert plot_air_date.part_for_date(parts, (2005, 1, 1)) == -1


def test_a_running_number_is_split_by_the_longest_run():
    parts = sorted(SAO, key=lambda c: plot_air_date.card_date(c))
    # Вики считает «Алисизацию» заново: 45 = 24 + 12 + 9.
    assert plot_air_date.episode_in_part(parts, 5, "45") == "9"
    # Номер уже посезонный — пересчитывать нечего.
    assert plot_air_date.episode_in_part(parts, 5, "3") == "3"
    # Столько серий не выходило ни в одном разбеге.
    assert plot_air_date.episode_in_part(parts, 5, "900") == ""


def test_episode_number_written_as_a_word_is_read_from_infobox():
    raw = """{{Infobox episode
|name = The Strongest Player
|number = Nine
|season = One}}"""
    assert plot_season.episode_of_page(raw) == "9"


def test_the_card_of_the_airing_part_replaces_the_first_season(tmp_path):
    gen = _Gen(SAO, tmp_path)
    cand = ap.SongCandidate(song={}, anime=SAO[0], kind=ap.PLOT_KIND)
    episode = plot_season.apply_season(
        gen, cand, SAO_45, "Sword Art Online Alicization Episode 45")
    assert episode == "9"
    assert cand.anime["malId"] == 40540
    assert "Война в Подмирье 2" in cand.title_ru
    assert any("05.09.2020" in line for line in gen.lines)


def test_the_first_season_of_its_own_episode_is_left_alone(tmp_path):
    """Серия своей же карточки франшизу не поднимает и номер не трогает."""
    gen = _Gen(SAO, tmp_path)
    cand = ap.SongCandidate(song={}, anime=SAO[0], kind=ap.PLOT_KIND)
    page = "Sword Art Online Episode 7"
    assert plot_season.apply_season(gen, cand, "==Plot==\nтекст", page) == "7"
    assert cand.anime["malId"] == 11757
    assert gen.lines == []


# Живая жалоба (просьба пользователя): «Обещанный Неверленд», страница
# «Episode 19». Это седьмая серия ВТОРОГО сезона, а в пак вопрос попал с
# постером первого и с репликой «Серия 19». Номера сезона в инфобоксе нет
# вовсе — он назван только прозой, — а дата показа есть, просто поле зовётся
# `japanese_air_date`, через подчёркивание.
TPN_19 = """{{Episodes Infobox
|japanese_air_date = February 26, 2021
|english_air_date = May 23, 2021
|previous = [[Episode 18]]}}
'''Episode 19''' is the seventh episode of season 2."""

TPN = [
    _tv(37779, "Обещанный Неверленд", "Yakusoku no Neverland",
        12, (2019, 1, 11), (2019, 3, 29)),
    _tv(40776, "Обещанный Неверленд 2", "Yakusoku no Neverland 2nd Season",
        11, (2021, 1, 8), (2021, 3, 26)),
]
for _card in TPN:
    _card["franchise"] = "yakusoku_no_neverland"


def test_the_air_date_is_read_through_an_underscore():
    assert plot_air_date.air_date_of_page(TPN_19) == (2021, 2, 26)
    assert plot_air_date.air_date_of_page(
        "|english_air_date = May 23, 2021") == ()


def test_the_second_season_of_the_promised_neverland_is_found(tmp_path):
    gen = _Gen(TPN, tmp_path)
    cand = ap.SongCandidate(song={}, anime=TPN[0], kind=ap.PLOT_KIND)
    assert plot_season.apply_season(gen, cand, TPN_19, "Episode 19") == "7"
    assert cand.anime["malId"] == 40776
    assert "Неверленд 2" in cand.title_ru


POKEMON_144 = """{{Episode Infobox
| season = 25
| episode = 8
| japanese_air_date = March 3, 2023
}}"""

POKEMON = [
    _tv(527, "Покемон", "Pokemon", 276,
        (1997, 4, 1), (2002, 11, 14)),
    _tv(40351, "Покемон (2019)", "Pokemon (2019)", 136,
        (2019, 11, 17), (2022, 12, 16)),
    _tv(53874, "Покемон: Стремление стать мастером покемонов",
        "Pokemon: Mezase Pokemon Master", 11,
        (2023, 1, 13), (2023, 3, 24)),
]
for _card in POKEMON:
    _card["franchise"] = "pokemon"


def test_pokemon_page_code_and_season_25_select_the_right_series(tmp_path):
    assert ap.episode_number("P144: Getting to the Heart of It All!") == "144"
    assert plot_season.season_of_page(POKEMON_144) == 25
    gen = _Gen(POKEMON, tmp_path)
    gen.db_cache.add_cards("anime", "pokemon", POKEMON)
    cand = ap.SongCandidate(song={}, anime=POKEMON[0], kind=ap.PLOT_KIND)
    episode = plot_season.apply_season(
        gen, cand, POKEMON_144, "P144: Getting to the Heart of It All!")
    assert episode == "8"
    assert cand.anime["malId"] == 53874
    assert "Стремление стать мастером" in cand.title_ru
