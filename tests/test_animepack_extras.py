# -*- coding: utf-8 -*-
"""Генерация аниме-пака: доли списков, манга, средняя сложность и прочее.

Отдельный файл, чтобы не раздувать test_animepack.py: здесь всё, что появилось
вокруг настроек пака — доли между списками людей, пометка «в основном музыка»,
средняя узнаваемость, раздел манги/манхвы/ранобэ, первый тайтл франшизы у
вопроса-персонажа и раскладка времени по этапам.
"""
from collections import Counter

from animepack import (CHAR_KIND, FRAME_KIND, MANGA_KIND, AnimePackGenerator,
                       PackSettings, SongCandidate, UserList, filter_anime)
from test_animepack import make_anime, make_candidate


def _gen(settings, **kw):
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
                              shikimori=FakeShiki(), anilist=object(),
                              kitsu=object(), themes=object(), **kw)


def make_manga(**over):
    manga = {
        "id": 21, "malId": 21, "name": "Berserk", "russian": "Берсерк",
        "english": "Berserk", "synonyms": [], "licenseNameRu": "Берсерк",
        "franchise": "berserk", "score": 9.3, "kind": "manga",
        "genres": [{"id": "1", "name": "Action"}],
        "poster": {"originalUrl": "https://shiki/berserk.jpg"},
        "airedOn": {"year": 1989},
        "statusesStats": [{"status": "completed", "count": 5000}],
    }
    manga.update(over)
    return manga


# ── Доли списков ─────────────────────────────────────────────────────────────
def test_user_shares_interleave_lists_by_percent():
    """Список на 1500 тайтлов не должен забивать пак: доли раздают очередь.

    Смотрим начало очереди — при 70/30 в первых десяти id должно быть семь
    тайтлов «жирного» списка и три «худого»."""
    gen = _gen(PackSettings())
    seen = {i: ["big"] for i in range(1, 200)}
    seen.update({1000 + i: ["small"] for i in range(50)})
    order = gen._order_by_shares(seen, {"big": 70, "small": 30})
    first = [owners[0] for _aid, owners in order[:10]]
    assert first.count("big") == 7 and first.count("small") == 3
    # Ничего не потеряли и не задвоили.
    assert len(order) == len(seen)
    assert len({aid for aid, _ in order}) == len(seen)


def test_user_shares_off_means_plain_shuffle():
    """Без долей (все нули) порядок прежний — просто перемешанный."""
    gen = _gen(PackSettings())
    seen = {i: ["a"] for i in range(20)}
    order = gen._order_by_shares(seen, {"a": 0})
    assert sorted(aid for aid, _ in order) == sorted(seen)


def test_user_shares_do_not_lose_the_tail():
    """Короткий список кончился раньше — остаток длинного всё равно в очереди."""
    gen = _gen(PackSettings())
    seen = {i: ["big"] for i in range(100)}
    seen[500] = ["small"]
    order = gen._order_by_shares(seen, {"big": 50, "small": 50})
    assert len(order) == 101
    assert {aid for aid, _ in order} == set(seen)


# ── «В основном музыка» ─────────────────────────────────────────────────────
def test_prefer_music_keeps_the_list_on_songs():
    s = PackSettings(rounds=1, themes=1, questions=10, pct_songs=50,
                     pct_frames=50, users=[
                         UserList("m", "shikimori", ["completed"],
                                  prefer_music=True),
                         UserList("other", "shikimori", ["completed"])])
    gen = _gen(s)
    quotas = s.question_quotas
    counts, inflight = Counter(), Counter()
    music = make_candidate(); music.users = ["m"]
    plain = make_candidate(); plain.users = ["other"]
    # Опенингов набрано почти по квоте, кадров — ни одного: обычному кандидату
    # достаётся кадр (он сильнее отстаёт), а «музыкальному» — последнее
    # песенное место.
    counts["opening"] = quotas["opening"] - 1
    assert gen._pick_kind(plain, counts, inflight, quotas) == FRAME_KIND
    assert gen._pick_kind(music, counts, inflight, quotas) == "opening"
    # Песенные места кончились — тогда и «музыкальный» идёт в картинку.
    for kind in ("opening", "ending", "insert"):
        counts[kind] = quotas.get(kind, 0)
    assert gen._pick_kind(music, counts, inflight, quotas) == FRAME_KIND


# ── Средняя сложность ───────────────────────────────────────────────────────
def _cand_with_level(count):
    return make_candidate(anime={"statusesStats": [{"status": "completed",
                                                    "count": count}]})


def test_level_avg_pulls_the_pack_to_the_middle():
    gen = _gen(PackSettings(level_avg=4))
    easy = _cand_with_level(900000)
    hard = _cand_with_level(3)
    assert easy.level < 4 < hard.level
    # Средняя уехала вверх — трудные больше не проходят, лёгкие проходят.
    assert gen._level_fits(hard, [9, 9, 9]) is False
    assert gen._level_fits(easy, [9, 9, 9]) is True
    # И наоборот.
    assert gen._level_fits(easy, [1, 1, 1]) is False
    assert gen._level_fits(hard, [1, 1, 1]) is True
    # Первых вопросов проверка не касается, а без цели её нет вовсе.
    assert gen._level_fits(hard, [9]) is True
    assert _gen(PackSettings())._level_fits(hard, [9, 9, 9]) is True


def test_level_avg_gives_up_instead_of_starving_the_pack():
    """Клапан: если подходящих нет, вопросы всё же берутся."""
    gen = _gen(PackSettings(level_avg=4))
    hard = _cand_with_level(3)
    rejected = 0
    while not gen._level_fits(hard, [9, 9, 9]):
        rejected += 1
        assert rejected < 500
    assert rejected == gen.LEVEL_AVG_GIVE_UP


def test_level_avg_must_fit_the_range():
    assert any("Средняя сложность" in p for p in
               PackSettings(level_min=5, level_max=8, level_avg=2).validate())
    assert not any("Средняя сложность" in p for p in
                   PackSettings(level_min=1, level_max=10, level_avg=4).validate())


# ── Манга, манхва, ранобэ ───────────────────────────────────────────────────
def test_manga_share_gets_its_own_quota():
    s = PackSettings(rounds=1, themes=1, questions=10, pct_songs=50,
                     pack_manga=True, pct_manga=50)
    assert s.percents == (50, 0, 0, 0, 50)
    assert s.question_quotas[MANGA_KIND] == 5
    assert s.manga_percent == 50


def test_manga_share_needs_its_checkbox():
    """Без галочки «Вопрос — манга» её доли на ползунке нет вовсе."""
    s = PackSettings(rounds=1, themes=1, questions=10, pct_songs=50,
                     pct_manga=50)
    assert s.percents == (100, 0, 0, 0, 0)
    assert s.question_quotas[MANGA_KIND] == 0
    # Старые настройки (доля есть, галочки в файле нет) галочку включают сами.
    assert PackSettings.from_dict({"pct_manga": 50}).pack_manga is True
    assert PackSettings.from_dict({"pct_manga": 50,
                                   "pack_manga": False}).manga_percent == 0


def test_manga_filter_uses_its_own_kinds():
    s = PackSettings(manga_kinds={"manga": True, "light_novel": False})
    assert filter_anime(make_manga(), s, manga=True) is True
    assert filter_anime(make_manga(kind="light_novel"), s, manga=True) is False
    # Скриншотов у книги нет — требование коллажа на неё не распространяется.
    s.images = True
    assert filter_anime(make_manga(), s, manga=True) is True


def test_manga_candidates_come_from_manga_lists():
    s = PackSettings(rounds=1, themes=1, questions=2, pct_songs=0,
                     pct_manga=100, random_mode=False, similar_count=1,
                     users=[UserList("m", "shikimori", ["completed"],
                                     target="manga")])
    gen = _gen(s)
    # Названия нарочно разные: тайтлы с общим корнем имени считаются частями
    # одной серии и в пак вдвоём не пускаются.
    names = {21: "Берсерк", 22: "Ванпанчмен"}
    gen.shikimori.mangas_by_ids = lambda ids: [
        make_manga(malId=i, id=i, russian=names[i], franchise=f"f{i}")
        for i in ids]
    gen.shikimori.user_anime_ids = lambda nick, st, **kw: (
        [21, 22] if kw.get("target") == "manga" else [])
    cands = list(gen._iter_manga_candidates())
    assert [c.kind for c in cands] == [MANGA_KIND, MANGA_KIND]
    assert all(c.is_manga and c.is_picture for c in cands)
    assert {c.title_ru for c in cands} == {"Берсерк", "Ванпанчмен"}


def test_anime_lists_are_not_asked_for_manga():
    """Раздел списка решает, куда идёт ник: аниме-список манги не даёт."""
    s = PackSettings(random_mode=False, similar_count=1, users=[
        UserList("a", "shikimori", ["completed"], target="anime"),
        UserList("m", "shikimori", ["completed"], target="manga")])
    gen = _gen(s)
    assert [u.username for u in gen._user_lists("anime")] == ["a"]
    assert [u.username for u in gen._user_lists("manga")] == ["m"]


def test_manga_answer_is_a_character_when_asked_by_portrait():
    cand = SongCandidate(song={}, anime=make_manga(), kind=MANGA_KIND,
                         media="manga")
    assert cand.is_character is False        # обложка: персонажа нет
    cand.character = {"id": 3, "name": "Гатс", "names": ["Гатс", "Guts"]}
    assert cand.is_character is True
    assert cand.main_answer == "Берсерк (1989) — 『Гатс』"
    assert "Guts" in cand.answer_variants()


def test_manga_needs_a_manga_list_or_a_common_base():
    s = PackSettings(pct_songs=0, pack_manga=True, pct_manga=100,
                     random_mode=False, similar_count=1,
                     users=[UserList("m", "shikimori", ["completed"])])
    assert any("списков манги нет" in p for p in s.validate())
    s.users[0].target = "manga"
    assert not any("списков манги нет" in p for p in s.validate())


def test_manga_kinds_must_not_be_all_off():
    s = PackSettings(pct_songs=0, pack_manga=True, pct_manga=100,
                     manga_kinds={k: False for k in ("manga", "manhwa")})
    assert any("не выбран ни один её тип" in p for p in s.validate())


# ── Первый тайтл франшизы у вопроса-персонажа ───────────────────────────────
def test_character_answer_uses_the_earliest_title():
    """Персонажа вытащили из сиквела — отвечаем по самому первому тайтлу."""
    gen = _gen(PackSettings(pct_songs=0, pct_chars=100))
    cand = make_candidate(anime={"malId": 999, "id": 999,
                                 "russian": "Наруто: Ураганные хроники"})
    cand.kind = CHAR_KIND
    cand.character = {"id": 17, "name": "Наруто Удзумаки"}
    gen.shikimori.character_titles = lambda cid: {
        "animes": [
            {"id": 999, "aired_on": "2007-02-15"},
            {"id": 20, "aired_on": "2002-10-03"},
            {"id": 30, "aired_on": ""},          # анонс без даты — не в счёт
        ],
        "mangas": []}
    gen.shikimori.animes_by_ids = lambda ids: [
        make_anime(malId=20, id=20, russian="Наруто")]
    gen._use_first_title(cand)
    assert cand.mal_id == 20
    assert cand.main_answer.startswith("Наруто (")


def test_character_answer_keeps_the_title_when_nothing_earlier():
    gen = _gen(PackSettings())
    cand = make_candidate()
    cand.kind = CHAR_KIND
    cand.character = {"id": 17, "name": "Лайт"}
    gen.shikimori.character_titles = lambda cid: {
        "animes": [{"id": 1535, "aired_on": "2006-10-04"}], "mangas": []}
    gen._use_first_title(cand)
    assert cand.mal_id == 1535
    # Пустой ответ сервера тоже ничего не ломает.
    gen.shikimori.character_titles = lambda cid: {}
    gen._use_first_title(cand)
    assert cand.mal_id == 1535


# ── Время по этапам и мелочи настроек ───────────────────────────────────────
def test_stage_times_are_logged():
    lines = []
    gen = _gen(PackSettings(parallel=4), log=lines.append)
    with gen._timed("аудио"):
        pass
    with gen._timed("картинки"):
        pass
    with gen._timed("аудио"):
        pass
    gen.log_stage_times(10.0)
    text = "\n".join(lines)
    assert "Время по этапам" in text
    assert "аудио" in text and "картинки" in text
    # Порядок — по первому появлению, а не по алфавиту.
    assert text.index("аудио") < text.index("картинки")
    # Один и тот же этап не задваивается, а складывается.
    assert sum("аудио" in line for line in lines) == 1


def test_stage_percent_counts_wall_clock_not_thread_seconds():
    """Восемь картинок, качавшихся одновременно, — это не 487% времени пака.

    Отрезки этапа склеиваются: сколько времени на часах этап шёл хоть в одном
    потоке. Сумма по потокам остаётся в скобках — по ней видно загрузку."""
    merge = AnimePackGenerator._merge_spans
    # Четыре потока по 10 секунд, все внахлёст — это 10 секунд работы.
    assert merge([(0.0, 10.0)] * 4) == 10.0
    # Разнесённые отрезки складываются, соприкасающиеся — склеиваются.
    assert merge([(0.0, 2.0), (5.0, 6.0)]) == 3.0
    assert merge([(0.0, 2.0), (1.0, 5.0)]) == 5.0
    assert merge([]) == 0.0

    lines = []
    gen = _gen(PackSettings(parallel=8), log=lines.append)
    with gen._stage_lock:
        gen._stage_spans["картинки"] = [(0.0, 60.0)] * 8 + [(60.0, 90.0)]
        gen._stage_order.append("картинки")
    gen.log_stage_times(180.0)
    row = next(l for l in lines if "картинки" in l)
    # 90 секунд по часам из 180 — это половина, а не 267%.
    assert "50%" in row
    assert "8 потоков суммарно" in row


def test_user_list_roundtrip_keeps_target_share_and_music():
    u = UserList("m", "anilist", ["completed"], target="manga", share=40,
                 prefer_music=True)
    back = UserList.from_dict(u.to_dict())
    assert (back.target, back.share, back.prefer_music) == ("manga", 40, True)
    # Мусор в разделе и доле чинится молча.
    bad = UserList.from_dict({"username": "m", "target": "фигня", "share": 500})
    assert (bad.target, bad.share) == ("anime", 100)


def test_duplicates_are_always_off():
    """Галочек «Дубли аниме/франшиз» больше нет — и включить их неоткуда."""
    s = PackSettings.from_dict({"dup_anime": True, "dup_franchise": True})
    assert s.dup_anime is False and s.dup_franchise is False


def test_streams_are_merged_by_their_weights():
    """Аниме и манга идут вперемешку, а не «сначала одно, потом другое»."""
    a = iter(["a"] * 10)
    m = iter(["m"] * 10)
    out = list(AnimePackGenerator._merge_streams([(a, 3), (m, 1)]))[:8]
    assert out.count("a") == 6 and out.count("m") == 2
    # Иссякший поток просто выпадает из очереди.
    out = list(AnimePackGenerator._merge_streams([(iter(["a"]), 1),
                                                 (iter(["m", "m"]), 1)]))
    assert out.count("m") == 2 and out.count("a") == 1
