"""Вкладка «Генерация аниме-пака»: фильтры, сборка content.xml и сеть.

Сеть везде подменяется FakeSession из conftest — ни один тест наружу не ходит.
Отдельно закреплены места, где оригинальный ASPG ошибался: snake_case в теле
запроса к AnisongDB, булевы isDub/isRebroadcast, пагинация списков, замена
песни с несостоявшейся загрузкой, формат длительности, дедуп по аниме.
"""
import json
import os

import pytest

from conftest import FakeResponse, FakeSession

import animepack
import animepack_api as api
from animepack import (
    PackSettings,
    UserList,
    arrange_questions,
    build_content_xml,
    filter_anime,
    filter_song,
    fmt_duration,
    fmt_elapsed,
    franchise_key,
    price_for_difficulty,
    song_kind,
)
from animepack_test_helpers import _forget_user_lists  # noqa: F401 — autouse-фикстура
from animepack_test_helpers import _generator, _pair, _parse, make_anime, make_candidate, make_song


# ── Чистые функции ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("difficulty,price", [
    (100, 6), (90, 6), (89.9, 8), (75, 9), (55, 12), (10, 18), (0, 20), (-1, 1),
    (None, 1), ("нет", 1),
])
def test_price_for_difficulty(difficulty, price):
    assert price_for_difficulty(difficulty) == price

def test_fmt_duration_pads_and_clamps():
    # ASPG склеивал строку руками и выдавал «00:00:3»; отрицательное время
    # получалось, когда картинки просили больше секунд, чем длится отрезок.
    assert fmt_duration(3) == "00:00:03"
    assert fmt_duration(65) == "00:01:05"
    assert fmt_duration(0) == "00:00:01"
    assert fmt_duration(-7) == "00:00:01"
    assert fmt_duration(None) == "00:00:01"

def test_song_kind():
    assert song_kind("Opening 1") == "opening"
    assert song_kind("Ending 12") == "ending"
    assert song_kind("Insert Song") == "insert"
    assert song_kind("Что-то") is None

def test_filter_song_defaults_pass():
    assert filter_song(make_song(), PackSettings()) is True

def test_filter_song_bool_dub_and_rebroadcast():
    """AnisongDB перешёл на true/false: сравнение с 1 (как в ASPG) не работало."""
    s = PackSettings()
    s.allow_dub = False
    assert filter_song(make_song(isDub=True), s) is False
    assert filter_song(make_song(isDub=1), s) is False
    s.allow_dub = True
    assert filter_song(make_song(isDub=True), s) is True

    s = PackSettings()
    s.allow_rebroadcast = False
    assert filter_song(make_song(isRebroadcast=True), s) is False
    s.allow_rebroadcast = True
    assert filter_song(make_song(isRebroadcast=True), s) is True

def test_filter_song_category_and_difficulty():
    s = PackSettings()
    s.categories = dict(s.categories, standard=False)
    assert filter_song(make_song(), s) is False
    s = PackSettings()
    s.difficulty_min, s.difficulty_max = 0, 50
    assert filter_song(make_song(songDifficulty=85.0), s) is False
    assert filter_song(make_song(songDifficulty=40.0), s) is True

def test_filter_song_requires_media_fields():
    s = PackSettings()
    assert filter_song(make_song(audio=None), s) is False
    assert filter_song(make_song(songLength=None), s) is False
    assert filter_song(make_song(songType="Ерунда"), s) is False
    assert filter_song(make_song(linked_ids={}), s) is False
    assert filter_song(make_song(songDifficulty=None), s) is False

def test_filter_anime_ranges():
    s = PackSettings()
    assert filter_anime(make_anime(), s) is True
    assert filter_anime(make_anime(kind="music"), s) is False
    assert filter_anime(make_anime(airedOn={"year": 1900}), s) is False
    s2 = PackSettings(); s2.score_from = 9.0
    assert filter_anime(make_anime(), s2) is False
    assert filter_anime(make_anime(poster={}), s) is False
    assert filter_anime(make_anime(malId=None), s) is False

def test_filter_anime_screenshots_only_when_images_needed():
    """Скриншоты нужны только под коллаж; ASPG требовал их всегда."""
    s = PackSettings()
    assert filter_anime(make_anime(screenshots=[]), s) is True
    s.images = True
    assert filter_anime(make_anime(screenshots=[]), s) is False
    assert filter_anime(make_anime(), s) is True

def test_filter_anime_genres_include_exclude():
    s = PackSettings()
    s.genres_exclude = [40]
    assert filter_anime(make_anime(), s) is False
    s = PackSettings()
    s.genres_include = [27, 999]
    s.genres_partial = True
    assert filter_anime(make_anime(), s) is True
    s.genres_partial = False           # нужны ВСЕ выбранные
    assert filter_anime(make_anime(), s) is False

def test_franchise_key_unique_for_empty():
    a = make_anime(franchise="", malId=1)
    b = make_anime(franchise="", malId=2)
    assert franchise_key(a) != franchise_key(b)
    assert franchise_key(make_anime()) == "death_note"

def test_song_kinds_are_a_ratio_not_a_count():
    """Опенинги/эндинги/OST — это ДОЛИ (ползунок), а не штуки: сколько бы ни
    стояло в них, они ужимаются под число песенных вопросов, и «распределите
    ещё N» больше не бывает."""
    s = PackSettings(rounds=1, themes=1, questions=10)
    s.openings, s.endings, s.inserts = 10, 0, 0
    assert not any("распределите" in p for p in s.validate())
    assert s.question_quotas["opening"] == 10
    s.openings, s.endings, s.inserts = 50, 30, 20
    q = s.question_quotas
    assert (q["opening"], q["ending"], q["insert"]) == (5, 3, 2)

def test_validate_images_longer_than_cut():
    s = PackSettings(images=True, images_time=25, audio_cut=20)
    assert any("раньше, чем кончится песня" in p for p in s.validate())

def test_settings_roundtrip():
    s = PackSettings(title="Мой пак", rounds=2, images=True,
                     users=[UserList("morr", "shikimori", ["completed"])],
                     genres_include=[1, 2])
    back = PackSettings.from_dict(s.to_dict())
    assert back.title == "Мой пак"
    assert back.rounds == 2 and back.images is True
    assert back.users[0].username == "morr"
    assert back.users[0].source == "shikimori"
    assert back.genres_include == [1, 2]

def test_build_content_xml_structure():
    s = PackSettings(rounds=1, themes=1, questions=2, openings=2, endings=0, inserts=0)
    # Тайтл у обоих один и тот же, поэтому база цены одинаковая, а расходятся
    # они ровно надбавкой за сложность AMQ: у лёгкой песни её нет, у трудной —
    # все десять очков.
    easy = make_candidate(song={"songDifficulty": 95.0})
    hard = make_candidate(song={"songDifficulty": 5.0, "annSongId": 9})
    easy.has_poster = hard.has_poster = True
    root, ns = _parse(build_content_xml([hard, easy], s))

    assert root.get("version") == "5"
    # Название заканчивается средней сложностью пака: «… (Ур. 4)».
    assert root.get("name").startswith(s.title + " (Ур. ")
    assert root.get("id") and root.get("date")
    questions = root.findall(".//s:question", ns)
    assert len(questions) == 2
    # Внутри темы вопросы идут по возрастанию цены (в ASPG порядок был случайный).
    base = animepack.price_for_level(easy.level)
    assert [q.get("price") for q in questions] == [str(base), str(base + 10)]

    audio = questions[0].find(".//s:item[@type='audio']", ns)
    # В пак кладётся opus, а не исходный mp3 с CDN.
    assert audio.text == "7868.opus"
    assert audio.get("isRef") == "True"
    assert audio.get("placement") == "background"
    # Таймера у дорожки нет вовсе: отрезок доигрывает сам (просьба
    # пользователя). Раньше здесь стояло duration="00:00:20".
    assert audio.get("duration") is None
    poster = questions[0].find(".//s:param[@name='answer']/s:item[@type='image']", ns)
    assert poster.text.endswith("_poster.avif")

def test_build_content_xml_images_and_hint():
    s = PackSettings(rounds=1, themes=1, questions=1, images=True, images_time=7,
                     audio_cut=20, hint=True)
    cand = make_candidate()
    cand.has_collage = True
    root, ns = _parse(build_content_xml([cand], s))
    audio = root.find(".//s:item[@type='audio']", ns)
    assert audio.get("duration") is None             # таймера у дорожки нет
    img = root.find(".//s:param[@name='question']/s:item[@type='image']", ns)
    assert img is not None and img.get("duration") == "00:00:07"
    texts = [i.text for i in root.findall(".//s:param[@name='question']/s:item", ns)]
    assert "Опенинг" in texts

def test_build_content_xml_skips_missing_media():
    """Коллаж/постер не скачались — ссылок на них в XML быть не должно."""
    s = PackSettings(rounds=1, themes=1, questions=1, images=True)
    cand = make_candidate()          # has_poster / has_collage = False
    root, ns = _parse(build_content_xml([cand], s))
    assert root.find(".//s:item[@type='image']", ns) is None
    audio = root.find(".//s:item[@type='audio']", ns)
    assert audio.get("duration") is None

def test_build_content_xml_answer_text():
    """Основной ответ — «Название (год) — 『Песня』», дальше идут синонимы."""
    s = PackSettings(rounds=1, themes=1, questions=1)
    cand = make_candidate(users=["morr", "kao"])
    root, ns = _parse(build_content_xml([cand], s))
    answers = [a.text for a in root.findall(".//s:right/s:answer", ns)]
    assert answers[0] == "Тетрадь смерти OP1 (2006) — 『the WORLD』"
    # Голое название, ромадзи, английское и синонимы — тоже верные.
    assert "Тетрадь смерти" in answers and "Death Note" in answers
    assert "DN" in answers
    # Иероглифы в ответы не идут вовсе.
    assert "デスノート" not in answers
    assert not any(a for a in answers if "デ" in a)
    # «Тетрадь смерти» и licenseNameRu совпали — дубля быть не должно.
    assert answers.count("Тетрадь смерти") == 1
    # В реплике сперва исполнитель, потом голые никнеймы — и в паке по спискам
    # тоже (просьба пользователя: никаких «Есть у»).
    replics = root.findall(".//s:param[@name='answer']/s:item[@placement='replic']", ns)
    assert [r.text for r in replics] == [
        "Исполнитель — 『Nightmare』 · Сложность AMQ — 85 · Рейтинг MAL — 『8.60⭐』 · morr, kao"]

def test_answer_replic_is_artist_without_lists():
    """Без списков людей реплика ведущего — исполнитель песни."""
    s = PackSettings(rounds=1, themes=1, questions=1)
    root, ns = _parse(build_content_xml([make_candidate()], s))
    replics = root.findall(".//s:param[@name='answer']/s:item[@placement='replic']", ns)
    assert [r.text for r in replics] == [
        "Исполнитель — 『Nightmare』 · Сложность AMQ — 85 · Рейтинг MAL — 『8.60⭐』"]

def test_answer_year_not_doubled():
    """Shikimori держит год прямо в названии части тайтлов — второй раз его
    дописывать нельзя."""
    cand = make_candidate(anime={"russian": "Могучий Атом (2003)",
                                 "airedOn": {"year": 2003}})
    assert cand.main_answer == "Могучий Атом OP1 (2003) — 『the WORLD』"

def test_answer_without_song_is_just_title():
    cand = make_candidate(song={"songName": ""})
    assert cand.main_answer == "Тетрадь смерти OP1 (2006)"

def test_answer_content_has_no_text_block():
    """На экране в ответе только постер: подпись-плашка больше не рисуется, а
    исполнитель уходит в реплику ведущего (как в паках пользователя)."""
    s = PackSettings(rounds=1, themes=1, questions=1)
    cand = make_candidate()
    cand.has_poster = True
    root, ns = _parse(build_content_xml([cand], s))
    items = root.findall(".//s:param[@name='answer']/s:item", ns)
    assert [i.get("type") or i.get("placement") for i in items] == ["replic", "image"]
    assert items[0].text == (
        "Исполнитель — 『Nightmare』 · Сложность AMQ — 85 · Рейтинг MAL — 『8.60⭐』")


# ── Прочее ───────────────────────────────────────────────────────────────────
def test_fmt_elapsed():
    assert fmt_elapsed(48) == "48 с"
    assert fmt_elapsed(200) == "3 мин 20 с"
    assert fmt_elapsed(180) == "3 мин"
    assert fmt_elapsed(3900) == "1 ч 5 мин"
    assert fmt_elapsed(None) == "0 с"

def test_similar_count_one_is_allowed():
    """Минимум «у 1 человека» — законная настройка, а не ошибка."""
    s = PackSettings(random_mode=False, similar_count=1,
                     users=[UserList("morr", "shikimori", ["completed"])])
    assert not any("Похожие" in p for p in s.validate())


def test_sort_by_index_orders_pack_and_prices():
    """Порядок — по узнаваемости, цена — узнаваемость плюс сложность AMQ."""
    s = PackSettings(rounds=1, themes=3, questions=1, sort_by_index=True)
    hot = make_candidate(song={"annSongId": 1, "songDifficulty": 5.0},
                         anime={"malId": 1, "airedOn": {"year": 2024},
                                "statusesStats": [{"status": "completed",
                                                   "count": 100000}]})
    mid = make_candidate(song={"annSongId": 2, "songDifficulty": 95.0},
                         anime={"malId": 2, "airedOn": {"year": 2010},
                                "statusesStats": [{"status": "completed",
                                                   "count": 5000}]})
    cold = make_candidate(song={"annSongId": 3, "songDifficulty": 50.0},
                          anime={"malId": 3, "airedOn": {"year": 1998},
                                 "statusesStats": []})
    themes = arrange_questions([mid, cold, hot], s)
    # Пак идёт от самых узнаваемых тайтлов к самым безвестным.
    assert [t[0].mal_id for t in themes] == [1, 2, 3]
    # База — место по индексу (6 / 12 / 20), сверху надбавка за сложность
    # самой песни: почти неугадываемая (5) даёт все десять очков, лёгкая (95) —
    # ничего, средняя (50) — половину.
    assert [t[0].price for t in themes] == [16, 12, 25]

    # Без сортировки по индексу цены те же — база у них общая, — а вопросы в
    # теме идут по возрастанию цены.
    s = PackSettings(rounds=1, themes=1, questions=3)
    theme = arrange_questions([mid, cold, hot], s)[0]
    assert [c.price for c in theme] == [12, 16, 25]

def test_build_content_xml_stops_when_songs_run_out():
    s = PackSettings(rounds=3, themes=5, questions=6)
    root, ns = _parse(build_content_xml([make_candidate()], s))
    assert len(root.findall(".//s:round", ns)) == 1
    assert len(root.findall(".//s:question", ns)) == 1

# ── Сетевой слой ─────────────────────────────────────────────────────────────
def test_anisong_uses_snake_case_body():
    """ASPG слал malIds — сервер отвечал пустым списком."""
    session = FakeSession([("mal_ids_request", FakeResponse(json_data=[{"a": 1}]))])
    anisong = api.AnisongApi(session)
    assert anisong.songs_by_mal_ids([1535]) == [{"a": 1}]
    _method, _url, kw = session.calls[-1]
    assert kw["json"] == {"mal_ids": [1535]}

    session = FakeSession([("ann_ids_request", FakeResponse(json_data=[]))])
    api.AnisongApi(session).songs_by_ann_ids([1, 2])
    assert session.calls[-1][2]["json"] == {"ann_ids": [1, 2]}

def test_anisong_empty_ids_makes_no_request():
    session = FakeSession()
    assert api.AnisongApi(session).songs_by_mal_ids([]) == []
    assert session.calls == []

def test_mal_paginates_and_filters_statuses():
    page1 = [{"anime_id": i, "status": 2} for i in range(300)]
    page2 = [{"anime_id": 1000, "status": 6}, {"anime_id": 1001, "status": 2}]

    def route(url, **kw):
        offset = kw.get("params", {}).get("offset", 0)
        return FakeResponse(json_data=page1 if offset == 0 else page2)

    session = FakeSession([("load.json", route)])
    ids = api.MalApi(session).user_anime_ids("morr", ["completed"])
    assert len(ids) == 301                     # 300 + один со статусом 2
    assert 1000 not in ids                     # «запланировано» не просили
    assert len(session.calls) == 2             # вторая страница запрошена

def test_mal_unknown_user_message():
    session = FakeSession([("load.json", FakeResponse(status_code=400))])
    with pytest.raises(api.AnimePackApiError) as e:
        api.MalApi(session).user_anime_ids("нет-такого", ["completed"])
    assert "не найден" in str(e.value)

def test_shikimori_exact_nickname_lookup():
    """Точный поиск по нику вместо ?search= (тот отдавал чужой список)."""
    session = FakeSession([
        ("/api/users/morr", FakeResponse(json_data={"id": 1, "nickname": "morr"})),
        ("/api/v2/user_rates", FakeResponse(json_data=[
            {"target_id": 5, "status": "completed"},
            {"target_id": 7, "status": "planned"},
        ])),
    ])
    shiki = api.ShikimoriApi(session)
    assert shiki.user_anime_ids("morr", ["completed"]) == [5]
    users_call = next(c for c in session.calls if "/api/users/" in c[1])
    assert users_call[2]["params"]["is_nickname"] == 1

def test_shikimori_ignores_paging_and_stops():
    """/api/v2/user_rates не умеет ни page, ни limit — отдаёт весь список
    заново на каждой странице. Раньше на этом цикл крутился бесконечно и
    набивал список копиями («получено 614… 1228… 1842…»)."""
    rates = [{"target_id": i, "status": "completed"}
             for i in range(api.ShikimoriApi.PAGE + 19)]
    session = FakeSession([
        ("/api/users/morr", FakeResponse(json_data={"id": 1})),
        ("/api/v2/user_rates", lambda url, **kw: FakeResponse(json_data=rates)),
    ])
    ids = api.ShikimoriApi(session).user_anime_ids("morr", ["completed"])
    assert ids == list(range(api.ShikimoriApi.PAGE + 19))   # без дублей
    # Один запрос за списком и один — убедиться, что нового не приехало.
    assert len([c for c in session.calls if "user_rates" in c[1]]) == 2

def test_shikimori_missing_user_raises():
    session = FakeSession([("/api/users/", FakeResponse(status_code=404))])
    with pytest.raises(api.AnimePackApiError):
        api.ShikimoriApi(session).user_anime_ids("нет", ["completed"])

def test_amq_library_uses_cache(tmp_path):
    payload = {"masterListId": "x", "animeMap": {
        "1": {"annId": 1, "year": 1999}, "2": {"annId": 2, "year": None}}}
    # content нужен потому, что мастер-лист качается потоком (16 МБ, иначе
    # «Стоп» не срабатывает, пока файл не приедет целиком).
    session = FakeSession([("libraryMasterList",
                            FakeResponse(json_data=payload,
                                         content=json.dumps(payload).encode()))])
    cache = str(tmp_path / "amq.json")
    amq = api.AmqApi(session, cache_path=cache)
    assert amq.library() == {1: 1999, 2: None}
    assert os.path.exists(cache)
    # Второй вызов не должен идти в сеть.
    amq2 = api.AmqApi(session, cache_path=cache)
    assert amq2.library() == {1: 1999, 2: None}
    assert len(session.calls) == 1

def test_iter_candidates_dedups_anime_and_franchise():
    s = PackSettings(random_mode=False, similar_count=1,
                     users=[UserList("morr", "myanimelist", ["completed"])])
    s1, a1 = _pair(1, "naruto")
    s2, a2 = _pair(2, "naruto")                     # та же франшиза
    s3, a3 = _pair(3, "bleach")
    s1b = make_song(linked_ids={"myanimelist": 1}, annSongId=11,
                    songType="Ending 1")            # второй сонг того же аниме
    gen = _generator(s, [s1, s1b, s2, s3], [a1, a2, a3],
                     user_ids={"morr": [1, 2, 3]})
    got = {c.mal_id for c in gen.iter_candidates()}
    assert got == {1, 3}                            # 2 отсеян как та же франшиза

    s.dup_franchise = True
    gen = _generator(s, [s1, s1b, s2, s3], [a1, a2, a3],
                     user_ids={"morr": [1, 2, 3]})
    assert {c.mal_id for c in gen.iter_candidates()} == {1, 2, 3}

def test_similar_requires_several_users():
    s = PackSettings(random_mode=False, similar_count=2,
                     users=[UserList("a", "myanimelist", ["completed"]),
                            UserList("b", "myanimelist", ["completed"])])
    s1, a1 = _pair(1, "one")
    s2, a2 = _pair(2, "two")
    gen = _generator(s, [s1, s2], [a1, a2],
                     user_ids={"a": [1, 2], "b": [2]})
    cands = list(gen.iter_candidates())
    assert [c.mal_id for c in cands] == [2]
    assert cands[0].users == ["a", "b"]

def test_select_songs_replaces_failed_downloads(monkeypatch):
    """Песня, чьё медиа не скачалось, заменяется следующим кандидатом —
    в ASPG она оставалась в XML со ссылкой на несуществующий файл."""
    s = PackSettings(rounds=1, themes=1, questions=2, openings=2, endings=0,
                     inserts=0, parallel=1, random_mode=False, similar_count=1,
                     users=[UserList("morr", "myanimelist", ["completed"])])
    pairs = [_pair(i, f"fr{i}") for i in range(1, 6)]
    gen = _generator(s, [p[0] for p in pairs], [p[1] for p in pairs],
                     user_ids={"morr": [1, 2, 3, 4, 5]})
    failed = {1, 2}
    monkeypatch.setattr(gen, "_fetch_media",
                        lambda cand: cand.mal_id not in failed)
    songs = gen.select_songs()
    assert len(songs) == 2
    assert not ({c.mal_id for c in songs} & failed)

def test_select_songs_respects_type_quotas(monkeypatch):
    s = PackSettings(rounds=1, themes=1, questions=3, openings=1, endings=2,
                     inserts=0, parallel=1, random_mode=False, similar_count=1,
                     users=[UserList("morr", "myanimelist", ["completed"])])
    songs, animes, ids = [], [], []
    for i in range(1, 9):
        kind = "Opening 1" if i <= 4 else "Ending 1"
        song, anime = _pair(i, f"fr{i}", song_over={"songType": kind})
        songs.append(song); animes.append(anime); ids.append(i)
    gen = _generator(s, songs, animes, user_ids={"morr": ids})
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: True)
    picked = gen.select_songs()
    kinds = [c.kind for c in picked]
    assert len(picked) == 3
    assert kinds.count("opening") == 1 and kinds.count("ending") == 2
