# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""test_rate_limiter_honors_the_minute_budget. Public namespace: test_animepack_chars_cache."""
import test_animepack_chars_cache as _api


def test_rate_limiter_honors_the_minute_budget(monkeypatch):
    """У Shikimori лимита два сразу: 5 запросов в секунду и 90 в минуту. Одной
    секундной паузы мало — ровные 2 запроса/с дают 120 в минуту и гарантированный
    429 (из-за него вопросы-персонажи и занимали десятки минут)."""
    import animepack_api as api
    clock = _api._Clock()
    monkeypatch.setattr(api, "time", clock)
    lim = api.RateLimiter(100, per_minute=5)
    for _ in range(5):
        lim.acquire()
    assert clock.now < 1.0
    lim.acquire()          # шестой ждёт, пока состарится самый ранний
    assert clock.now >= 60.0

test_rate_limiter_honors_the_minute_budget.__module__ = _api.__name__
_api.test_rate_limiter_honors_the_minute_budget = test_rate_limiter_honors_the_minute_budget

def test_rate_limiter_penalty_slows_every_thread(monkeypatch):
    """После 429 тормозим ВСЕХ: иначе соседние потоки долбят сервер в том же
    темпе и разговор не налаживается."""
    import animepack_api as api
    clock = _api._Clock()
    monkeypatch.setattr(api, "time", clock)
    lim = api.RateLimiter(100)
    lim.penalize(20.0)
    lim.acquire()
    assert clock.now >= 20.0

test_rate_limiter_penalty_slows_every_thread.__module__ = _api.__name__
_api.test_rate_limiter_penalty_slows_every_thread = test_rate_limiter_penalty_slows_every_thread

def test_shikimori_api_asks_no_more_than_ninety_a_minute():
    import animepack_api as api
    assert api.ShikimoriApi.PER_MINUTE <= 90
    assert api.ShikimoriApi(session=object()).limiter.per_minute \
        == api.ShikimoriApi.PER_MINUTE

test_shikimori_api_asks_no_more_than_ninety_a_minute.__module__ = _api.__name__
_api.test_shikimori_api_asks_no_more_than_ninety_a_minute = test_shikimori_api_asks_no_more_than_ninety_a_minute

def test_shikimori_get_penalizes_on_429(fake_session, fake_response):
    """429 доезжает и статусом (когда ретраи адаптера кончились не совсем)."""
    import animepack_api as api
    shiki = api.ShikimoriApi(fake_session([("/api/", fake_response(429))]))
    before = shiki.limiter._next
    shiki._get(f"{shiki.base_url}/api/characters/1")
    assert shiki.limiter._next >= before + api.ShikimoriApi.RETRY_PENALTY

test_shikimori_get_penalizes_on_429.__module__ = _api.__name__
_api.test_shikimori_get_penalizes_on_429 = test_shikimori_get_penalizes_on_429

def test_shikimori_get_penalizes_adapter_retry_error():
    """urllib3 оборачивает исчерпанные 429 в requests.exceptions.RetryError."""
    import animepack_api as api

    class RetrySession:
        def get(self, *_args, **_kwargs):
            raise api.requests.exceptions.RetryError("too many 429 responses")

    shiki = api.ShikimoriApi(RetrySession())
    before = shiki.limiter._next
    with _api.pytest.raises(api.requests.exceptions.RetryError):
        shiki._get("https://shikimori.io/api/characters/1")
    assert shiki.limiter._next >= before + api.ShikimoriApi.RETRY_PENALTY

test_shikimori_get_penalizes_adapter_retry_error.__module__ = _api.__name__
_api.test_shikimori_get_penalizes_adapter_retry_error = \
    test_shikimori_get_penalizes_adapter_retry_error

# ── Кэш каталога Shikimori ──────────────────────────────────────────────────
def test_db_cache_survives_a_reload(tmp_path):
    path = str(tmp_path / "db.json")
    cache = _api.ShikimoriDbCache(path)
    cache.add_cards("anime", "sig", [{"malId": 1, "russian": "Раз"},
                                     {"malId": 2, "russian": "Два"}])
    cache.add_franchises({"naruto": [_api._part(100, 2002)]})
    assert cache.save() is True

    again = _api.ShikimoriDbCache(path)
    assert {c["malId"] for c in again.cards("anime", "sig")} == {1, 2}
    assert again.franchise("naruto") == [_api._part(100, 2002)]
    # Чужой набор фильтров — чужой мешок, подменять нельзя.
    assert again.cards("anime", "другой") == []
    assert again.franchise("bleach") is None
    # Забыли — и на диске ничего не осталось.
    again.clear()
    assert again.cards("anime", "sig") == []
    assert _api.ShikimoriDbCache(path).cards("anime", "sig") == []

test_db_cache_survives_a_reload.__module__ = _api.__name__
_api.test_db_cache_survives_a_reload = test_db_cache_survives_a_reload

def test_db_cache_keeps_only_a_few_filter_sets(tmp_path):
    cache = _api.ShikimoriDbCache(str(tmp_path / "db.json"))
    for i in range(8):
        cache.add_cards("anime", f"sig{i}", [{"malId": i}])
    kept = [s for s in range(8) if cache.cards("anime", f"sig{s}")]
    assert len(kept) == 4 and kept == [4, 5, 6, 7]     # выпали самые старые

test_db_cache_keeps_only_a_few_filter_sets.__module__ = _api.__name__
_api.test_db_cache_keeps_only_a_few_filter_sets = test_db_cache_keeps_only_a_few_filter_sets

def test_cache_signature_follows_the_filters():
    a = _api.PackSettings(year_from=2000, year_to=2010)
    b = _api.PackSettings(year_from=2000, year_to=2011)
    assert _api.shiki_cache_signature(a) != _api.shiki_cache_signature(b)
    c = _api.PackSettings(year_from=2000, year_to=2010)
    c.kinds = dict(c.kinds, movie=False)
    assert _api.shiki_cache_signature(a) != _api.shiki_cache_signature(c)
    # Манга считается отдельно: её типы к аниме отношения не имеют.
    assert _api.shiki_cache_signature(a) != _api.shiki_cache_signature(a, manga=True)

test_cache_signature_follows_the_filters.__module__ = _api.__name__
_api.test_cache_signature_follows_the_filters = test_cache_signature_follows_the_filters

def test_catalog_is_asked_once_and_then_taken_from_cache(tmp_path):
    """Просьба пользователя: базу собрали один раз — дальше она из кэша."""
    pages = []

    class CountingShiki:
        def random_animes(self, page, **_kw):
            pages.append(page)
            if page > 2:
                return []
            return [_api.make_anime(malId=1000 + page * 50 + i, id=1000 + page * 50 + i)
                    for i in range(50)]

        def franchise_parts(self, keys):
            return {}

    cache = _api.ShikimoriDbCache(str(tmp_path / "db.json"))
    # 12 вопросов × запас 8 = 96 карточек: две страницы каталога.
    s = _api.PackSettings(rounds=1, themes=1, questions=12, pct_songs=0,
                     pct_frames=100)
    first = _api._gen(s, shikimori=CountingShiki(), db_cache=cache)._random_shikimori_ids()
    assert len(first) == 100 and pages

    pages.clear()
    fresh = _api.ShikimoriDbCache(str(tmp_path / "db.json"))
    again = _api._gen(s, shikimori=CountingShiki(),
                 db_cache=fresh)._random_shikimori_ids()
    assert sorted(again) == sorted(first)
    assert pages == []                    # ни одного запроса к серверу

test_catalog_is_asked_once_and_then_taken_from_cache.__module__ = _api.__name__
_api.test_catalog_is_asked_once_and_then_taken_from_cache = test_catalog_is_asked_once_and_then_taken_from_cache

def test_refresh_db_forgets_the_old_catalog(tmp_path):
    class Shiki:
        def random_animes(self, page, **_kw):
            return ([_api.make_anime(malId=7000 + i, id=7000 + i) for i in range(50)]
                    if page == 1 else [])

        def franchise_parts(self, keys):
            return {k: [_api._part(1000, 2019)] for k in keys}

    cache = _api.ShikimoriDbCache(str(tmp_path / "db.json"))
    cache.add_cards("anime", "устаревший", [{"malId": 1}])
    s = _api.PackSettings(rounds=1, themes=1, questions=5, pct_songs=0,
                     pct_frames=100)
    gen = _api._gen(s, shikimori=Shiki(), db_cache=cache)
    assert gen.refresh_db() == 50
    assert cache.cards("anime", "устаревший") == []      # старое забыто
    # Узнаваемость франшиз прогрета заодно — за ней тоже ходить не придётся.
    assert cache.franchise("death_note")

test_refresh_db_forgets_the_old_catalog.__module__ = _api.__name__
_api.test_refresh_db_forgets_the_old_catalog = test_refresh_db_forgets_the_old_catalog

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
            return [_api.make_anime(malId=page * 50 + i, id=page * 50 + i)
                    for i in range(50)]

        def franchise_parts(self, keys):
            return {}

    cache = _api.ShikimoriDbCache(str(tmp_path / "db.json"))
    s = _api.PackSettings(rounds=1, themes=1, questions=5, pct_songs=0,
                     pct_frames=100)
    gen = _api._gen(s, shikimori=Shiki(), db_cache=cache)
    assert gen.refresh_db() == 1000
    # Порядок устойчивый: с order: random страницы накладывались бы друг на
    # друга и каталог не кончился бы никогда.
    assert set(orders) == {"id"}

test_refresh_db_takes_the_whole_catalog_not_just_a_packs_worth.__module__ = _api.__name__
_api.test_refresh_db_takes_the_whole_catalog_not_just_a_packs_worth = test_refresh_db_takes_the_whole_catalog_not_just_a_packs_worth

def test_refresh_db_keeps_what_it_managed_to_take_when_stopped(tmp_path):
    """«Остановить» посреди сбора не теряет набранного."""
    stop = {"now": False}

    class Shiki:
        def random_animes(self, page, **_kw):
            if page >= 3:
                stop["now"] = True             # третья страница — и хватит
            return [_api.make_anime(malId=page * 50 + i, id=page * 50 + i)
                    for i in range(50)]

        def franchise_parts(self, keys):
            return {}

    cache = _api.ShikimoriDbCache(str(tmp_path / "db.json"))
    s = _api.PackSettings(rounds=1, themes=1, questions=5, pct_songs=0,
                     pct_frames=100)
    gen = _api._gen(s, shikimori=Shiki(), db_cache=cache,
               should_stop=lambda: stop["now"])
    assert gen.refresh_db() == 150             # три страницы успели приехать
    saved = _api.ShikimoriDbCache(str(tmp_path / "db.json"))
    assert len(saved.cards("anime", _api.shiki_cache_signature(s))) == 150

test_refresh_db_keeps_what_it_managed_to_take_when_stopped.__module__ = _api.__name__
_api.test_refresh_db_keeps_what_it_managed_to_take_when_stopped = test_refresh_db_keeps_what_it_managed_to_take_when_stopped

# ── Отметки «у кого из списков есть тайтл» ──────────────────────────────────
def test_mark_owners_signs_random_titles_with_nicknames():
    from animepack import UserList, clear_user_list_cache
    clear_user_list_cache()

    class ListsShiki:
        def user_anime_ids(self, nick, statuses, **_kw):
            return {"morr": [1535, 20], "kir": [20]}[nick]

    s = _api.PackSettings(random_mode=True, mark_owners=True,
                     users=[UserList("morr", "shikimori", ["completed"]),
                            UserList("kir", "shikimori", ["completed"])])
    gen = _api._gen(s, shikimori=ListsShiki())
    mine = _api.make_candidate()                          # malId 1535
    theirs = _api.make_candidate(anime={"malId": 20, "id": 20, "russian": "Наруто"})
    nobody = _api.make_candidate(anime={"malId": 999, "id": 999, "russian": "Никто"})
    gen.mark_list_owners([mine, theirs, nobody])
    assert mine.users == ["morr"]
    assert sorted(theirs.users) == ["kir", "morr"]
    assert nobody.users == []
    clear_user_list_cache()

test_mark_owners_signs_random_titles_with_nicknames.__module__ = _api.__name__
_api.test_mark_owners_signs_random_titles_with_nicknames = test_mark_owners_signs_random_titles_with_nicknames

def test_mark_owners_does_nothing_without_the_checkbox():
    from animepack import UserList

    class Boom:
        def user_anime_ids(self, *_a, **_kw):
            raise AssertionError("списки спрашивать не должны")

    s = _api.PackSettings(random_mode=True, mark_owners=False,
                     users=[UserList("morr", "shikimori", ["completed"])])
    cand = _api.make_candidate()
    _api._gen(s, shikimori=Boom()).mark_list_owners([cand])
    assert cand.users == []

test_mark_owners_does_nothing_without_the_checkbox.__module__ = _api.__name__
_api.test_mark_owners_does_nothing_without_the_checkbox = test_mark_owners_does_nothing_without_the_checkbox

# ── Картинка в ответе ───────────────────────────────────────────────────────
def _poster_item(settings, cand):
    root = _api.ET.fromstring(_api.build_content_xml([cand], settings))
    for param in root.iter():
        if param.tag.rsplit("}", 1)[-1] != "param":
            continue
        if param.get("name") != "answer":
            continue
        for item in param:
            if item.get("type") == "image":
                return item
    return None

_poster_item.__module__ = _api.__name__
_api._poster_item = _poster_item

def test_answer_image_time_is_a_setting():
    cand = _api.make_candidate()
    cand.has_poster = True
    s = _api.PackSettings(rounds=1, themes=1, questions=1, answer_image_time=4)
    assert _api._poster_item(s, cand).get("duration") == "00:00:04"
    # Ноль — «без ограничения»: атрибута нет, картинка висит до перехода.
    s.answer_image_time = 0
    assert _api._poster_item(s, cand).get("duration") is None

test_answer_image_time_is_a_setting.__module__ = _api.__name__
_api.test_answer_image_time_is_a_setting = test_answer_image_time_is_a_setting

def test_answer_image_time_never_exceeds_the_ceiling():
    """Дольше ANSWER_IMAGE_MAX постер не висит (просьба пользователя): игра на
    это время стоит. Подрезается и то, что осталось в старых настройках."""
    from animepack import ANSWER_IMAGE_MAX
    cand = _api.make_candidate()
    cand.has_poster = True
    s = _api.PackSettings(rounds=1, themes=1, questions=1, answer_image_time=30)
    assert _api._poster_item(s, cand).get("duration") == f"00:00:0{ANSWER_IMAGE_MAX}"
    assert _api.PackSettings.from_dict({"answer_image_time": 30}).answer_image_time \
        == ANSWER_IMAGE_MAX

test_answer_image_time_never_exceeds_the_ceiling.__module__ = _api.__name__
_api.test_answer_image_time_never_exceeds_the_ceiling = test_answer_image_time_never_exceeds_the_ceiling
