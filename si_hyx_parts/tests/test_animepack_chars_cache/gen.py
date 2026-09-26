# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_gen. Public namespace: test_animepack_chars_cache."""
import test_animepack_chars_cache as _api


def _gen(settings, shikimori=None, **kw):
    """Генератор без сети: источники подменены заглушками."""
    class FakeShiki:
        def animes_by_ids(self, ids):
            return []

        def mangas_by_ids(self, ids):
            return []

        def user_anime_ids(self, nick, statuses, **_kw):
            return []

        def franchise_parts(self, keys):
            return {}

    return _api.AnimePackGenerator(settings, session=object(), amq=object(),
                              anisong=object(), mal=object(),
                              shikimori=shikimori or FakeShiki(),
                              anilist=object(), kitsu=object(),
                              themes=object(), **kw)

_gen.__module__ = _api.__name__
_api._gen = _gen

def _part(base, year, score=7.0):
    return {"statusesStats": [{"status": "completed", "count": base}],
            "airedOn": {"year": year}, "score": score}

_part.__module__ = _api.__name__
_api._part = _part

# ── Узнаваемость франшизы по её частям ──────────────────────────────────────
def test_franchise_index_rises_with_live_seasons():
    """У сериала с несколькими популярными сезонами узнаваемость выше, чем у
    одиночного тайтла с тем же числом зрителей."""
    alone = _api.franchise_parts_index([_api._part(10_000, 2019)])
    series = _api.franchise_parts_index([_api._part(10_000, 2019), _api._part(9_000, 2019),
                                    _api._part(8_000, 2019), _api._part(7_000, 2019)])
    assert series > alone
    # Надбавка именно «чуть»: потолок — четверть.
    assert series <= alone * 1.26

test_franchise_index_rises_with_live_seasons.__module__ = _api.__name__
_api.test_franchise_index_rises_with_live_seasons = test_franchise_index_rises_with_live_seasons

def test_franchise_index_softens_the_age_penalty_for_sequels():
    """Первый сезон 2002-го с популярным продолжением 2019-го теряет за возраст
    меньше, чем такой же одиночка без продолжений (просьба пользователя)."""
    old_alone = _api.franchise_parts_index([_api._part(10_000, 2002)])
    with_sequel = _api.franchise_parts_index([_api._part(10_000, 2002), _api._part(9_000, 2019)])
    assert with_sequel > old_alone
    # Но и ровесником сиквела оригинал не становится: год не подменяется
    # целиком, а усредняется.
    fresh = _api.franchise_parts_index([_api._part(10_000, 2019)])
    assert with_sequel < fresh

test_franchise_index_softens_the_age_penalty_for_sequels.__module__ = _api.__name__
_api.test_franchise_index_softens_the_age_penalty_for_sequels = test_franchise_index_softens_the_age_penalty_for_sequels

def test_franchise_index_ignores_unpopular_parts():
    """Спешл, которого никто не смотрел, франшизу не омолаживает."""
    plain = _api.franchise_parts_index([_api._part(10_000, 2002)])
    with_ova = _api.franchise_parts_index([_api._part(10_000, 2002), _api._part(50, 2024)])
    assert with_ova == _api.pytest.approx(plain)

test_franchise_index_ignores_unpopular_parts.__module__ = _api.__name__
_api.test_franchise_index_ignores_unpopular_parts = test_franchise_index_ignores_unpopular_parts

def test_franchise_index_of_nothing_is_zero():
    assert _api.franchise_parts_index([]) == 0.0
    assert _api.franchise_parts_index([{"statusesStats": []}]) == 0.0
    assert _api.franchise_parts_index(None) == 0.0

test_franchise_index_of_nothing_is_zero.__module__ = _api.__name__
_api.test_franchise_index_of_nothing_is_zero = test_franchise_index_of_nothing_is_zero

def test_franchise_index_does_not_age_the_newest_top_part():
    """«Стальной алхимик: Братство» 2009-го популярнее частей 2003-го — старость
    предшественников ему не приписывается."""
    top_is_new = _api.franchise_parts_index([_api._part(10_000, 2009), _api._part(4_000, 2003)])
    alone = _api.franchise_parts_index([_api._part(10_000, 2009)])
    assert top_is_new >= alone

test_franchise_index_does_not_age_the_newest_top_part.__module__ = _api.__name__
_api.test_franchise_index_does_not_age_the_newest_top_part = test_franchise_index_does_not_age_the_newest_top_part

# ── «В избранном» как мера сложности персонажа ──────────────────────────────
@_api.pytest.mark.parametrize("favorites,level", [
    (10_740, 1), (5_000, 1), (3_000, 2), (2_000, 3), (900, 5),
    (89, 11), (4, 14), (1, 15), (0, 15), (None, 15), ("нет", 15),
])
def test_char_fav_level(favorites, level):
    assert _api.char_fav_level(favorites) == level

test_char_fav_level.__module__ = _api.__name__
_api.test_char_fav_level = test_char_fav_level

def test_char_question_level_mixes_title_and_favorites():
    # Популярность героя больше не сдвигает уровень относительно тайтла.
    assert _api.char_question_level(1, 10_000) == 1
    assert _api.char_question_level(1, 1) == 1
    assert _api.char_question_level(9, 10_000) == 9
    assert _api.char_question_level(4, -1) == 4

test_char_question_level_mixes_title_and_favorites.__module__ = _api.__name__
_api.test_char_question_level_mixes_title_and_favorites = test_char_question_level_mixes_title_and_favorites

def _char_cand(favorites, *, viewers=1_000, year=2006, char_id=1, main=True):
    """Вопрос-персонаж: узнаваемость тайтла задаётся зрителями и годом, а
    известность самого персонажа — числом добавивших его в избранное."""
    cand = _api.make_candidate(anime={
        "malId": char_id, "id": char_id,
        "statusesStats": [{"status": "completed", "count": viewers}],
        "airedOn": {"year": year}})
    cand.kind = _api.CHAR_KIND
    cand.character = {"id": char_id, "name": f"Персонаж {char_id}", "main": main}
    cand.char_favorites = favorites
    return cand

_char_cand.__module__ = _api.__name__
_api._char_cand = _char_cand

def test_char_price_follows_the_favorites():
    """Много «в избранном» — героя узнают, вопрос дешевле; уровень тот же."""
    famous = _api._char_cand(10_000, char_id=1)
    plain = _api._char_cand(1, char_id=2)
    _api.arrange_questions([famous, plain], _api.PackSettings(pct_songs=0, pct_chars=100))
    assert famous.level == plain.level
    assert famous.price == plain.price - 3
    hidden = _api._char_cand(1, viewers=200_000, year=2024, char_id=3)
    assert _api.char_fav_price_shift(famous) == -3
    assert _api.char_fav_price_shift(_api._char_cand(700, char_id=5)) == -2
    assert _api.char_fav_price_shift(hidden) == 0
    assert _api.char_fav_price_shift(_api._char_cand(-1, char_id=4)) == 0

test_char_price_follows_the_favorites.__module__ = _api.__name__
_api.test_char_price_follows_the_favorites = test_char_price_follows_the_favorites

def test_char_level_avg_pulls_characters_to_the_middle():
    gen = _api._gen(_api.PackSettings(pct_songs=0, pct_chars=100, char_level_avg=5))
    easy = _api._char_cand(10_000, viewers=200_000, year=2024, char_id=1)
    hard = _api._char_cand(0, char_id=2, main=False)
    assert easy.char_level < 5 < hard.char_level
    gen._char_levels = [9, 9, 9]         # средняя уехала вверх
    assert gen._char_level_fits(hard) is False
    assert gen._char_level_fits(easy) is True
    gen._char_levels = [1, 1, 1]         # и наоборот
    assert gen._char_level_fits(easy) is False
    assert gen._char_level_fits(hard) is True
    # Без цели проверки нет вовсе, а песенных вопросов она не касается.
    assert _api._gen(_api.PackSettings())._char_level_fits(hard) is True

test_char_level_avg_pulls_characters_to_the_middle.__module__ = _api.__name__
_api.test_char_level_avg_pulls_characters_to_the_middle = test_char_level_avg_pulls_characters_to_the_middle

def test_char_reach_is_bounded_by_the_title():
    """У героя тайтла шестого уровня достижима только шестёрка."""
    gen = _api._gen(_api.PackSettings(pct_songs=0, pct_chars=100, char_level_avg=3))
    cand = _api._char_cand(-1, viewers=20_000, year=2006)
    assert cand.level == 6
    assert gen._char_reach(cand) == (6, 6)

test_char_reach_is_bounded_by_the_title.__module__ = _api.__name__
_api.test_char_reach_is_bounded_by_the_title = test_char_reach_is_bounded_by_the_title

def _seven(favorites, char_id):
    """Тайтл 4-го уровня для 10 000 и 10-го для нуля (старое имя helper)."""
    viewers = 10_000 if favorites else 100
    return _api._char_cand(favorites, viewers=viewers, year=2024,
                           char_id=char_id)

_seven.__module__ = _api.__name__
_api._seven = _seven

def _warm_up(gen):
    """Даёт генератору насмотреться пула: персонажи от 4-го уровня до 10-го."""
    pool = (_api._seven(10_000, 1), _api._seven(0, 2))
    for n in range(gen.CHAR_REACH_SAMPLE - 1):
        gen._char_level_fits(pool[n % 2])
    assert pool[0].char_level == 4 and pool[1].char_level == 10

_warm_up.__module__ = _api.__name__
_api._warm_up = _warm_up

def test_unreachable_char_level_moves_to_the_nearest_one():
    """Просили 3, а легче четвёрки персонажей в паке не попадается: генератор не
    хватает что попало, а честно говорит об этом и держит четвёрку."""
    lines = []
    gen = _api._gen(_api.PackSettings(pct_songs=0, pct_chars=100, char_level_avg=3),
               log=lines.append)
    gen._char_levels = [8, 8, 8]              # средняя уехала вверх
    _api._warm_up(gen)
    assert gen._char_target_eff == 0           # пока держим то, что просили
    # Кандидатов насмотрелись — недостижимость видна СРАЗУ, без двух десятков
    # впустую перебранных персонажей.
    hard = _api._seven(0, 200)
    assert gen._char_level_fits(hard) is False
    assert gen._char_target_eff == 4
    assert any("недостижима" in line and "держу ближайшую, 4" in line
               for line in lines)
    assert not any("беру что есть" in line for line in lines)
    # И дальше отбор идёт по четвёрке: лёгкий персонаж подходит, трудный нет.
    easy = _api._seven(10_000, 201)
    assert easy.char_level == 4 and hard.char_level > 4
    assert gen._char_level_fits(easy) is True

test_unreachable_char_level_moves_to_the_nearest_one.__module__ = _api.__name__
_api.test_unreachable_char_level_moves_to_the_nearest_one = test_unreachable_char_level_moves_to_the_nearest_one

def test_char_level_returns_when_easier_characters_show_up():
    """Границы только расширяются, поэтому цель ходит лишь В СТОРОНУ просимой:
    попались персонажи полегче — возвращаемся к запрошенной сложности."""
    lines = []
    gen = _api._gen(_api.PackSettings(pct_songs=0, pct_chars=100, char_level_avg=3),
               log=lines.append)
    _api._warm_up(gen)
    gen._char_level_fits(_api._seven(0, 200))
    assert gen._char_target_eff == 4
    # Главный герой хита: и тайтл первого уровня, и в избранном у тысяч.
    star = _api._char_cand(10_000, viewers=200_000, year=2024, char_id=9)
    assert star.char_level == 1
    gen._char_level_fits(star)
    assert gen._char_target_eff == 3
    assert any("возвращаюсь к запрошенной" in line for line in lines)

test_char_level_returns_when_easier_characters_show_up.__module__ = _api.__name__
_api.test_char_level_returns_when_easier_characters_show_up = test_char_level_returns_when_easier_characters_show_up

def test_reachable_char_level_still_gives_up_out_loud():
    """Когда сложность достижима, но подходящих просто не попадается, старое
    поведение сохраняется: одна жалоба и дальше берём что есть."""
    lines = []
    gen = _api._gen(_api.PackSettings(pct_songs=0, pct_chars=100, char_level_avg=7),
               log=lines.append)
    _api._warm_up(gen)                     # в пуле попадались 4-й и 10-й уровни
    gen._char_levels = [10, 10, 10]
    # Семёрка этому паку по силам — просто не попадается.
    hard = _api._char_cand(0, viewers=100, year=2024, char_id=7, main=False)
    for _ in range(gen.CHAR_LEVEL_GIVE_UP):
        assert gen._char_level_fits(hard) is False
    assert gen._char_level_fits(hard) is True
    assert gen._char_target_eff == 0
    assert any("не выдерживается" in line for line in lines)

test_reachable_char_level_still_gives_up_out_loud.__module__ = _api.__name__
_api.test_reachable_char_level_still_gives_up_out_loud = test_reachable_char_level_still_gives_up_out_loud


def test_first_title_swap_is_silent():
    """О подмене ответа на первый тайтл франшизы в лог больше не пишем."""
    lines = []
    gen = _api._gen(_api.PackSettings(pct_songs=0, pct_chars=100), log=lines.append)
    cand = _api.make_candidate(anime={"malId": 999, "id": 999,
                                 "russian": "Наруто: Ураганные хроники"})
    cand.kind = _api.CHAR_KIND
    cand.character = {"id": 17, "name": "Наруто Удзумаки"}
    gen.shikimori.character_titles = lambda cid: {
        "animes": [{"id": 999, "aired_on": "2007-02-15"},
                   {"id": 20, "aired_on": "2002-10-03"}], "mangas": []}
    gen.shikimori.animes_by_ids = lambda ids: [
        _api.make_anime(malId=20, id=20, russian="Наруто")]
    gen._use_first_title(cand)
    assert cand.mal_id == 20
    assert not any("перв" in line.lower() for line in lines)

test_first_title_swap_is_silent.__module__ = _api.__name__
_api.test_first_title_swap_is_silent = test_first_title_swap_is_silent

def test_rejected_character_costs_no_extra_requests():
    """Кандидата, не прошедшего по средней сложности, дальше не разрабатываем.

    «Где ещё был этот персонаж» — ещё один-два запроса к Shikimori, а Shikimori
    даёт всего 90 запросов в минуту: раньше они тратились на вопросы, которые
    тут же выбрасывались, и персонажи занимали десятки минут."""
    asked = []
    gen = _api._gen(_api.PackSettings(pct_songs=0, pct_chars=100, char_level_avg=3))
    gen.shikimori.characters_by_anime_ids = lambda ids, target="anime": {
        ids[0]: [{"id": 5, "name": "Персонаж", "names": ["Персонаж"],
                  "poster": "http://x/p.jpg", "main": True}]}
    gen.shikimori.character_favorites = lambda cid: 1
    gen.shikimori.character_titles = lambda cid: asked.append(cid) or {}
    # Три трудных персонажа уже набраны — четвёртый такой же (безвестный тайтл,
    # в избранном у одного) не подходит и должен отсеяться ДО поиска первого
    # тайтла.
    gen._char_levels.extend([10, 10, 10])
    cand = _api._char_cand(1, char_id=42, viewers=20)
    cand.character = None
    assert gen._fetch_media(cand) is False
    assert cand.rejected is True
    assert asked == []

test_rejected_character_costs_no_extra_requests.__module__ = _api.__name__
_api.test_rejected_character_costs_no_extra_requests = test_rejected_character_costs_no_extra_requests

def test_repeated_complaints_are_hushed():
    """Когда сервер отказывает на каждом вопросе, лог не должен превращаться в
    простыню из одинаковых строк — считаем и подводим итог."""
    lines = []
    gen = _api._gen(_api.PackSettings(), log=lines.append)
    for _ in range(10):
        gen._log_rare("Где ещё был персонаж", "Где ещё был «Кто-то»: 429")
    gen._log_warn_totals()
    assert lines.count("Где ещё был «Кто-то»: 429") == gen.WARN_REPEATS
    assert any("дальше молчу" in line for line in lines)
    assert any("всего таких ошибок за прогон — 10" in line for line in lines)

test_repeated_complaints_are_hushed.__module__ = _api.__name__
_api.test_repeated_complaints_are_hushed = test_repeated_complaints_are_hushed

# ── Частота запросов к Shikimori ────────────────────────────────────────────
class _Clock:
    """Часы под управлением теста: sleep просто двигает стрелки."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(0.0, float(seconds))

_Clock.__module__ = _api.__name__
_api._Clock = _Clock
