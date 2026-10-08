# -*- coding: utf-8 -*-
"""Генерация аниме-пака: сложность персонажей, кэш каталога и отметки списков.

Здесь всё, что появилось вокруг узнаваемости: «в избранном» у персонажа как
вторая мера сложности, узнаваемость франшизы по её частям, кэш каталога
Shikimori на диске, отметки «у кого из списков есть тайтл» и длительность
картинки в ответе.
"""
import xml.etree.ElementTree as ET

import pytest

from animepack import (CHAR_KIND, AnimePackGenerator, PackSettings,
                       ShikimoriDbCache, arrange_questions, build_content_xml,
                       char_fav_level, char_fav_price_shift,
                       char_question_level, shiki_cache_signature)
from shikimori_api import franchise_parts_index
from test_animepack import make_anime, make_candidate


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

    return AnimePackGenerator(settings, session=object(), amq=object(),
                              anisong=object(), mal=object(),
                              shikimori=shikimori or FakeShiki(),
                              anilist=object(), kitsu=object(),
                              themes=object(), **kw)

def _part(base, year, score=7.0):
    return {"statusesStats": [{"status": "completed", "count": base}],
            "airedOn": {"year": year}, "score": score}

# ── Узнаваемость франшизы по её частям ──────────────────────────────────────
def test_franchise_index_rises_with_live_seasons():
    """У сериала с несколькими популярными сезонами узнаваемость выше, чем у
    одиночного тайтла с тем же числом зрителей."""
    alone = franchise_parts_index([_part(10_000, 2019)])
    series = franchise_parts_index([_part(10_000, 2019), _part(9_000, 2019),
                                    _part(8_000, 2019), _part(7_000, 2019)])
    assert series > alone
    # Надбавка именно «чуть»: потолок — четверть.
    assert series <= alone * 1.26

def test_franchise_index_softens_the_age_penalty_for_sequels():
    """Первый сезон 2002-го с популярным продолжением 2019-го теряет за возраст
    меньше, чем такой же одиночка без продолжений (просьба пользователя)."""
    old_alone = franchise_parts_index([_part(10_000, 2002)])
    with_sequel = franchise_parts_index([_part(10_000, 2002), _part(9_000, 2019)])
    assert with_sequel > old_alone
    # Но и ровесником сиквела оригинал не становится: год не подменяется
    # целиком, а усредняется.
    fresh = franchise_parts_index([_part(10_000, 2019)])
    assert with_sequel < fresh

def test_franchise_index_ignores_unpopular_parts():
    """Спешл, которого никто не смотрел, франшизу не омолаживает."""
    plain = franchise_parts_index([_part(10_000, 2002)])
    with_ova = franchise_parts_index([_part(10_000, 2002), _part(50, 2024)])
    assert with_ova == pytest.approx(plain)

def test_franchise_index_of_nothing_is_zero():
    assert franchise_parts_index([]) == 0.0
    assert franchise_parts_index([{"statusesStats": []}]) == 0.0
    assert franchise_parts_index(None) == 0.0

def test_franchise_index_does_not_age_the_newest_top_part():
    """«Стальной алхимик: Братство» 2009-го популярнее частей 2003-го — старость
    предшественников ему не приписывается."""
    top_is_new = franchise_parts_index([_part(10_000, 2009), _part(4_000, 2003)])
    alone = franchise_parts_index([_part(10_000, 2009)])
    assert top_is_new >= alone

# ── «В избранном» как мера сложности персонажа ──────────────────────────────
@pytest.mark.parametrize("favorites,level", [
    (10_740, 1), (5_000, 1), (3_000, 2), (2_000, 3), (900, 5),
    (89, 11), (4, 14), (1, 15), (0, 15), (None, 15), ("нет", 15),
])
def test_char_fav_level(favorites, level):
    assert char_fav_level(favorites) == level

def test_char_question_level_mixes_title_and_favorites():
    # Популярность героя больше не сдвигает уровень относительно тайтла.
    assert char_question_level(1, 10_000) == 1
    assert char_question_level(1, 1) == 1
    assert char_question_level(9, 10_000) == 9
    assert char_question_level(4, -1) == 4

def _char_cand(favorites, *, viewers=1_000, year=2006, char_id=1, main=True):
    """Вопрос-персонаж: узнаваемость тайтла задаётся зрителями и годом, а
    известность самого персонажа — числом добавивших его в избранное."""
    cand = make_candidate(anime={
        "malId": char_id, "id": char_id,
        "statusesStats": [{"status": "completed", "count": viewers}],
        "airedOn": {"year": year}})
    cand.kind = CHAR_KIND
    cand.character = {"id": char_id, "name": f"Персонаж {char_id}", "main": main}
    cand.char_favorites = favorites
    return cand

def test_char_price_follows_the_favorites():
    """Много «в избранном» — героя узнают, вопрос дешевле; уровень тот же."""
    famous = _char_cand(10_000, char_id=1)
    plain = _char_cand(1, char_id=2)
    arrange_questions([famous, plain], PackSettings(pct_songs=0, pct_chars=100))
    assert famous.level == plain.level
    assert famous.price == plain.price - 3
    hidden = _char_cand(1, viewers=200_000, year=2024, char_id=3)
    assert char_fav_price_shift(famous) == -3
    assert char_fav_price_shift(_char_cand(700, char_id=5)) == -2
    assert char_fav_price_shift(hidden) == 0
    assert char_fav_price_shift(_char_cand(-1, char_id=4)) == 0

def test_char_level_avg_pulls_characters_to_the_middle():
    gen = _gen(PackSettings(pct_songs=0, pct_chars=100, char_level_avg=5))
    easy = _char_cand(10_000, viewers=200_000, year=2024, char_id=1)
    hard = _char_cand(0, char_id=2, main=False)
    assert easy.char_level < 5 < hard.char_level
    gen._char_levels = [9, 9, 9]         # средняя уехала вверх
    assert gen._char_level_fits(hard) is False
    assert gen._char_level_fits(easy) is True
    gen._char_levels = [1, 1, 1]         # и наоборот
    assert gen._char_level_fits(easy) is False
    assert gen._char_level_fits(hard) is True
    # Без цели проверки нет вовсе, а песенных вопросов она не касается.
    assert _gen(PackSettings())._char_level_fits(hard) is True

def test_char_reach_is_bounded_by_the_title():
    """У героя тайтла шестого уровня достижима только шестёрка."""
    gen = _gen(PackSettings(pct_songs=0, pct_chars=100, char_level_avg=3))
    cand = _char_cand(-1, viewers=20_000, year=2006)
    assert cand.level == 6
    assert gen._char_reach(cand) == (6, 6)

def _seven(favorites, char_id):
    """Тайтл 4-го уровня для 10 000 и 10-го для нуля (старое имя helper)."""
    viewers = 10_000 if favorites else 100
    return _char_cand(favorites, viewers=viewers, year=2024,
                           char_id=char_id)

def _warm_up(gen):
    """Даёт генератору насмотреться пула: персонажи от 4-го уровня до 10-го."""
    pool = (_seven(10_000, 1), _seven(0, 2))
    for n in range(gen.CHAR_REACH_SAMPLE - 1):
        gen._char_level_fits(pool[n % 2])
    assert pool[0].char_level == 4 and pool[1].char_level == 10

def test_unreachable_char_level_keeps_the_requested_target():
    """Просили 3, а средняя уехала вверх: цель не подменяется молча (правка
    настройки — дело пользователя), трудный персонаж не берётся, а лёгкий,
    возвращающий среднюю к просимой, — берётся."""
    lines = []
    gen = _gen(PackSettings(pct_songs=0, pct_chars=100, char_level_avg=3),
               log=lines.append)
    gen._char_levels = [8, 8, 8]              # средняя уехала вверх
    _warm_up(gen)
    hard = _seven(0, 200)
    assert gen._char_level_fits(hard) is False
    assert gen._char_target_eff == 3
    assert not any("держу ближайшую" in line or "беру что есть" in line
                   for line in lines)
    easy = _seven(10_000, 201)
    assert easy.char_level == 4 and hard.char_level > 4
    assert gen._char_level_fits(easy) is True

def test_char_level_target_stays_put_when_easier_characters_show_up():
    """Цель одна на весь прогон: и после отказа трудному, и после лёгкого
    персонажа она остаётся той, что просили."""
    gen = _gen(PackSettings(pct_songs=0, pct_chars=100, char_level_avg=3))
    _warm_up(gen)
    gen._char_level_fits(_seven(0, 200))
    assert gen._char_target_eff == 3
    # Главный герой хита: и тайтл первого уровня, и в избранном у тысяч.
    star = _char_cand(10_000, viewers=200_000, year=2024, char_id=9)
    assert star.char_level == 1
    assert gen._char_level_fits(star) is True
    assert gen._char_target_eff == 3

def test_char_average_does_not_give_up_after_many_rejections():
    """Средняя персонажей строгая: сколько бы трудных ни попадалось подряд,
    клапана «беру что есть» у неё нет."""
    lines = []
    gen = _gen(PackSettings(pct_songs=0, pct_chars=100, char_level_avg=7),
               log=lines.append)
    _warm_up(gen)
    gen._char_levels = [10, 10, 10]
    hard = _char_cand(0, viewers=100, year=2024, char_id=7, main=False)
    for _ in range(gen.CHAR_LEVEL_GIVE_UP + 1):
        assert gen._char_level_fits(hard) is False
    assert gen._char_target_eff == 7
    assert not any("не выдерживается" in line for line in lines)


def test_first_title_swap_is_silent():
    """О подмене ответа на первый тайтл франшизы в лог больше не пишем."""
    lines = []
    gen = _gen(PackSettings(pct_songs=0, pct_chars=100), log=lines.append)
    cand = make_candidate(anime={"malId": 999, "id": 999,
                                 "russian": "Наруто: Ураганные хроники"})
    cand.kind = CHAR_KIND
    cand.character = {"id": 17, "name": "Наруто Удзумаки"}
    gen.shikimori.character_titles = lambda cid: {
        "animes": [{"id": 999, "aired_on": "2007-02-15"},
                   {"id": 20, "aired_on": "2002-10-03"}], "mangas": []}
    gen.shikimori.animes_by_ids = lambda ids: [
        make_anime(malId=20, id=20, russian="Наруто")]
    gen._use_first_title(cand)
    assert cand.mal_id == 20
    assert not any("перв" in line.lower() for line in lines)

def test_character_difficulty_checked_after_debut_before_media():
    """Сложность считаем после проверки дебюта, до скачивания портрета."""
    asked = []
    gen = _gen(PackSettings(pct_songs=0, pct_chars=100, char_level_avg=3))
    gen.shikimori.characters_by_anime_ids = lambda ids, target="anime": {
        ids[0]: [{"id": 5, "name": "Персонаж", "names": ["Персонаж"],
                  "poster": "http://x/p.jpg", "main": True}]}
    gen.shikimori.character_favorites = lambda cid: 1
    gen.shikimori.character_titles = lambda cid: asked.append(cid) or {
        "animes": [{"id": 42, "aired_on": "2006-01-01"}]}
    downloaded = []
    gen.download_images = lambda cand: downloaded.append(cand)
    # Три трудных персонажа уже набраны — четвёртый такой же (безвестный тайтл,
    # в избранном у одного) не подходит после подтверждения первого тайтла.
    gen._char_levels.extend([10, 10, 10])
    cand = _char_cand(1, char_id=42, viewers=20)
    cand.character = None
    assert gen._fetch_media(cand) is False
    assert cand.rejected is True
    assert asked == [5]
    assert downloaded == []

def test_repeated_complaints_are_hushed():
    """Когда сервер отказывает на каждом вопросе, лог не должен превращаться в
    простыню из одинаковых строк — считаем и подводим итог."""
    lines = []
    gen = _gen(PackSettings(), log=lines.append)
    for _ in range(10):
        gen._log_rare("Где ещё был персонаж", "Где ещё был «Кто-то»: 429")
    gen._log_warn_totals()
    assert lines.count("Где ещё был «Кто-то»: 429") == gen.WARN_REPEATS
    assert any("дальше молчу" in line for line in lines)
    assert any("всего таких ошибок за прогон — 10" in line for line in lines)

# ── Частота запросов к Shikimori ────────────────────────────────────────────
class _Clock:
    """Часы под управлением теста: sleep просто двигает стрелки."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(0.0, float(seconds))


def test_rate_limiter_honors_the_minute_budget(monkeypatch):
    """У Shikimori лимита два сразу: 5 запросов в секунду и 90 в минуту. Одной
    секундной паузы мало — ровные 2 запроса/с дают 120 в минуту и гарантированный
    429 (из-за него вопросы-персонажи и занимали десятки минут)."""
    import animepack_api as api
    clock = _Clock()
    monkeypatch.setattr(api, "time", clock)
    lim = api.RateLimiter(100, per_minute=5)
    for _ in range(5):
        lim.acquire()
    assert clock.now < 1.0
    lim.acquire()          # шестой ждёт, пока состарится самый ранний
    assert clock.now >= 60.0

def test_rate_limiter_penalty_slows_every_thread(monkeypatch):
    """После 429 тормозим ВСЕХ: иначе соседние потоки долбят сервер в том же
    темпе и разговор не налаживается."""
    import animepack_api as api
    clock = _Clock()
    monkeypatch.setattr(api, "time", clock)
    lim = api.RateLimiter(100)
    lim.penalize(20.0)
    lim.acquire()
    assert clock.now >= 20.0

def test_shikimori_api_asks_no_more_than_ninety_a_minute():
    import animepack_api as api
    assert api.ShikimoriApi.PER_MINUTE <= 90
    assert api.ShikimoriApi(session=object()).limiter.per_minute \
        == api.ShikimoriApi.PER_MINUTE

def test_shikimori_get_penalizes_on_429(fake_session, fake_response):
    """429 доезжает и статусом (когда ретраи адаптера кончились не совсем)."""
    import animepack_api as api
    shiki = api.ShikimoriApi(fake_session([("/api/", fake_response(429))]))
    before = shiki.limiter._next
    shiki._get(f"{shiki.base_url}/api/characters/1")
    assert shiki.limiter._next >= before + api.ShikimoriApi.RETRY_PENALTY

def test_shikimori_get_penalizes_adapter_retry_error():
    """urllib3 оборачивает исчерпанные 429 в requests.exceptions.RetryError."""
    import animepack_api as api

    class RetrySession:
        def get(self, *_args, **_kwargs):
            raise api.requests.exceptions.RetryError("too many 429 responses")

    shiki = api.ShikimoriApi(RetrySession())
    before = shiki.limiter._next
    with pytest.raises(api.requests.exceptions.RetryError):
        shiki._get("https://shikimori.io/api/characters/1")
    assert shiki.limiter._next >= before + api.ShikimoriApi.RETRY_PENALTY

# ── Кэш каталога Shikimori ──────────────────────────────────────────────────
def test_db_cache_survives_a_reload(tmp_path):
    path = str(tmp_path / "db.json")
    cache = ShikimoriDbCache(path)
    cache.add_cards("anime", "sig", [{"malId": 1, "russian": "Раз"},
                                     {"malId": 2, "russian": "Два"}])
    cache.add_franchises({"naruto": [_part(100, 2002)]})
    assert cache.save() is True

    again = ShikimoriDbCache(path)
    assert {c["malId"] for c in again.cards("anime", "sig")} == {1, 2}
    assert again.franchise("naruto") == [_part(100, 2002)]
    # Чужой набор фильтров — чужой мешок, подменять нельзя.
    assert again.cards("anime", "другой") == []
    assert again.franchise("bleach") is None
    # Забыли — и на диске ничего не осталось.
    again.clear()
    assert again.cards("anime", "sig") == []
    assert ShikimoriDbCache(path).cards("anime", "sig") == []

def test_db_cache_keeps_only_a_few_filter_sets(tmp_path):
    cache = ShikimoriDbCache(str(tmp_path / "db.json"))
    for i in range(8):
        cache.add_cards("anime", f"sig{i}", [{"malId": i}])
    kept = [s for s in range(8) if cache.cards("anime", f"sig{s}")]
    assert len(kept) == 4 and kept == [4, 5, 6, 7]     # выпали самые старые

def test_cache_signature_follows_the_filters():
    a = PackSettings(year_from=2000, year_to=2010)
    b = PackSettings(year_from=2000, year_to=2011)
    assert shiki_cache_signature(a) != shiki_cache_signature(b)
    c = PackSettings(year_from=2000, year_to=2010)
    c.kinds = dict(c.kinds, movie=False)
    assert shiki_cache_signature(a) != shiki_cache_signature(c)
    # Манга считается отдельно: её типы к аниме отношения не имеют.
    assert shiki_cache_signature(a) != shiki_cache_signature(a, manga=True)

def test_catalog_is_asked_once_and_then_taken_from_cache(tmp_path):
    """Просьба пользователя: базу собрали один раз — дальше она из кэша."""
    pages = []

    class CountingShiki:
        def random_animes(self, page, **_kw):
            pages.append(page)
            if page > 2:
                return []
            return [make_anime(malId=1000 + page * 50 + i, id=1000 + page * 50 + i)
                    for i in range(50)]

        def franchise_parts(self, keys):
            return {}

    cache = ShikimoriDbCache(str(tmp_path / "db.json"))
    # 12 вопросов × запас 8 = 96 карточек: две страницы каталога.
    s = PackSettings(rounds=1, themes=1, questions=12, pct_songs=0,
                     pct_frames=100)
    first = _gen(s, shikimori=CountingShiki(), db_cache=cache)._random_shikimori_ids()
    assert len(first) == 100 and pages

    pages.clear()
    fresh = ShikimoriDbCache(str(tmp_path / "db.json"))
    again = _gen(s, shikimori=CountingShiki(),
                 db_cache=fresh)._random_shikimori_ids()
    assert sorted(again) == sorted(first)
    assert pages == []                    # ни одного запроса к серверу

def test_refresh_db_forgets_the_old_catalog(tmp_path):
    class Shiki:
        def random_animes(self, page, **_kw):
            return ([make_anime(malId=7000 + i, id=7000 + i) for i in range(50)]
                    if page == 1 else [])

        def franchise_parts(self, keys):
            return {k: [_part(1000, 2019)] for k in keys}

    cache = ShikimoriDbCache(str(tmp_path / "db.json"))
    cache.add_cards("anime", "устаревший", [{"malId": 1}])
    s = PackSettings(rounds=1, themes=1, questions=5, pct_songs=0,
                     pct_frames=100)
    gen = _gen(s, shikimori=Shiki(), db_cache=cache)
    assert gen.refresh_db(("anime", "franchises")) == 50
    assert cache.cards("anime", "устаревший") == []      # старое забыто
    # Узнаваемость франшиз прогрета заодно — за ней тоже ходить не придётся.
    assert cache.franchise("death_note")

def test_refresh_db_takes_the_whole_catalog_not_just_a_packs_worth(tmp_path):
    """Кнопка «Обновить базу» берёт каталог ЦЕЛИКОМ.

    Раньше она набирала ровно столько, сколько нужно на один пак («вопросов ×
    запас»), и база останавливалась на нескольких сотнях карточек."""
    orders = []

    class Shiki:
        def random_animes(self, page, order="random", **_kw):
            orders.append(order)
            if page > 20:                      # 20 страниц по 50 — весь каталог
                return []
            return [make_anime(malId=page * 50 + i, id=page * 50 + i)
                    for i in range(50)]

        def franchise_parts(self, keys):
            return {}

    cache = ShikimoriDbCache(str(tmp_path / "db.json"))
    s = PackSettings(rounds=1, themes=1, questions=5, pct_songs=0,
                     pct_frames=100)
    gen = _gen(s, shikimori=Shiki(), db_cache=cache)
    assert gen.refresh_db(("anime",)) == 1000
    # Порядок устойчивый: с order: random страницы накладывались бы друг на
    # друга и каталог не кончился бы никогда.
    assert set(orders) == {"id"}

def test_refresh_db_keeps_what_it_managed_to_take_when_stopped(tmp_path):
    """«Остановить» посреди сбора не теряет набранного."""
    stop = {"now": False}

    class Shiki:
        def random_animes(self, page, **_kw):
            if page >= 3:
                stop["now"] = True             # третья страница — и хватит
            return [make_anime(malId=page * 50 + i, id=page * 50 + i)
                    for i in range(50)]

        def franchise_parts(self, keys):
            return {}

    cache = ShikimoriDbCache(str(tmp_path / "db.json"))
    s = PackSettings(rounds=1, themes=1, questions=5, pct_songs=0,
                     pct_frames=100)
    gen = _gen(s, shikimori=Shiki(), db_cache=cache,
               should_stop=lambda: stop["now"])
    assert gen.refresh_db(("anime",)) == 150   # три страницы успели приехать
    saved = ShikimoriDbCache(str(tmp_path / "db.json"))
    assert len(saved.all_cards("anime")) == 150

# ── Отметки «у кого из списков есть тайтл» ──────────────────────────────────
def test_mark_owners_signs_random_titles_with_nicknames():
    from animepack import UserList, clear_user_list_cache
    clear_user_list_cache()

    class ListsShiki:
        def user_anime_ids(self, nick, statuses, **_kw):
            return {"morr": [1535, 20], "kir": [20]}[nick]

    s = PackSettings(random_mode=True, mark_owners=True,
                     users=[UserList("morr", "shikimori", ["completed"]),
                            UserList("kir", "shikimori", ["completed"])])
    gen = _gen(s, shikimori=ListsShiki())
    mine = make_candidate()                          # malId 1535
    theirs = make_candidate(anime={"malId": 20, "id": 20, "russian": "Наруто"})
    nobody = make_candidate(anime={"malId": 999, "id": 999, "russian": "Никто"})
    gen.mark_list_owners([mine, theirs, nobody])
    assert mine.users == ["morr"]
    assert sorted(theirs.users) == ["kir", "morr"]
    assert nobody.users == []
    clear_user_list_cache()

def test_mark_owners_does_nothing_without_the_checkbox():
    from animepack import UserList

    class Boom:
        def user_anime_ids(self, *_a, **_kw):
            raise AssertionError("списки спрашивать не должны")

    s = PackSettings(random_mode=True, mark_owners=False,
                     users=[UserList("morr", "shikimori", ["completed"])])
    cand = make_candidate()
    _gen(s, shikimori=Boom()).mark_list_owners([cand])
    assert cand.users == []

# ── Картинка в ответе ───────────────────────────────────────────────────────
def _poster_item(settings, cand):
    root = ET.fromstring(build_content_xml([cand], settings))
    for param in root.iter():
        if param.tag.rsplit("}", 1)[-1] != "param":
            continue
        if param.get("name") != "answer":
            continue
        for item in param:
            if item.get("type") == "image":
                return item
    return None

def test_answer_image_time_is_a_setting():
    cand = make_candidate()
    cand.has_poster = True
    s = PackSettings(rounds=1, themes=1, questions=1, answer_image_time=4)
    assert _poster_item(s, cand).get("duration") == "00:00:04"
    # Ноль — «без ограничения»: атрибута нет, картинка висит до перехода.
    s.answer_image_time = 0
    assert _poster_item(s, cand).get("duration") is None

def test_answer_image_time_never_exceeds_the_ceiling():
    """Дольше ANSWER_IMAGE_MAX постер не висит (просьба пользователя): игра на
    это время стоит. Подрезается и то, что осталось в старых настройках."""
    from animepack import ANSWER_IMAGE_MAX
    cand = make_candidate()
    cand.has_poster = True
    s = PackSettings(rounds=1, themes=1, questions=1, answer_image_time=30)
    assert _poster_item(s, cand).get("duration") == f"00:00:0{ANSWER_IMAGE_MAX}"
    assert PackSettings.from_dict({"answer_image_time": 30}).answer_image_time \
        == ANSWER_IMAGE_MAX


# ── Сетевой слой: «в избранном» и части франшизы ────────────────────────────
_CHAR_PAGE = ('<body class="p-characters p-characters-show">'
              '<div class="b-favoured"><div class="subheadline">'
              '<div class="linkeable" data-href="/characters/417/favoured">'
              'В избранном<div class="count">10740</div></div></div>'
              '<div class="cc">…</div></div></body>')


def test_character_favorites_are_read_from_the_page(fake_session, fake_response):
    """В API этого числа нет вовсе: у GraphQL-типа Character полей про избранное
    не существует, а REST отдаёт лишь флаг «добавил ли я». Берём со страницы."""
    import animepack_api as api
    session = fake_session([("/characters/417",
                             fake_response(text=_CHAR_PAGE))])
    assert api.ShikimoriApi(session).character_favorites(417) == 10740

def test_character_without_favorites_is_zero_not_unknown(fake_session,
                                                         fake_response):
    """Страница пришла, блока нет — значит в избранном он ни у кого. А вот 404 и
    посторонний ответ — это «не узнали», и путать их нельзя: иначе сложность
    вопроса считалась бы по случайности."""
    import animepack_api as api
    empty = '<body class="p-characters p-characters-show">пусто</body>'
    session = fake_session([("/characters/5", fake_response(text=empty))])
    assert api.ShikimoriApi(session).character_favorites(5) == 0

    gone = fake_session([("/characters/6", fake_response(status_code=404))])
    assert api.ShikimoriApi(gone).character_favorites(6) == -1

    junk = fake_session([("/characters/7", fake_response(text="<html>?</html>"))])
    assert api.ShikimoriApi(junk).character_favorites(7) == -1
    assert api.ShikimoriApi(junk).character_favorites("ерунда") == -1

def test_franchise_parts_returns_every_season(fake_session):
    """Запрашиваем не одну самую популярную часть, а первые FRANCHISE_PARTS."""
    import animepack_api as api
    asked = {}

    class FakeClient:
        base_url = "https://shikimori.io"

        def _graphql(self, query, variables):
            asked["query"] = query
            return {"f0": [_part(1000, 2002), _part(900, 2007)], "f1": []}

    parts = api.ShikimoriApi(session=object(),
                             client=FakeClient()).franchise_parts(["naruto",
                                                                   "bleach"])
    assert f"limit: {api.ShikimoriApi.FRANCHISE_PARTS}" in asked["query"]
    assert len(parts["naruto"]) == 2
    # Пустой ответ — тоже ответ: ключ есть, спрашивать снова незачем.
    assert parts["bleach"] == []

def test_franchise_parts_keep_quiet_about_a_broken_batch(fake_session):
    """Сорвавшуюся пачку не выдаём за «частей нет»: разовый обрыв связи иначе
    навсегда осел бы в кэше нулевой узнаваемостью."""
    import animepack_api as api

    class DeadClient:
        base_url = "https://shikimori.io"

        def _graphql(self, query, variables):
            raise RuntimeError("нет связи")

    parts = api.ShikimoriApi(session=object(),
                             client=DeadClient()).franchise_parts(["naruto"])
    assert parts == {}

def test_franchise_parts_stay_below_graphql_complexity_limit():
    """Четырнадцатую франшизу выносим в следующий GraphQL-документ."""
    import animepack_api as api
    sizes = []

    class FakeClient:
        base_url = "https://shikimori.io"

        def _graphql(self, query, variables):
            size = query.count(": animes")
            sizes.append(size)
            return {f"f{i}": [] for i in range(size)}

    keys = [f"series_{i}" for i in range(14)]
    parts = api.ShikimoriApi(session=object(),
                             client=FakeClient()).franchise_parts(keys)
    assert sizes == [13, 1]
    assert set(parts) == set(keys)

def test_franchise_parts_preserve_bracketed_cache_key():
    """Скобки — часть ключа Shikimori и остаются в запросе и кэше."""
    import animepack_api as api
    asked = {}

    class FakeClient:
        base_url = "https://shikimori.io"

        def _graphql(self, query, variables):
            asked["query"] = query
            return {"f0": [_part(100, 2024)]}

    parts = api.ShikimoriApi(session=object(),
                             client=FakeClient()).franchise_parts(
                                 ["[oshi_no_ko]"])
    assert 'franchise: "[oshi_no_ko]"' in asked["query"]
    assert list(parts) == ["[oshi_no_ko]"]

def _replic(settings, cand):
    root = ET.fromstring(build_content_xml([cand], settings))
    for item in root.iter():
        if item.get("placement") == "replic":
            return item.text
    return None

def test_artist_comes_first_and_nicks_are_bare():
    """Порядок в реплике один и тот же, откуда бы ни собрался пак: сперва
    исполнитель, потом голые ники — без «Есть у» (просьба пользователя)."""
    cand = make_candidate()
    cand.users = ["morr", "kao"]
    marked = PackSettings(rounds=1, themes=1, questions=1, random_mode=True,
                          mark_owners=True)
    by_lists = PackSettings(rounds=1, themes=1, questions=1, random_mode=False,
                            mark_owners=False)
    want = "Исполнитель — 『Nightmare』 · Сложность AMQ — 85 · Рейтинг MAL — 『8.60⭐』 · morr, kao"
    assert _replic(marked, cand) == want
    assert _replic(by_lists, cand) == want
    assert "Есть у" not in want

def test_nicks_alone_when_the_question_is_not_a_song():
    """У вопроса-персонажа исполнителя нет — остаются одни ники."""
    cand = _char_cand(500)
    cand.users = ["morr"]
    s = PackSettings(rounds=1, themes=1, questions=1, random_mode=True,
                     mark_owners=True)
    assert _replic(s, cand) == "morr"
