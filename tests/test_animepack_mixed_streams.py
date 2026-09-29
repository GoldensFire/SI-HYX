# -*- coding: utf-8 -*-
"""Смешанный пак: песня нужна ПЕСЕННЫМ вопросам, а не всему каталогу.

Живой случай: пак из 144 вопросов с ненулевой долей песен набрал 116. В кэше
Shikimori лежало 12 811 аниме, все они ушли в AnisongDB, и до отбора добрались
849 — остальные 11 962 не рассматривались даже под кадр, персонажа или сюжет,
хотя в активный диапазон сложности попадали 4 520 тайтлов.

Сети тут нет: AnisongDB и Shikimori подменяются заглушками, медиа не качается.
"""
import collections
import random

import pytest

import animepack
from animepack import (CHAR_KIND, FRAME_KIND, SONG_KINDS, PackSettings,
                       SongCandidate)

from test_animepack_new_kinds import make_anime as _make_anime


# Корень названия — вторая линия обороны против повторов франшизы, и у
# «Тайтл 1» с «Тайтл 2» он один и тот же («тайтл»). Поэтому имена здесь и
# правда разные словами, а не номером.
_ALPHA = "абвгдежзиклмнопрстуфхцчшщэюя"


def _name(mal):
    return "Кино" + _ALPHA[mal % len(_ALPHA)] + _ALPHA[mal // len(_ALPHA) % len(_ALPHA)]


def make_anime(mal, **over):
    """Карточка Shikimori с собственными id, франшизой и названием."""
    card = {"id": mal, "malId": mal, "franchise": f"fr{mal}",
            "russian": _name(mal), "name": _name(mal), "english": _name(mal)}
    card.update(over)
    return _make_anime(**card)


def make_song(mal, difficulty=50.0):
    return {"songType": "Opening 1", "songName": f"song{mal}",
            "songArtist": "artist", "songDifficulty": difficulty,
            "audio": f"https://cdn/{mal}.mp3", "songLength": 90,
            "songCategory": "standard", "animeType": "TV",
            "linked_ids": {"myanimelist": mal}}


class FakeAnisong:
    """AnisongDB, который знает песни только у части тайтлов."""

    def __init__(self, songs):
        self.songs = list(songs)
        self.asked = []

    def songs_by_mal_ids(self, ids):
        self.asked.append(list(ids))
        want = set(int(i) for i in ids)
        return [s for s in self.songs
                if int(s["linked_ids"]["myanimelist"]) in want]


def _generator(tmp_path, monkeypatch, cards, songs, **over):
    """Генератор с подменённым каталогом: ни одного запроса в сеть."""
    monkeypatch.setattr(animepack, "CONFIG_DIR", str(tmp_path))
    settings = PackSettings(**{
        "pct_songs": 50, "pct_frames": 50, "pct_chars": 0,
        "rounds": 1, "themes": 1, "questions": 4, "parallel": 2,
        "openings": 1, "endings": 0, "inserts": 0,
        "pick_endings": False, "pick_inserts": False,
        "images": False, **over})
    gen = animepack.AnimePackGenerator(
        settings, session=object(), amq=object(),
        anisong=FakeAnisong(songs), shikimori=object(), mal=object(),
        tmdb=object(), rng=random.Random(7))
    by_id = {int(c["malId"]): c for c in cards}
    monkeypatch.setattr(gen, "collect_anime_ids",
                        lambda: [(i, []) for i in sorted(by_id)])
    monkeypatch.setattr(gen, "_animes_by_ids",
                        lambda ids: [by_id[int(i)] for i in ids if int(i) in by_id])
    monkeypatch.setattr(gen, "_load_franchise_indexes", lambda animes: None)
    monkeypatch.setattr(gen, "_franchise_index", lambda anime: 0.0)
    return gen


# ── Разделение потоков ──────────────────────────────────────────────────────
def test_a_title_without_a_song_still_becomes_a_frame(tmp_path, monkeypatch):
    """Главный баг: тайтл без подходящей песни годится в кадр.

    Песня есть ровно у одного тайтла из четырёх. Раньше кадры брались из тех
    же 849 «песенных» карточек, а остальные 11 962 не рассматривались вовсе."""
    cards = [make_anime(i) for i in (1, 2, 3, 4)]
    gen = _generator(tmp_path, monkeypatch, cards, [make_song(1)],
                     pct_songs=25, pct_frames=75)
    assert gen.s.question_quotas[FRAME_KIND] == 3
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: True)
    picked = gen.select_songs()
    kinds = collections.Counter(c.kind for c in picked)
    assert kinds == {"opening": 1, FRAME_KIND: 3}, f"набрано {kinds}"
    # Кадры собраны из тайтлов, которых в AnisongDB нет вовсе. Раньше их не
    # видел никто: пачка уходила в AnisongDB, и оттуда возвращался один тайтл.
    assert {c.mal_id for c in picked if c.kind == FRAME_KIND} == {2, 3, 4}


def test_a_song_question_is_still_made_only_from_a_filtered_song(
        tmp_path, monkeypatch):
    """Песенный вопрос по-прежнему берётся только из прошедшей filter_song.

    У второго тайтла песня есть, но её сложность AMQ вне рамки — в песенные
    вопросы он не годится, а в кадры годится."""
    cards = [make_anime(i) for i in (1, 2)]
    songs = [make_song(1, difficulty=50.0), make_song(2, difficulty=99.0)]
    gen = _generator(tmp_path, monkeypatch, cards, songs,
                     difficulty_min=0, difficulty_max=80, questions=2)
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: True)
    picked = gen.select_songs()
    by_kind = {c.kind: c for c in picked}
    assert set(by_kind) == {"opening", FRAME_KIND}
    assert by_kind["opening"].mal_id == 1
    assert by_kind["opening"].song["songName"] == "song1"
    assert by_kind[FRAME_KIND].mal_id == 2
    # У вопроса-кадра песни нет вовсе — её и не должно быть.
    assert by_kind[FRAME_KIND].song == {}


def test_both_streams_work_at_once_not_only_without_songs(
        tmp_path, monkeypatch):
    """Непесенный поток живёт и при songs_percent > 0.

    Раньше он заводился только в паке без единой песни."""
    cards = [make_anime(i) for i in range(1, 7)]
    gen = _generator(tmp_path, monkeypatch, cards, [make_song(1)])
    assert gen.s.songs_percent > 0
    streams = list(gen.iter_candidates())
    assert any(c.song for c in streams), "песенных кандидатов нет"
    assert any(not c.song for c in streams), "непесенных кандидатов нет"
    # Каталог разобран ОДИН раз: повторной загрузки тех же карточек нет.
    assert len(gen.anisong.asked) == 1
    assert sum(len(batch) for batch in gen.anisong.asked) == len(cards)


def test_the_catalogue_is_walked_once_for_both_streams(tmp_path, monkeypatch):
    """Одна карточка — один разбор: кандидатов ровно столько, сколько тайтлов."""
    cards = [make_anime(i) for i in range(1, 21)]
    gen = _generator(tmp_path, monkeypatch, cards,
                     [make_song(i) for i in (1, 2, 3)])
    got = list(gen.iter_candidates())
    assert len(got) == len(cards)
    assert len({c.mal_id for c in got}) == len(cards)


# ── Общие ограничения потоков ───────────────────────────────────────────────
def test_one_franchise_cannot_give_both_a_song_and_a_frame(
        tmp_path, monkeypatch):
    """Запрет повторов франшиз общий для песенного и непесенного потоков."""
    cards = [make_anime(1, franchise="one"), make_anime(2, franchise="one"),
             make_anime(3, franchise="two")]
    gen = _generator(tmp_path, monkeypatch, cards, [make_song(1)])
    got = list(gen.iter_candidates())
    # Второй тайтл той же серии не пришёл ни в один из потоков.
    assert {c.mal_id for c in got} == {1, 3}


def test_a_failed_download_frees_the_franchise_for_the_next_title(
        tmp_path, monkeypatch):
    """Сорвавшаяся загрузка возвращает франшизу, и место занимает следующий."""
    cards = [make_anime(1, franchise="one"), make_anime(2, franchise="two"),
             make_anime(3, franchise="one")]
    gen = _generator(tmp_path, monkeypatch, cards, [], questions=2,
                     pct_songs=0, pct_frames=100)
    # Первый тайтл не скачался: его серия должна снова стать свободной.
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: cand.mal_id != 1)
    picked = gen.select_songs()
    assert {c.mal_id for c in picked} == {2, 3}, "место занял не тот тайтл"
    assert gen._failed_media == 1


def test_a_candidate_back_from_the_bench_re_books_its_franchise(
        tmp_path, monkeypatch):
    """Отложенный кандидат занимает франшизу заново, а занятую — не отбирает."""
    gen = _generator(tmp_path, monkeypatch, [make_anime(1)], [])
    first, second = make_anime(1, franchise="one"), make_anime(2, franchise="one")
    assert gen._accept_anime(first, 1, set(), gen._used_franchise) is True
    cand = SongCandidate({}, first, kind=FRAME_KIND)
    cand._reserved = gen._last_reserved

    gen._bench_candidate(cand)                  # франшиза отпущена
    assert gen._accept_anime(second, 2, set(), gen._used_franchise) is True
    # Серию уже заняли, пока кандидат ждал — обратно он не пройдёт.
    assert gen._rebook_candidate(cand) is False

    third = SongCandidate({}, make_anime(3, franchise="three"), kind=FRAME_KIND)
    assert gen._accept_anime(third.anime, 3, set(), gen._used_franchise) is True
    third._reserved = gen._last_reserved
    gen._bench_candidate(third)
    assert gen._rebook_candidate(third) is True
    assert "three" in gen._used_franchise


# ── Средняя сложность больше не жжёт кандидатов ─────────────────────────────
def test_candidates_rejected_by_the_average_return_for_the_final_topup(
        tmp_path, monkeypatch):
    """Отложенные ради средней идут в дело, когда каталог кончился.

    За живой прогон так сгорел 321 кандидат при недобранном паке."""
    # Все тайтлы безвестные (сложность 15), а просят середину 5. Первые три
    # проходят без проверки, остальные её уже не проходят — и раньше сгорали.
    cards = [make_anime(i, statusesStats=[{"status": "completed", "count": 3}])
             for i in range(1, 7)]
    gen = _generator(tmp_path, monkeypatch, cards, [], questions=6,
                     pct_songs=0, pct_frames=100, level_avg=5)
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: True)
    picked = gen.select_songs()
    assert len(picked) == 6, f"набрано {len(picked)} — скамейка не сработала"
    assert gen._level_relaxed is True
    assert gen._level_reused == gen._level_benched >= 2
    # Ни один кандидат не потерян: скамейка пуста, франшизы возвращены.
    assert gen._level_bench == []


def test_the_average_is_still_guarded_while_candidates_last(
        tmp_path, monkeypatch):
    """Пока поток жив, середина сторожится: клапан не открывается заранее."""
    gen = _generator(tmp_path, monkeypatch, [make_anime(1)], [],
                     pct_songs=0, pct_frames=100, level_avg=8)
    hard = SongCandidate({}, make_anime(
        1, statusesStats=[{"status": "completed", "count": 3}]),
        kind=FRAME_KIND)
    easy = SongCandidate({}, make_anime(
        2, statusesStats=[{"status": "completed", "count": 900000}]),
        kind=FRAME_KIND)
    assert easy.level < 8 < hard.level
    assert gen._level_relaxed is False
    # Набранное куда легче цели — трудный кандидат проходит, лёгкий нет.
    assert gen._level_fits(hard, [1, 1, 1], FRAME_KIND) is True
    assert gen._level_fits(easy, [1, 1, 1], FRAME_KIND) is False
    # А после финального добора середина не сторожится вовсе.
    gen._level_relaxed = True
    assert gen._level_fits(easy, [1, 1, 1], FRAME_KIND) is True


def test_two_question_pack_selects_titles_with_average_four(tmp_path, monkeypatch):
    gen = _generator(tmp_path, monkeypatch, [], [], questions=2,
                     pct_songs=0, pct_frames=100, level_avg=4)
    counts = (30, 7000, 700000)  # levels 14, 7, 1
    candidates = [SongCandidate({}, make_anime(i, statusesStats=[
        {"status": "completed", "count": count}]), kind=FRAME_KIND)
        for i, count in enumerate(counts, 1)]
    assert [candidate.level for candidate in candidates] == [14, 7, 1]
    monkeypatch.setattr(gen, "iter_candidates", lambda: iter(candidates))
    monkeypatch.setattr(gen, "_fetch_media", lambda _candidate: True)
    picked = gen.select_songs()
    assert len(picked) == 2
    assert sorted(candidate.level for candidate in picked) == [1, 7]


def test_a_full_pack_is_collected_when_candidates_suffice(
        tmp_path, monkeypatch):
    """Кандидатов вдоволь — набирается ровно total_questions, не меньше."""
    cards = [make_anime(i) for i in range(1, 41)]
    songs = [make_song(i) for i in range(1, 21)]
    gen = _generator(tmp_path, monkeypatch, cards, songs, questions=12,
                     level_avg=5)
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: True)
    picked = gen.select_songs()
    assert len(picked) == 12
    kinds = collections.Counter(c.kind for c in picked)
    assert kinds[FRAME_KIND] == gen.s.question_quotas[FRAME_KIND]
    assert sum(kinds[k] for k in SONG_KINDS) == sum(
        gen.s.question_quotas[k] for k in SONG_KINDS)


# ── Отчёт о нехватке ────────────────────────────────────────────────────────
def _report(gen, monkeypatch):
    lines = []
    monkeypatch.setattr(gen, "log", lines.append)
    return lines


def test_the_shortage_report_counts_types_and_adds_up(tmp_path, monkeypatch):
    """Дефициты по родам вопросов и сходящаяся арифметика кандидатов."""
    cards = [make_anime(i) for i in range(1, 4)]
    gen = _generator(tmp_path, monkeypatch, cards, [make_song(1)],
                     questions=8)
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: True)
    lines = []
    real_log = gen.log
    monkeypatch.setattr(gen, "log", lambda msg: (lines.append(msg),
                                                 real_log(msg))[0])
    picked = gen.select_songs()
    text = "\n".join(lines)
    assert len(picked) < 8
    assert "Карточек просмотрено: 3" in text
    assert "Прошли первичные фильтры" in text
    assert "По родам вопросов:" in text
    # «нужно / получено / не хватило» — по каждому роду вопросов.
    need = gen.s.question_quotas
    got = collections.Counter(c.kind for c in picked)
    assert (f"Кадр: нужно {need[FRAME_KIND]}, получено {got[FRAME_KIND]}, "
            f"не хватило {need[FRAME_KIND] - got[FRAME_KIND]}") in text
    # Попыток ровно столько, сколько кандидатов дошло до загрузки.
    assert sum(gen._tries.values()) == len(picked)


def test_the_report_counts_candidates_rejected_during_the_download(
        tmp_path, monkeypatch):
    """Кандидат с cand.rejected считается отдельно от «не скачалось»."""
    cards = [make_anime(i) for i in range(1, 4)]
    gen = _generator(tmp_path, monkeypatch, cards, [], questions=8,
                     pct_songs=0, pct_frames=100)

    def fetch(cand):
        if cand.mal_id == 1:
            cand.rejected = True
            return False
        return cand.mal_id != 2

    monkeypatch.setattr(gen, "_fetch_media", fetch)
    lines = _report(gen, monkeypatch)
    gen.select_songs()
    text = "\n".join(lines)
    assert gen._rejected_media == 1 and gen._failed_media == 1
    assert "отвергнут по сложности уже при загрузке" in text
    assert "попытка сорвалась" in text


def test_an_empty_catalogue_is_still_reported_honestly(tmp_path, monkeypatch):
    """Настоящая пустая база — сообщение остаётся честным."""
    gen = _generator(tmp_path, monkeypatch, [], [], questions=4)
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: True)
    lines = _report(gen, monkeypatch)
    with pytest.raises(animepack.AnimePackError):
        gen.run()
    text = "\n".join(lines)
    assert "База не дала ни одной карточки" in text


# ── Совет зависит от причины ────────────────────────────────────────────────
def test_no_advice_to_widen_a_year_range_that_is_already_full(
        tmp_path, monkeypatch):
    """Диапазон годов и так полный — расширять его не предлагаем."""
    from si_hyx_parts.animepack.shortage_report import _advice
    gen = _generator(tmp_path, monkeypatch, [], [], questions=10)
    gen._skips["фильтры (тип, год, оценка, жанры)"] = 500
    gen._good_titles = 500
    tips = "; ".join(_advice(gen, 0, 10))
    assert "ослабить оценку" in tips
    assert "годы" not in tips


def test_advice_names_years_when_the_range_is_narrow(tmp_path, monkeypatch):
    from si_hyx_parts.animepack.shortage_report import _advice
    gen = _generator(tmp_path, monkeypatch, [], [], questions=10,
                     year_from=2015, year_to=2016)
    gen._skips["фильтры (тип, год, оценка, жанры)"] = 500
    gen._good_titles = 500
    assert "годы" in "; ".join(_advice(gen, 0, 10))


def test_no_advice_to_refresh_the_database_when_it_has_enough(
        tmp_path, monkeypatch):
    """Карточек вдоволь, а съели их квоты — «Обновить базу» тут ни при чём."""
    from si_hyx_parts.animepack.shortage_report import _advice
    gen = _generator(tmp_path, monkeypatch, [], [], questions=10)
    gen._good_titles = 4520
    gen._drops["мест под такой тайтл уже не осталось"] = 321
    tips = "; ".join(_advice(gen, 4, 10))
    assert "Обновить базу" not in tips
    assert "доли родов вопросов" in tips


def test_a_thin_database_is_still_told_to_refresh(tmp_path, monkeypatch):
    from si_hyx_parts.animepack.shortage_report import _advice
    gen = _generator(tmp_path, monkeypatch, [], [], questions=100)
    gen._good_titles = 12
    assert "Обновить базу" in "; ".join(_advice(gen, 3, 100))
