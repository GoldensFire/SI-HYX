# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""test_fmt_elapsed. Public namespace: test_animepack."""
import test_animepack as _api


# ── Прочее ───────────────────────────────────────────────────────────────────
def test_fmt_elapsed():
    assert _api.fmt_elapsed(48) == "48 с"
    assert _api.fmt_elapsed(200) == "3 мин 20 с"
    assert _api.fmt_elapsed(180) == "3 мин"
    assert _api.fmt_elapsed(3900) == "1 ч 5 мин"
    assert _api.fmt_elapsed(None) == "0 с"

test_fmt_elapsed.__module__ = _api.__name__
_api.test_fmt_elapsed = test_fmt_elapsed

def test_similar_count_one_is_allowed():
    """Минимум «у 1 человека» — законная настройка, а не ошибка."""
    s = _api.PackSettings(random_mode=False, similar_count=1,
                     users=[_api.UserList("morr", "shikimori", ["completed"])])
    assert not any("Похожие" in p for p in s.validate())

test_similar_count_one_is_allowed.__module__ = _api.__name__
_api.test_similar_count_one_is_allowed = test_similar_count_one_is_allowed


def test_sort_by_index_orders_pack_and_prices():
    """Порядок — по узнаваемости, цена — узнаваемость плюс сложность AMQ."""
    s = _api.PackSettings(rounds=1, themes=3, questions=1, sort_by_index=True)
    hot = _api.make_candidate(song={"annSongId": 1, "songDifficulty": 5.0},
                         anime={"malId": 1, "airedOn": {"year": 2024},
                                "statusesStats": [{"status": "completed",
                                                   "count": 100000}]})
    mid = _api.make_candidate(song={"annSongId": 2, "songDifficulty": 95.0},
                         anime={"malId": 2, "airedOn": {"year": 2010},
                                "statusesStats": [{"status": "completed",
                                                   "count": 5000}]})
    cold = _api.make_candidate(song={"annSongId": 3, "songDifficulty": 50.0},
                          anime={"malId": 3, "airedOn": {"year": 1998},
                                 "statusesStats": []})
    themes = _api.arrange_questions([mid, cold, hot], s)
    # Пак идёт от самых узнаваемых тайтлов к самым безвестным.
    assert [t[0].mal_id for t in themes] == [1, 2, 3]
    # База — место по индексу (6 / 12 / 20), сверху надбавка за сложность
    # самой песни: почти неугадываемая (5) даёт все десять очков, лёгкая (95) —
    # ничего, средняя (50) — половину.
    assert [t[0].price for t in themes] == [16, 12, 25]

    # Без сортировки по индексу цены те же — база у них общая, — а вопросы в
    # теме идут по возрастанию цены.
    s = _api.PackSettings(rounds=1, themes=1, questions=3)
    theme = _api.arrange_questions([mid, cold, hot], s)[0]
    assert [c.price for c in theme] == [12, 16, 25]

test_sort_by_index_orders_pack_and_prices.__module__ = _api.__name__
_api.test_sort_by_index_orders_pack_and_prices = test_sort_by_index_orders_pack_and_prices

def test_build_content_xml_stops_when_songs_run_out():
    s = _api.PackSettings(rounds=3, themes=5, questions=6)
    root, ns = _api._parse(_api.build_content_xml([_api.make_candidate()], s))
    assert len(root.findall(".//s:round", ns)) == 1
    assert len(root.findall(".//s:question", ns)) == 1

test_build_content_xml_stops_when_songs_run_out.__module__ = _api.__name__
_api.test_build_content_xml_stops_when_songs_run_out = test_build_content_xml_stops_when_songs_run_out

# ── Сетевой слой ─────────────────────────────────────────────────────────────
def test_anisong_uses_snake_case_body():
    """ASPG слал malIds — сервер отвечал пустым списком."""
    session = _api.FakeSession([("mal_ids_request", _api.FakeResponse(json_data=[{"a": 1}]))])
    anisong = _api.api.AnisongApi(session)
    assert anisong.songs_by_mal_ids([1535]) == [{"a": 1}]
    _method, _url, kw = session.calls[-1]
    assert kw["json"] == {"mal_ids": [1535]}

    session = _api.FakeSession([("ann_ids_request", _api.FakeResponse(json_data=[]))])
    _api.api.AnisongApi(session).songs_by_ann_ids([1, 2])
    assert session.calls[-1][2]["json"] == {"ann_ids": [1, 2]}

test_anisong_uses_snake_case_body.__module__ = _api.__name__
_api.test_anisong_uses_snake_case_body = test_anisong_uses_snake_case_body

def test_anisong_empty_ids_makes_no_request():
    session = _api.FakeSession()
    assert _api.api.AnisongApi(session).songs_by_mal_ids([]) == []
    assert session.calls == []

test_anisong_empty_ids_makes_no_request.__module__ = _api.__name__
_api.test_anisong_empty_ids_makes_no_request = test_anisong_empty_ids_makes_no_request

def test_mal_paginates_and_filters_statuses():
    page1 = [{"anime_id": i, "status": 2} for i in range(300)]
    page2 = [{"anime_id": 1000, "status": 6}, {"anime_id": 1001, "status": 2}]

    def route(url, **kw):
        offset = kw.get("params", {}).get("offset", 0)
        return _api.FakeResponse(json_data=page1 if offset == 0 else page2)

    session = _api.FakeSession([("load.json", route)])
    ids = _api.api.MalApi(session).user_anime_ids("morr", ["completed"])
    assert len(ids) == 301                     # 300 + один со статусом 2
    assert 1000 not in ids                     # «запланировано» не просили
    assert len(session.calls) == 2             # вторая страница запрошена

test_mal_paginates_and_filters_statuses.__module__ = _api.__name__
_api.test_mal_paginates_and_filters_statuses = test_mal_paginates_and_filters_statuses

def test_mal_unknown_user_message():
    session = _api.FakeSession([("load.json", _api.FakeResponse(status_code=400))])
    with _api.pytest.raises(_api.api.AnimePackApiError) as e:
        _api.api.MalApi(session).user_anime_ids("нет-такого", ["completed"])
    assert "не найден" in str(e.value)

test_mal_unknown_user_message.__module__ = _api.__name__
_api.test_mal_unknown_user_message = test_mal_unknown_user_message

def test_shikimori_exact_nickname_lookup():
    """Точный поиск по нику вместо ?search= (тот отдавал чужой список)."""
    session = _api.FakeSession([
        ("/api/users/morr", _api.FakeResponse(json_data={"id": 1, "nickname": "morr"})),
        ("/api/v2/user_rates", _api.FakeResponse(json_data=[
            {"target_id": 5, "status": "completed"},
            {"target_id": 7, "status": "planned"},
        ])),
    ])
    shiki = _api.api.ShikimoriApi(session)
    assert shiki.user_anime_ids("morr", ["completed"]) == [5]
    users_call = next(c for c in session.calls if "/api/users/" in c[1])
    assert users_call[2]["params"]["is_nickname"] == 1

test_shikimori_exact_nickname_lookup.__module__ = _api.__name__
_api.test_shikimori_exact_nickname_lookup = test_shikimori_exact_nickname_lookup

def test_shikimori_ignores_paging_and_stops():
    """/api/v2/user_rates не умеет ни page, ни limit — отдаёт весь список
    заново на каждой странице. Раньше на этом цикл крутился бесконечно и
    набивал список копиями («получено 614… 1228… 1842…»)."""
    rates = [{"target_id": i, "status": "completed"}
             for i in range(_api.api.ShikimoriApi.PAGE + 19)]
    session = _api.FakeSession([
        ("/api/users/morr", _api.FakeResponse(json_data={"id": 1})),
        ("/api/v2/user_rates", lambda url, **kw: _api.FakeResponse(json_data=rates)),
    ])
    ids = _api.api.ShikimoriApi(session).user_anime_ids("morr", ["completed"])
    assert ids == list(range(_api.api.ShikimoriApi.PAGE + 19))   # без дублей
    # Один запрос за списком и один — убедиться, что нового не приехало.
    assert len([c for c in session.calls if "user_rates" in c[1]]) == 2

test_shikimori_ignores_paging_and_stops.__module__ = _api.__name__
_api.test_shikimori_ignores_paging_and_stops = test_shikimori_ignores_paging_and_stops

def test_shikimori_missing_user_raises():
    session = _api.FakeSession([("/api/users/", _api.FakeResponse(status_code=404))])
    with _api.pytest.raises(_api.api.AnimePackApiError):
        _api.api.ShikimoriApi(session).user_anime_ids("нет", ["completed"])

test_shikimori_missing_user_raises.__module__ = _api.__name__
_api.test_shikimori_missing_user_raises = test_shikimori_missing_user_raises

def test_amq_library_uses_cache(tmp_path):
    payload = {"masterListId": "x", "animeMap": {
        "1": {"annId": 1, "year": 1999}, "2": {"annId": 2, "year": None}}}
    # content нужен потому, что мастер-лист качается потоком (16 МБ, иначе
    # «Стоп» не срабатывает, пока файл не приедет целиком).
    session = _api.FakeSession([("libraryMasterList",
                            _api.FakeResponse(json_data=payload,
                                         content=_api.json.dumps(payload).encode()))])
    cache = str(tmp_path / "amq.json")
    amq = _api.api.AmqApi(session, cache_path=cache)
    assert amq.library() == {1: 1999, 2: None}
    assert _api.os.path.exists(cache)
    # Второй вызов не должен идти в сеть.
    amq2 = _api.api.AmqApi(session, cache_path=cache)
    assert amq2.library() == {1: 1999, 2: None}
    assert len(session.calls) == 1

test_amq_library_uses_cache.__module__ = _api.__name__
_api.test_amq_library_uses_cache = test_amq_library_uses_cache

# ── Отбор ────────────────────────────────────────────────────────────────────
def _generator(settings, songs, animes, **kw):
    """Генератор с подменёнными источниками (сети нет вовсе)."""
    class FakeAnisong:
        def songs_by_mal_ids(self, ids):
            return [s for s in songs
                    if (s.get("linked_ids") or {}).get("myanimelist") in ids]
        songs_by_ann_ids = songs_by_mal_ids

    class FakeShiki:
        def animes_by_ids(self, ids):
            ids = {int(i) for i in ids}
            return [a for a in animes if int(a["malId"]) in ids]

        def user_anime_ids(self, nick, statuses, **_kw):
            return kw.get("user_ids", {}).get(nick, [])

        def franchise_parts(self, keys):
            return kw.get("franchise_parts", {})

    class FakeMal:
        def user_anime_ids(self, nick, statuses, **_kw):
            return kw.get("user_ids", {}).get(nick, [])

    gen = _api.AnimePackGenerator(settings, session=object(), amq=object(),
                             anisong=FakeAnisong(), mal=FakeMal(),
                             shikimori=FakeShiki(), **{
                                 k: v for k, v in kw.items() if k != "user_ids"})
    return gen

_generator.__module__ = _api.__name__
_api._generator = _generator

def _pair(mal_id, franchise="fr", song_over=None, anime_over=None):
    song = _api.make_song(**{"linked_ids": {"myanimelist": mal_id},
                        "annSongId": mal_id * 10, **(song_over or {})})
    # Название у каждой франшизы своё: тайтлы с общим корнем имени генератор
    # считает частями одной серии и в один пак не пускает.
    anime = _api.make_anime(**{"malId": mal_id, "id": mal_id, "franchise": franchise,
                          "russian": f"Тетрадь смерти {franchise}",
                          **(anime_over or {})})
    return song, anime

_pair.__module__ = _api.__name__
_api._pair = _pair

def test_iter_candidates_dedups_anime_and_franchise():
    s = _api.PackSettings(random_mode=False, similar_count=1,
                     users=[_api.UserList("morr", "myanimelist", ["completed"])])
    s1, a1 = _api._pair(1, "naruto")
    s2, a2 = _api._pair(2, "naruto")                     # та же франшиза
    s3, a3 = _api._pair(3, "bleach")
    s1b = _api.make_song(linked_ids={"myanimelist": 1}, annSongId=11,
                    songType="Ending 1")            # второй сонг того же аниме
    gen = _api._generator(s, [s1, s1b, s2, s3], [a1, a2, a3],
                     user_ids={"morr": [1, 2, 3]})
    got = {c.mal_id for c in gen.iter_candidates()}
    assert got == {1, 3}                            # 2 отсеян как та же франшиза

    s.dup_franchise = True
    gen = _api._generator(s, [s1, s1b, s2, s3], [a1, a2, a3],
                     user_ids={"morr": [1, 2, 3]})
    assert {c.mal_id for c in gen.iter_candidates()} == {1, 2, 3}

test_iter_candidates_dedups_anime_and_franchise.__module__ = _api.__name__
_api.test_iter_candidates_dedups_anime_and_franchise = test_iter_candidates_dedups_anime_and_franchise

def test_similar_requires_several_users():
    s = _api.PackSettings(random_mode=False, similar_count=2,
                     users=[_api.UserList("a", "myanimelist", ["completed"]),
                            _api.UserList("b", "myanimelist", ["completed"])])
    s1, a1 = _api._pair(1, "one")
    s2, a2 = _api._pair(2, "two")
    gen = _api._generator(s, [s1, s2], [a1, a2],
                     user_ids={"a": [1, 2], "b": [2]})
    cands = list(gen.iter_candidates())
    assert [c.mal_id for c in cands] == [2]
    assert cands[0].users == ["a", "b"]

test_similar_requires_several_users.__module__ = _api.__name__
_api.test_similar_requires_several_users = test_similar_requires_several_users

def test_select_songs_replaces_failed_downloads(monkeypatch):
    """Песня, чьё медиа не скачалось, заменяется следующим кандидатом —
    в ASPG она оставалась в XML со ссылкой на несуществующий файл."""
    s = _api.PackSettings(rounds=1, themes=1, questions=2, openings=2, endings=0,
                     inserts=0, parallel=1, random_mode=False, similar_count=1,
                     users=[_api.UserList("morr", "myanimelist", ["completed"])])
    pairs = [_api._pair(i, f"fr{i}") for i in range(1, 6)]
    gen = _api._generator(s, [p[0] for p in pairs], [p[1] for p in pairs],
                     user_ids={"morr": [1, 2, 3, 4, 5]})
    failed = {1, 2}
    monkeypatch.setattr(gen, "_fetch_media",
                        lambda cand: cand.mal_id not in failed)
    songs = gen.select_songs()
    assert len(songs) == 2
    assert not ({c.mal_id for c in songs} & failed)

test_select_songs_replaces_failed_downloads.__module__ = _api.__name__
_api.test_select_songs_replaces_failed_downloads = test_select_songs_replaces_failed_downloads

def test_select_songs_respects_type_quotas(monkeypatch):
    s = _api.PackSettings(rounds=1, themes=1, questions=3, openings=1, endings=2,
                     inserts=0, parallel=1, random_mode=False, similar_count=1,
                     users=[_api.UserList("morr", "myanimelist", ["completed"])])
    songs, animes, ids = [], [], []
    for i in range(1, 9):
        kind = "Opening 1" if i <= 4 else "Ending 1"
        song, anime = _api._pair(i, f"fr{i}", song_over={"songType": kind})
        songs.append(song); animes.append(anime); ids.append(i)
    gen = _api._generator(s, songs, animes, user_ids={"morr": ids})
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: True)
    picked = gen.select_songs()
    kinds = [c.kind for c in picked]
    assert len(picked) == 3
    assert kinds.count("opening") == 1 and kinds.count("ending") == 2

test_select_songs_respects_type_quotas.__module__ = _api.__name__
_api.test_select_songs_respects_type_quotas = test_select_songs_respects_type_quotas
