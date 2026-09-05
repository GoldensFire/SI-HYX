# -*- coding: utf-8 -*-
"""Вкладка «Генерация аниме-пака»: фильтры, сборка content.xml и сеть.

Сеть везде подменяется FakeSession из conftest — ни один тест наружу не ходит.
Отдельно закреплены места, где оригинальный ASPG ошибался: snake_case в теле
запроса к AnisongDB, булевы isDub/isRebroadcast, пагинация списков, замена
песни с несостоявшейся загрузкой, формат длительности, дедуп по аниме.
"""
import json
import os
import xml.etree.ElementTree as ET
import zipfile

import pytest

from conftest import FakeResponse, FakeSession

import animepack
import animepack_api as api
from animepack import (CHAR_KIND, FRAME_KIND, MEDIA_NAME_PREFIX, VIDEO_KIND,
                       AnimePackGenerator, PackSettings,
                       SongCandidate, UserList, arrange_questions,
                       build_content_xml, clear_user_list_cache,
                       filter_anime, filter_song,
                       fmt_duration, fmt_elapsed, franchise_key, index_level,
                       load_frame_history, price_for_difficulty,
                       price_for_index, save_frame_history, song_kind,
                       song_difficulty_bonus, song_tag, title_root,
                       answer_title, siq_answer_roots)


@pytest.fixture(autouse=True)
def _forget_user_lists():
    """Кэш списков пользователей живёт в модуле и переживает тест — чистим его,
    иначе ники из соседнего теста «уже спрошены» и сеть не трогается вовсе."""
    clear_user_list_cache()
    yield
    clear_user_list_cache()


# ── Заготовки данных ─────────────────────────────────────────────────────────
def make_song(**over):
    song = {
        "annId": 6592, "annSongId": 7868, "audio": "a6h06o.mp3",
        "animeENName": "Death Note", "animeJPName": "Death Note",
        "animeType": "TV", "animeCategory": "TV",
        "linked_ids": {"myanimelist": 1535},
        "songType": "Opening 1", "songName": "the WORLD",
        "songArtist": "Nightmare", "songCategory": "Standard",
        "songDifficulty": 85.0, "songLength": 79.0,
        "isDub": False, "isRebroadcast": False,
    }
    song.update(over)
    return song


def make_anime(**over):
    anime = {
        "id": 1535, "malId": 1535, "name": "Death Note",
        "russian": "Тетрадь смерти", "english": "Death Note",
        "japanese": "デスノート", "synonyms": ["DN"],
        "licenseNameRu": "Тетрадь смерти", "franchise": "death_note",
        "score": 8.6, "kind": "tv",
        "genres": [{"id": "27", "name": "Shounen"}, {"id": "40", "name": "Psychological"}],
        "poster": {"originalUrl": "https://shiki/poster.jpg"},
        "screenshots": [{"originalUrl": f"https://shiki/{i}.jpg"} for i in range(6)],
        "airedOn": {"year": 2006},
        "statusesStats": [{"status": "completed", "count": 1000},
                          {"status": "planned", "count": 500}],
    }
    anime.update(over)
    return anime


def make_candidate(**over):
    song = make_song(**over.pop("song", {}))
    anime = make_anime(**over.pop("anime", {}))
    cand = SongCandidate(song=song, anime=anime,
                         kind=song_kind(song["songType"]) or "opening",
                         **over)
    return cand


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


# ── content.xml ──────────────────────────────────────────────────────────────
def _parse(xml_bytes):
    root = ET.fromstring(xml_bytes)
    ns = {"s": "https://github.com/VladimirKhil/SI/blob/master/assets/siq_5.xsd"}
    return root, ns


def test_build_content_xml_structure():
    s = PackSettings(rounds=1, themes=1, questions=2, openings=2, endings=0, inserts=0)
    easy = make_candidate(song={"songDifficulty": 95.0})      # цена 6
    hard = make_candidate(song={"songDifficulty": 5.0, "annSongId": 9})   # цена 20
    easy.has_poster = hard.has_poster = True
    root, ns = _parse(build_content_xml([hard, easy], s))

    assert root.get("version") == "5"
    assert root.get("name") == s.title
    assert root.get("id") and root.get("date")
    questions = root.findall(".//s:question", ns)
    assert len(questions) == 2
    # Внутри темы вопросы идут по возрастанию цены (в ASPG порядок был случайный).
    assert [q.get("price") for q in questions] == ["6", "20"]

    audio = questions[0].find(".//s:item[@type='audio']", ns)
    # В пак кладётся opus, а не исходный mp3 с CDN.
    assert audio.text == "7868.opus"
    assert audio.get("isRef") == "True"
    assert audio.get("placement") == "background"
    # Картинок нет → аудио играет ВЕСЬ отрезок (ASPG всё равно резал 7 секунд).
    assert audio.get("duration") == "00:00:20"
    poster = questions[0].find(".//s:param[@name='answer']/s:item[@type='image']", ns)
    assert poster.text.endswith("_poster.avif")


def test_build_content_xml_images_and_hint():
    s = PackSettings(rounds=1, themes=1, questions=1, images=True, images_time=7,
                     audio_cut=20, hint=True)
    cand = make_candidate()
    cand.has_collage = True
    root, ns = _parse(build_content_xml([cand], s))
    audio = root.find(".//s:item[@type='audio']", ns)
    assert audio.get("duration") == "00:00:13"       # 20 − 7
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
    assert audio.get("duration") == "00:00:20"


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
    assert [r.text for r in replics] == ["Исполнитель — 『Nightmare』 · morr, kao"]


def test_answer_replic_is_artist_without_lists():
    """Без списков людей реплика ведущего — исполнитель песни."""
    s = PackSettings(rounds=1, themes=1, questions=1)
    root, ns = _parse(build_content_xml([make_candidate()], s))
    replics = root.findall(".//s:param[@name='answer']/s:item[@placement='replic']", ns)
    assert [r.text for r in replics] == ["Исполнитель — 『Nightmare』"]


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
    assert items[0].text == "Исполнитель — 『Nightmare』"


def test_answer_bare_russian_title_goes_last():
    """Сразу после «Название (год) — 『Песня』» голое название смотрится
    копией, поэтому идёт в самый конец — после ромадзи и синонимов."""
    cand = make_candidate()
    variants = cand.answer_variants()
    assert variants[0] == "Тетрадь смерти OP1 (2006) — 『the WORLD』"
    assert variants[1] == "Death Note"                 # ромадзи
    assert variants[-1] == "Тетрадь смерти"            # копия — в хвосте


def test_shuffle_questions_keeps_given_order():
    """«В разнобой»: вопросы идут как набрались, а не по возрастанию цены."""
    s = PackSettings(rounds=1, themes=1, questions=3, shuffle_questions=True)
    hard = make_candidate(song={"annSongId": 1, "songDifficulty": 10.0},
                          anime={"malId": 1, "russian": "Первое"})
    easy = make_candidate(song={"annSongId": 2, "songDifficulty": 95.0},
                          anime={"malId": 2, "russian": "Второе"})
    mid = make_candidate(song={"annSongId": 3, "songDifficulty": 50.0},
                         anime={"malId": 3, "russian": "Третье"})
    theme = arrange_questions([hard, easy, mid], s)[0]
    assert [c.mal_id for c in theme] == [1, 2, 3]
    assert theme[0].price > theme[1].price          # цены НЕ по возрастанию
    s.shuffle_questions = False
    theme = arrange_questions([hard, easy, mid], s)[0]
    assert [c.price for c in theme] == sorted(c.price for c in theme)


def test_package_author():
    """В авторах пака — откуда он взялся."""
    s = PackSettings(rounds=1, themes=1, questions=1)
    root, ns = _parse(build_content_xml([make_candidate()], s))
    assert root.find(".//s:info/s:authors/s:author", ns).text == \
        "Сгенерировано в программе SI-HYX"


def test_answer_poster_is_not_simultaneous():
    """У постера не должно быть режима «воспроизводить одновременно»
    (waitForFinish="False") — просьба пользователя."""
    s = PackSettings(rounds=1, themes=1, questions=1)
    cand = make_candidate()
    cand.has_poster = True
    root, ns = _parse(build_content_xml([cand], s))
    poster = root.find(".//s:param[@name='answer']/s:item[@type='image']", ns)
    assert poster.get("waitForFinish") is None
    assert poster.get("duration") == "00:00:03"


def test_kind_price_step_is_one_rung():
    """Опенинг 2 → эндинг 3 → вставка 4 при одинаковой узнаваемости."""
    s = PackSettings(rounds=1, themes=1, questions=3)
    cands = []
    for i, kind in enumerate(("Opening 1", "Ending 1", "Insert Song")):
        c = make_candidate(song={"annSongId": i + 1, "songType": kind,
                                 "songDifficulty": 100.0},
                           anime={"malId": i + 1})
        c.kind = song_kind(kind)
        cands.append(c)
    theme = arrange_questions(cands, s)
    assert [c.price for c in theme[0]] == [6, 7, 8]


def test_kind_price_step_opening_cheaper_than_insert():
    """Опенинг < эндинг < вставка при одинаковой сложности."""
    s = PackSettings(rounds=1, themes=1, questions=3)
    op = make_candidate(song={"annSongId": 1, "songType": "Opening 1"})
    ed = make_candidate(song={"annSongId": 2, "songType": "Ending 1"})
    ins = make_candidate(song={"annSongId": 3, "songType": "Insert Song"})
    for c, kind in ((op, "opening"), (ed, "ending"), (ins, "insert")):
        c.kind = kind
    theme = arrange_questions([ins, ed, op], s)[0]
    assert [c.kind for c in theme] == ["opening", "ending", "insert"]
    assert theme[0].price < theme[1].price < theme[2].price


def test_audio_filters_match_processing_tab():
    """Нормализация -20/11/-1.5, затухание в конце и фикс раскладки под opus."""
    from animepack import OPUS_LAYOUT_FIX, AnimePackGenerator as G
    af = G.audio_filters(20)
    assert af.startswith("loudnorm=I=-20.0:LRA=11.0:TP=-1.5,")
    assert "afade=t=out:st=19.000:d=1.0" in af
    assert af.endswith(OPUS_LAYOUT_FIX)
    # Отрезок короче фейда — старт затухания не уезжает в минус.
    assert "afade=t=out:st=0.000" in G.audio_filters(0.5)


# ── Режим «только кадры» ─────────────────────────────────────────────────────
def test_frames_only_question_is_image_and_answer_has_no_song():
    s = PackSettings(rounds=1, themes=1, questions=1, pct_songs=0, pct_frames=100)
    cand = SongCandidate(song={}, anime=make_anime(), kind=FRAME_KIND)
    cand.has_frame = cand.has_poster = True
    root, ns = _parse(build_content_xml([cand], s))
    q_items = root.findall(".//s:param[@name='question']/s:item", ns)
    assert len(q_items) == 1 and q_items[0].get("type") == "image"
    assert q_items[0].text == cand.frame_file == "1535_frame.avif"
    assert root.find(".//s:item[@type='audio']", ns) is None
    # Без песни ответ — просто название с годом.
    assert root.find(".//s:right/s:answer", ns).text == "Тетрадь смерти (2006)"


def test_frames_only_takes_titles_without_shikimori_screenshots():
    """Кадры собираются ещё и с AniList/Kitsu, поэтому отсутствие скриншотов
    у Shikimori тайтл больше не выбраковывает."""
    s = PackSettings(pct_songs=0, pct_frames=100)
    assert filter_anime(make_anime(screenshots=[]), s) is True
    assert filter_anime(make_anime(), s) is True
    # Квоты по типам песен в режиме кадров не проверяются.
    s = PackSettings(pct_songs=0, pct_frames=100, openings=0, endings=0, inserts=0)
    assert not any("распределите" in p for p in s.validate())


def test_frames_only_candidates_skip_anisong_for_lists():
    """Списки людей дают MAL id сразу — AnisongDB в режиме кадров не нужен."""
    s = PackSettings(random_mode=False, similar_count=1,
                     pct_songs=0, pct_frames=100,
                     users=[UserList("morr", "myanimelist", ["completed"])])
    _s1, a1 = _pair(1, "naruto")
    _s2, a2 = _pair(2, "naruto")               # та же франшиза — отсеется
    _s3, a3 = _pair(3, "bleach")

    class Boom:
        def songs_by_mal_ids(self, ids):
            raise AssertionError("AnisongDB в режиме кадров не должен вызываться")
        songs_by_ann_ids = songs_by_mal_ids

    gen = _generator(s, [], [a1, a2, a3], user_ids={"morr": [1, 2, 3]})
    gen.anisong = Boom()
    cands = list(gen.iter_candidates())
    assert {c.mal_id for c in cands} == {1, 3}
    assert all(c.song == {} and c.kind == FRAME_KIND for c in cands)


# ── Смешанный режим: кадры вперемешку с песнями ──────────────────────────────
def test_mixed_quotas_split_frames_and_songs():
    """На каждые 2 кадра — одна песня, а квоты по типам ужимаются под неё."""
    s = PackSettings(rounds=1, themes=1, questions=9, pct_songs=34, pct_frames=66, openings=6, endings=2, inserts=1)
    q = s.question_quotas
    assert q[FRAME_KIND] == 6
    assert sum(q[k] for k in ("opening", "ending", "insert")) == 3
    assert q["opening"] == 2                      # 6/9 от трёх песен
    # Поровну — 9 вопросов не делятся ровно, лишний достаётся картинкам.
    s.pct_songs, s.pct_frames = 50, 50
    assert s.question_quotas[FRAME_KIND] == 5
    # Ползунок до упора — весь пак из кадров.
    s.pct_songs, s.pct_frames = 0, 100
    q = s.question_quotas
    assert q[FRAME_KIND] == 9 and q[CHAR_KIND] == 0
    assert sum(q[k] for k in ("opening", "ending", "insert")) == 0


def test_mixed_select_songs_makes_both_kinds(monkeypatch):
    s = PackSettings(rounds=1, themes=1, questions=6, pct_songs=34, pct_frames=66, openings=6, endings=0, inserts=0,
                     parallel=1, random_mode=False, similar_count=1,
                     users=[UserList("morr", "shikimori", ["completed"])])
    pairs = [_pair(i, f"fr{i}") for i in range(1, 12)]
    gen = _generator(s, [p[0] for p in pairs], [p[1] for p in pairs],
                     user_ids={"morr": list(range(1, 12))})
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: True)
    picked = gen.select_songs()
    kinds = [c.kind for c in picked]
    assert len(picked) == 6
    assert kinds.count(FRAME_KIND) == 4 and kinds.count("opening") == 2
    # У вопроса-кадра песни нет, даже если кандидат пришёл с ней.
    frame = next(c for c in picked if c.is_frame)
    assert frame.song_name == "" and frame.artist == ""
    assert frame.main_answer == frame.title_ru + " (2006)"


def test_mixed_pack_xml_has_image_and_audio_questions():
    s = PackSettings(rounds=1, themes=1, questions=2, pct_songs=50, pct_frames=50, hint=False)
    song = make_candidate(song={"annSongId": 1}, anime={"malId": 1})
    frame = make_candidate(song={"annSongId": 2}, anime={"malId": 2})
    frame.kind = FRAME_KIND
    frame.has_frame = True
    root, ns = _parse(build_content_xml([song, frame], s))
    q_items = root.findall(".//s:param[@name='question']/s:item", ns)
    assert {i.get("type") for i in q_items} == {"audio", "image"}


def test_frame_question_works_without_shikimori_screenshots(monkeypatch):
    """Кадр добирается с AniList/Kitsu, так что тайтл без скриншотов Shikimori
    вопросом-кадром стать может."""
    s = PackSettings(rounds=1, themes=1, questions=2, pct_songs=50, pct_frames=50, openings=2, endings=0, inserts=0,
                     parallel=1, random_mode=False, similar_count=1,
                     users=[UserList("morr", "shikimori", ["completed"])])
    pairs = [_pair(i, f"fr{i}", anime_over={"screenshots": []})
             for i in range(1, 6)]
    gen = _generator(s, [p[0] for p in pairs], [p[1] for p in pairs],
                     user_ids={"morr": [1, 2, 3, 4, 5]})
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: True)
    picked = gen.select_songs()
    assert picked and any(c.is_frame for c in picked)


# ── Сложность по узнаваемости и франшизы ─────────────────────────────────────
@pytest.mark.parametrize("index,level", [
    (5_000_000, 1), (700_000, 1), (699_999, 2), (215_000, 3), (66_000, 5),
    (6_000, 9), (5_999, 10), (0, 10), (None, 10),
])
def test_index_level(index, level):
    assert index_level(index) == level


@pytest.mark.parametrize("name,root", [
    ("Доктор Стоун: Научное будущее. Часть 3", "доктор стоун"),
    ("Доктор Стоун", "доктор стоун"),
    ("Доктор Стоун 4", "доктор стоун"),
    ("Магическая битва 0. Фильм", "магическая битва"),
    ("Тетрадь смерти (2006)", "тетрадь смерти"),
    ("Ван-Пис", "ван-пис"),
    ("Тор", ""),                           # слишком короткий корень
])
def test_title_root(name, root):
    assert title_root(name) == root


def test_sequel_inherits_franchise_index():
    """Сиквел узнаваем настолько же, насколько оригинал серии."""
    sequel = make_anime(malId=62568, russian="Доктор Стоун: Часть 3",
                        franchise="dr_stone", airedOn={"year": 2026},
                        statusesStats=[{"status": "completed", "count": 9098}])
    cand = SongCandidate(song={}, anime=sequel, kind=FRAME_KIND)
    alone = cand.level
    cand.franchise_index = 550_000.0
    assert cand.index == 550_000.0 and cand.own_index < 550_000.0
    assert cand.level < alone                    # стал заметно легче


def test_level_filter_skips_too_easy(monkeypatch):
    """«Сложность пака от 2» выбрасывает самые заезженные тайтлы."""
    s = PackSettings(rounds=1, themes=1, questions=2, level_min=2, level_max=10,
                     random_mode=False, similar_count=1, parallel=1,
                     users=[UserList("morr", "shikimori", ["completed"])])
    hot = make_anime(malId=1, id=1, russian="Мега известное", franchise="a",
                     airedOn={"year": 2024},
                     statusesStats=[{"status": "completed", "count": 500_000}])
    mid = make_anime(malId=2, id=2, russian="Обычное такое", franchise="b",
                     airedOn={"year": 2015},
                     statusesStats=[{"status": "completed", "count": 20_000}])
    songs = [make_song(linked_ids={"myanimelist": i}, annSongId=i * 10)
             for i in (1, 2)]
    gen = _generator(s, songs, [hot, mid], user_ids={"morr": [1, 2]})
    got = [c.mal_id for c in gen.iter_candidates()]
    assert got == [2]                            # первый — уровень 1, не подошёл


def test_dedup_by_title_root_when_franchise_missing():
    """У свежих тайтлов Shikimori иногда не проставил franchise — серия всё
    равно не должна попасть в пак дважды (в паке пользователя так пролезли две
    части «Доктора Стоуна»)."""
    s = PackSettings(random_mode=False, similar_count=1,
                     pct_songs=0, pct_frames=100,
                     users=[UserList("morr", "shikimori", ["completed"])])
    part2 = make_anime(malId=61322, id=61322, franchise="dr_stone",
                       russian="Доктор Стоун: Научное будущее. Часть 2")
    part3 = make_anime(malId=62568, id=62568, franchise=None,
                       russian="Доктор Стоун: Научное будущее. Часть 3")
    other = make_anime(malId=7, id=7, franchise="bleach", russian="Блич")
    gen = _generator(s, [], [part2, part3, other], user_ids={"morr": [61322, 62568, 7]})
    got = [c.mal_id for c in gen.iter_candidates()]
    assert got == [61322, 7]


# ── Галочки сжатия ───────────────────────────────────────────────────────────
def test_compression_off_copies_source_stream():
    """Выключенное сжатие аудио = поток копируется: никакого второго
    перекодирования поверх того, что отдал сервер."""
    s = PackSettings(compress_audio=False)
    gen = AnimePackGenerator(s, session=object())
    assert gen.audio_encode_args(20) == ["-c:a", "copy"]
    args = AnimePackGenerator(PackSettings(), session=object()).audio_encode_args(20)
    assert "libopus" in args and "-af" in args


def test_compression_off_keeps_source_extensions(tmp_path):
    s = PackSettings(compress_images=False, compress_audio=False)
    gen = AnimePackGenerator(s, session=object())
    gen.folder = str(tmp_path)
    os.makedirs(os.path.join(gen.folder, "Images"), exist_ok=True)
    cand = make_candidate(compress_audio=False, compress_images=False)
    assert cand.audio_out == "7868.mp3"           # как приехало с CDN
    name = gen._save_image(b"\x89PNG", f"{cand.media_key}_poster", ".png")
    assert name == "7868_poster.png"
    with open(os.path.join(gen.folder, "Images", name), "rb") as f:
        assert f.read() == b"\x89PNG"             # байты не тронуты
    cand.poster_name = name
    assert cand.poster_file == "7868_poster.png"
    # Со сжатием имена всегда .opus/.avif.
    on = make_candidate()
    assert on.audio_out == "7868.opus" and on.poster_file == "7868_poster.avif"


def test_url_ext_ignores_query():
    ext = AnimePackGenerator._url_ext
    assert ext("https://shiki/original/1535.jpeg?1690") == ".jpeg"
    assert ext("https://shiki/x.webp") == ".webp"
    assert ext("https://shiki/no-ext") == ".jpg"


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


def test_price_for_index_maps_rank_to_ladder():
    ladder = [0.0, 0.0, 10.0, 100.0, 1000.0]
    assert price_for_index(1000.0, ladder) == 6      # самый узнаваемый — дешевле всех
    assert price_for_index(0.0, ladder) == 20        # никем не смотренные — дороже всех
    assert price_for_index(100.0, ladder) == 9        # 3 из 4 позади → 75 %
    assert price_for_index(5.0, [5.0]) == 12         # сравнивать не с чем


def test_sort_by_index_orders_pack_and_prices():
    s = PackSettings(rounds=1, themes=1, questions=3, sort_by_index=True)
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
    theme = arrange_questions([mid, cold, hot], s)[0]
    # Самый узнаваемый идёт первым и стоит дешевле всех — вопреки сложности AMQ.
    assert [c.mal_id for c in theme] == [1, 2, 3]
    # Цена по индексу плюс небольшая надбавка за сложность самой песни:
    # 6+3 у почти неугадываемой (difficulty 5), 12+0 у лёгкой (95), 20+2 у 50.
    assert [c.price for c in theme] == [9, 12, 22]

    s.sort_by_index = False
    theme = arrange_questions([mid, cold, hot], s)[0]
    assert [c.price for c in theme] == [price_for_difficulty(95.0),
                                        price_for_difficulty(50.0),
                                        price_for_difficulty(5.0)]


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

    gen = AnimePackGenerator(settings, session=object(), amq=object(),
                             anisong=FakeAnisong(), mal=FakeMal(),
                             shikimori=FakeShiki(), **{
                                 k: v for k, v in kw.items() if k != "user_ids"})
    return gen


def _pair(mal_id, franchise="fr", song_over=None, anime_over=None):
    song = make_song(**{"linked_ids": {"myanimelist": mal_id},
                        "annSongId": mal_id * 10, **(song_over or {})})
    # Название у каждой франшизы своё: тайтлы с общим корнем имени генератор
    # считает частями одной серии и в один пак не пускает.
    anime = make_anime(**{"malId": mal_id, "id": mal_id, "franchise": franchise,
                          "russian": f"Тетрадь смерти {franchise}",
                          **(anime_over or {})})
    return song, anime


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


def test_run_writes_readable_siq(tmp_path, monkeypatch):
    """Готовый .siq должен читаться разборщиком самого приложения, и все
    ссылки на медиа — существовать внутри архива."""
    s = PackSettings(rounds=1, themes=1, questions=2, openings=2, endings=0,
                     inserts=0, parallel=1, random_mode=False,
                     similar_count=1, title="Тест пак",
                     out_dir=str(tmp_path),
                     users=[UserList("morr", "myanimelist", ["completed"])])
    pairs = [_pair(i, f"fr{i}") for i in (1, 2)]
    gen = _generator(s, [p[0] for p in pairs], [p[1] for p in pairs],
                     user_ids={"morr": [1, 2]})

    def fake_fetch(cand):
        audio = os.path.join(gen.folder, "Audio", cand.audio_out)
        with open(audio, "wb") as f:
            f.write(b"\x00" * 32)
        poster = os.path.join(gen.folder, "Images", cand.poster_file)
        with open(poster, "wb") as f:
            f.write(b"\x00" * 16)
        cand.has_poster = True
        return True

    monkeypatch.setattr(gen, "_fetch_media", fake_fetch)
    result = gen.run()
    assert result.path.endswith(".siq") and os.path.exists(result.path)
    assert len(result.songs) == 2

    with zipfile.ZipFile(result.path) as zf:
        names = set(zf.namelist())
        assert "content.xml" in names
        xml = zf.read("content.xml")
        root, ns = _parse(xml)
        for item in root.findall(".//s:item[@isRef='True']", ns):
            folder = "Audio" if item.get("type") == "audio" else "Images"
            assert f"{folder}/{item.text}" in names

    # Разборщик приложения (SiQuesterHYX) должен понять пакет.
    from siquester.siq_package import SiqPackage
    pkg = SiqPackage(result.path)
    assert sum(len(t.get("questions", ())) for r in pkg.rounds
               for t in r.get("themes", ())) == 2
    assert gen.folder == ""            # временная папка убрана


def test_run_refuses_broken_settings():
    from animepack import AnimePackError
    s = PackSettings(openings=0, endings=0, inserts=0)
    gen = AnimePackGenerator(s, session=object())
    with pytest.raises(AnimePackError):
        gen.run()


# ── Тег песни в ответе («Название OP1 (2010)») ───────────────────────────────
@pytest.mark.parametrize("song_type,tag", [
    ("Opening 1", "OP1"), ("Ending 12", "ED12"), ("Insert Song", "OST"),
    ("Opening", "OP"), ("Что-то", ""), (None, ""),
])
def test_song_tag(song_type, tag):
    assert song_tag(song_type) == tag


def test_answer_tag_goes_before_year():
    """Просьба пользователя: в ответе видно, опенинг это, эндинг или вставка."""
    cand = make_candidate(song={"songType": "Ending 2"})
    assert cand.main_answer == "Тетрадь смерти ED2 (2006) — 『the WORLD』"
    # Год, уже записанный Shikimori в название, не задваивается и остаётся
    # последним — тег встаёт перед ним.
    old = make_candidate(song={"songType": "Insert Song"},
                         anime={"russian": "Могучий Атом (2003)",
                                "airedOn": {"year": 2003}})
    assert old.main_answer == "Могучий Атом OST (2003) — 『the WORLD』"
    # У вопроса-кадра песни нет — нет и тега.
    frame = make_candidate()
    frame.kind = FRAME_KIND
    assert frame.tag == "" and frame.main_answer == "Тетрадь смерти (2006)"


# ── Выбор кадра: случайный и без повторов ────────────────────────────────────
def _frame_cand(anime=None):
    return SongCandidate(song={}, anime=anime or make_anime(), kind=FRAME_KIND)


def test_frame_pick_is_random_and_unique_within_pack():
    s = PackSettings(pct_songs=0, pct_frames=100)
    gen = _generator(s, [], [])
    cand = _frame_cand()
    picked = [gen._pick_frame_url(cand) for _ in range(6)]
    assert len(set(picked)) == 6          # шесть скриншотов — шесть разных
    # Кадры кончились, но памяти о прошлых паках нет — берём по кругу.
    assert gen._pick_frame_url(cand)


def test_frame_pick_never_repeats_within_pack():
    """Кадр всегда случайный (настройки «первый кадр» больше нет), но дважды
    один и тот же в паке не берётся."""
    s = PackSettings(pct_songs=0, pct_frames=100)
    gen = _generator(s, [], [])
    cand = _frame_cand()
    seen = {gen._pick_frame_url(cand) for _ in range(6)}
    assert len(seen) == 6


def test_frames_no_repeat_skips_history(tmp_path):
    path = str(tmp_path / "frames.json")
    save_frame_history(["https://shiki/0.jpg", "https://shiki/1.jpg"], path)
    s = PackSettings(pct_songs=0, pct_frames=100, frames_no_repeat=True)
    gen = _generator(s, [], [], frames_history_path=path)
    # Кадр случайный, но из тех, что в истории ещё не были.
    assert gen._pick_frame_url(_frame_cand()) in {
        f"https://shiki/{i}.jpg" for i in range(2, 6)}


def test_frames_no_repeat_drops_title_without_fresh_frames(tmp_path):
    path = str(tmp_path / "frames.json")
    save_frame_history([f"https://shiki/{i}.jpg" for i in range(6)], path)
    s = PackSettings(pct_songs=0, pct_frames=100, frames_no_repeat=True)
    gen = _generator(s, [], [], frames_history_path=path)
    # Свободных кадров нет — вопроса не будет, пак возьмёт другой тайтл.
    assert gen._pick_frame_url(_frame_cand()) == ""


def test_save_frames_history_appends_used_only(tmp_path):
    path = str(tmp_path / "frames.json")
    s = PackSettings(pct_songs=0, pct_frames=100, frames_no_repeat=True)
    gen = _generator(s, [], [], frames_history_path=path)
    used = _frame_cand()
    used.frame_url, used.has_frame = "https://shiki/3.jpg?ts=1", True
    lost = _frame_cand()
    lost.frame_url = "https://shiki/4.jpg"      # кадр не скачался
    gen.save_frames_history([used, lost])
    assert load_frame_history(path) == ["https://shiki/3.jpg"]  # ?query отброшен

    # Без галочки история не пишется вовсе.
    s2 = PackSettings(pct_songs=0, pct_frames=100)
    gen2 = _generator(s2, [], [], frames_history_path=str(tmp_path / "no.json"))
    gen2.save_frames_history([used])
    assert load_frame_history(str(tmp_path / "no.json")) == []


# ── Галочки типов песен ──────────────────────────────────────────────────────
def test_song_kind_checkboxes_filter_songs_and_quotas():
    s = PackSettings(pick_openings=False)
    assert filter_song(make_song(songType="Opening 1"), s) is False
    assert filter_song(make_song(songType="Ending 1"), s) is True
    assert s.quotas["opening"] == 0
    assert s.quotas["ending"] == s.endings
    # Ни одного типа — генерацию запускать бессмысленно.
    s = PackSettings(pick_openings=False, pick_endings=False, pick_inserts=False)
    assert any("тип песни" in p for p in s.validate())


def test_only_endings_pack_takes_endings(monkeypatch):
    """Оставили одни эндинги — опенингов в паке нет вовсе."""
    s = PackSettings(rounds=1, themes=1, questions=2, parallel=1,
                     pick_openings=False, pick_inserts=False,
                     openings=54, endings=20, inserts=16, random_mode=False,
                     similar_count=1,
                     users=[UserList("morr", "shikimori", ["completed"])])
    pairs = [_pair(i, f"fr{i}") for i in range(1, 5)]
    songs = []
    for n, (song, _anime) in enumerate(pairs):
        songs.append(dict(song, songType="Opening 1"))
        songs.append(dict(song, songType="Ending 1", annSongId=song["annSongId"] + 1))
    gen = _generator(s, songs, [p[1] for p in pairs],
                     user_ids={"morr": [1, 2, 3, 4]})
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: True)
    picked = gen.select_songs()
    assert len(picked) == 2
    assert all(c.kind == "ending" for c in picked)
    assert all("ED" in c.main_answer for c in picked)


# ── «Похожие» = переключатель «собирать по спискам» ──────────────────────────
def test_common_base_means_no_lists_are_requested():
    """Общая база включена — ни один список не спрашивается. Отдельной галочки
    «Похожие» больше нет: снятые обе базы и означают сборку по спискам."""
    s = PackSettings(random_mode=True, random_source="amq",
                     users=[UserList("morr", "shikimori", ["completed"])])
    assert s.random_pool is True
    # Списка нет — и он не нужен: жалобы на «добавьте пользователя» быть не должно.
    assert not any("пользовател" in p for p in PackSettings().validate())

    class Boom:
        def user_anime_ids(self, *_a, **_kw):
            raise AssertionError("с общей базой списки спрашивать нельзя")

    class FakeAmq:
        def library(self, progress_cb=None, should_stop=None):
            return {11: 2015, 22: 2016}

    gen = _generator(s, [], [])
    gen.amq, gen.shikimori.user_anime_ids, gen.mal = FakeAmq(), Boom().user_anime_ids, Boom()
    assert {aid for aid, _users in gen.collect_anime_ids()} == {11, 22}

    # Обе базы сняты — наоборот, идут списки, а база AMQ не трогается.
    s.random_mode, s.similar_count = False, 1
    assert s.random_pool is False
    gen = _generator(s, [], [], user_ids={"morr": [5, 7]})
    gen.amq = object()
    assert {aid for aid, _users in gen.collect_anime_ids()} == {5, 7}


def test_user_lists_are_asked_once_per_run_of_the_program():
    """Просьба пользователя: уже спрошенный список берётся из памяти, пока
    программу не перезапустили, — следующий пак собирается быстрее."""
    calls = []

    class CountingShiki:
        def user_anime_ids(self, nick, statuses, **_kw):
            calls.append(nick)
            return [1, 2, 3]

        def animes_by_ids(self, ids):
            return []

        def franchise_parts(self, keys):
            return {}

    s = PackSettings(random_mode=False, similar_count=1,
                     users=[UserList("morr", "shikimori", ["completed"])])
    for _ in range(3):
        gen = _generator(s, [], [])
        gen.shikimori = CountingShiki()
        assert {aid for aid, _u in gen.collect_anime_ids()} == {1, 2, 3}
    assert calls == ["morr"]

    # Другие статусы — другой список, его спрашиваем заново.
    s.users = [UserList("morr", "shikimori", ["watching"])]
    gen = _generator(s, [], [])
    gen.shikimori = CountingShiki()
    gen.collect_anime_ids()
    assert calls == ["morr", "morr"]

    # Перезапуск программы (очистка кэша) — список спрашивается снова.
    clear_user_list_cache()
    gen = _generator(s, [], [])
    gen.shikimori = CountingShiki()
    gen.collect_anime_ids()
    assert calls == ["morr", "morr", "morr"]


def test_characters_api_keeps_all_names():
    """Раздел «Прочие» со страницы персонажа приезжает вместе с именем."""
    payload = {"data": {"animes": [{
        "id": "1535", "malId": "1535",
        "characterRoles": [{
            "rolesEn": ["Supporting"],
            "character": {"id": "3", "name": "Ryuk", "russian": "Рюк",
                          "synonyms": ["Shinigami, Рюук"],
                          "poster": {"originalUrl": "https://shiki/r.jpg"}}}]}]}}

    class FakeClient:
        base_url = "https://shikimori.one"

        def _graphql(self, query, variables):
            assert "synonyms" in query
            return payload["data"]

    rows = api.ShikimoriApi(session=object(),
                            client=FakeClient()).characters_by_anime_ids([1535])
    row = rows[1535][0]
    assert row["name"] == "Рюк" and row["main"] is False
    # «Прочие» приезжают одной строкой через запятую — её разбиваем, иначе
    # целиком такое прозвище никто не назовёт.
    assert row["names"] == ["Рюк", "Ryuk", "Shinigami", "Рюук"]


# ── Персонажи, подсказка, имена файлов, исключения по чужим пакам ────────────
def test_character_answer_and_price_multiplier():
    """Ответ «Название (год) — 『Имя』», цена — как за тайтл, но в полтора раза."""
    s = PackSettings(rounds=1, themes=1, questions=2, pct_songs=0, pct_chars=100)
    hero = make_candidate(anime={"malId": 1})
    hero.kind = CHAR_KIND
    hero.character = {"id": 7, "name": "Лайт Ягами", "main": True}
    plain = make_candidate(song={"annSongId": 2}, anime={"malId": 2})
    plain.kind = FRAME_KIND
    theme = arrange_questions([hero, plain], s)[0]
    assert hero.main_answer == "Тетрадь смерти (2006) — 『Лайт Ягами』"
    # Оба тайтла с одинаковым индексом → одна база цены, персонаж дороже в 1,5.
    assert hero.price == int(round(plain.price * 1.5))


def test_supporting_character_costs_more_than_main():
    """Просьба пользователя: второстепенный герой — 1,8 цены тайтла, а не 1,5."""
    s = PackSettings(rounds=1, themes=1, questions=3, pct_songs=0, pct_chars=100)
    main = make_candidate(anime={"malId": 1})
    main.kind = CHAR_KIND
    main.character = {"id": 1, "name": "Лайт Ягами", "main": True}
    side = make_candidate(song={"annSongId": 2}, anime={"malId": 2})
    side.kind = CHAR_KIND
    side.character = {"id": 2, "name": "Рюк", "main": False}
    plain = make_candidate(song={"annSongId": 3}, anime={"malId": 3})
    plain.kind = FRAME_KIND
    arrange_questions([main, side, plain], s)
    assert main.price == int(round(plain.price * 1.5))
    assert side.price == int(round(plain.price * 1.8))


def test_character_answers_do_not_accept_bare_title():
    """Голое название аниме не должно засчитываться: угадывают персонажа."""
    cand = make_candidate()
    cand.kind = CHAR_KIND
    cand.character = {"id": 7, "name": "Лайт Ягами", "main": True}
    variants = cand.answer_variants()
    assert variants[0] == "Тетрадь смерти (2006) — 『Лайт Ягами』"
    assert "Лайт Ягами" in variants
    assert "Тетрадь смерти" not in variants


def test_character_answers_list_every_name_of_the_character():
    """В ответе перебираются имена ПЕРСОНАЖА (в том числе «Прочие» с его
    страницы Shikimori), а не названия аниме."""
    cand = make_candidate()
    cand.kind = CHAR_KIND
    cand.character = {"id": 7, "main": False, "name": "Лайт Ягами",
                      "names": ["Лайт Ягами", "Light Yagami"],
                      "synonyms": ["Kira", "キラ"]}
    variants = cand.answer_variants()
    assert variants[0] == "Тетрадь смерти (2006) — 『Лайт Ягами』"
    for name in ("Лайт Ягами", "Light Yagami", "Kira"):
        assert name in variants
    # Название произведения — ровно один раз, в основном ответе: доп-варианты
    # состоят из одних имён персонажа (просьба пользователя).
    assert sum("Тетрадь смерти" in v for v in variants) == 1
    # Иероглифы по-прежнему не годятся, а имена аниме в ответ не идут.
    assert not any("キラ" in v for v in variants)
    assert "Death Note" not in variants and "DN" not in variants


def test_chars_only_quotas_and_xml():
    s = PackSettings(rounds=1, themes=1, questions=2, pct_songs=0, pct_chars=100)
    assert s.question_quotas[CHAR_KIND] == 2
    assert not any(v for k, v in s.question_quotas.items() if k != CHAR_KIND)
    cand = make_candidate()
    cand.kind = CHAR_KIND
    cand.character = {"id": 1, "name": "Рюк", "main": False}
    cand.has_frame = True
    root, ns = _parse(build_content_xml([cand], s))
    items = root.findall(".//s:param[@name='question']/s:item", ns)
    # Первым идёт задание «Назвать персонажа» (иначе портрет неотличим от
    # обычного кадра), следом сам портрет.
    assert items[0].text == "Назвать персонажа"
    assert items[0].get("waitForFinish") == "False"
    assert items[1].get("type") == "image"
    assert items[1].text.endswith("_frame.avif")


def test_mixed_quotas_split_frames_chars_and_songs():
    """Кадры и персонажи делят пак вместе с песнями по своим весам."""
    s = PackSettings(rounds=1, themes=2, questions=6, pct_songs=25, pct_frames=50, pct_chars=25)
    q = s.question_quotas
    assert sum(q.values()) == 12
    # 1 песня : 2 кадра : 1 персонаж → 3 песни, 6 кадров, 3 персонажа.
    assert q[FRAME_KIND] == 6
    assert q[CHAR_KIND] == 3
    assert sum(q[k] for k in ("opening", "ending", "insert")) == 3


def test_hint_plays_together_with_song():
    """Подсказка идёт ПЕРЕД дорожкой и не ждёт её конца — иначе она
    показывалась бы уже после отрезка."""
    s = PackSettings(rounds=1, themes=1, questions=1, hint=True)
    root, ns = _parse(build_content_xml([make_candidate()], s))
    items = root.findall(".//s:param[@name='question']/s:item", ns)
    assert items[0].text == "Опенинг"
    assert items[0].get("waitForFinish") == "False"
    assert items[1].get("type") == "audio"


def test_hint_over_a_video_is_spoken_not_written():
    """У вопроса-ролика «Опенинг»/«Эндинг» ведущий ПРОИЗНОСИТ одновременно с
    видео: на экране надпись загородила бы картинку (просьба пользователя)."""
    s = PackSettings(rounds=1, themes=1, questions=1, song_video=True,
                     pct_songs=0, pct_videos=100, hint=True)
    cand = make_candidate()
    cand.kind, cand.has_video = VIDEO_KIND, True
    cand.media_base = "Пак(Тетрадь смерти)"
    root, ns = _parse(build_content_xml([cand], s))
    items = root.findall(".//s:param[@name='question']/s:item", ns)
    assert [i.get("type") for i in items] == [None, "video"]
    said = items[0]
    assert said.text == "Опенинг"
    assert said.get("placement") == "replic"      # устный текст, не подпись
    assert said.get("waitForFinish") == "False"   # одновременно с роликом


def test_video_hint_obeys_its_checkbox():
    """Галочка подсказки одна на всех: выключена — молчит и ведущий."""
    s = PackSettings(rounds=1, themes=1, questions=1, song_video=True,
                     pct_songs=0, pct_videos=100, hint=False)
    cand = make_candidate()
    cand.kind, cand.has_video = VIDEO_KIND, True
    cand.media_base = "Пак(Тетрадь смерти)"
    root, ns = _parse(build_content_xml([cand], s))
    items = root.findall(".//s:param[@name='question']/s:item", ns)
    assert [i.get("type") for i in items] == ["video"]


def test_hint_calls_insert_song_ost():
    s = PackSettings(rounds=1, themes=1, questions=1, hint=True)
    cand = make_candidate(song={"songType": "Insert Song"})
    cand.kind = "insert"
    root, ns = _parse(build_content_xml([cand], s))
    assert root.find(".//s:param[@name='question']/s:item", ns).text == "OST"


def test_media_files_named_after_title(tmp_path):
    """Файлы в паке зовутся «Сгенерировано в SI-HYX(Тайтл)», а не числами."""
    gen = AnimePackGenerator(PackSettings(), session=FakeSession({}))
    cand = make_candidate()
    cand.media_base = gen._media_base(cand)
    assert cand.audio_out == f"{MEDIA_NAME_PREFIX}(Тетрадь смерти).opus"
    assert cand.poster_file == f"{MEDIA_NAME_PREFIX}(Тетрадь смерти)_poster.avif"
    # Второй вопрос того же тайтла не должен делить файл с первым.
    other = make_candidate()
    other.media_base = gen._media_base(other)
    assert other.audio_out != cand.audio_out


@pytest.mark.parametrize("line,title", [
    ("Наруто OP1 (2002) — 『Song』", "Наруто"),
    ("Доктор Стоун (2019)", "Доктор Стоун"),
    ("Бляйч ED12", "Бляйч"),
    ("Тетрадь смерти (2006) — 『Лайт Ягами』", "Тетрадь смерти"),
])
def test_answer_title_strips_song_year_and_tag(line, title):
    assert answer_title(line) == title


def test_siq_exclusion_skips_same_franchise(tmp_path):
    """Франшизы из чужого пака в новый не попадают."""
    old = tmp_path / "старый.siq"
    s = PackSettings(rounds=1, themes=1, questions=1)
    cand = make_candidate()
    with zipfile.ZipFile(old, "w") as zf:
        zf.writestr("content.xml", build_content_xml([cand], s))
    assert "тетрадь смерти" in siq_answer_roots(str(old))

    gen = AnimePackGenerator(PackSettings(exclude_siq=[str(old)]),
                             session=FakeSession({}))
    gen.load_exclusions()
    assert not gen._accept_anime(make_anime(), 1535, set(), set())
    other = make_anime(russian="Стальной алхимик", name="Fullmetal Alchemist",
                       english="Fullmetal Alchemist", malId=5, franchise="fma")
    assert gen._accept_anime(other, 5, set(), set())


# ── Потолок веса пака и выбор общей базы ─────────────────────────
def test_pack_stops_when_budget_is_spent(monkeypatch):
    """Набранное уже перевалило за потолок — отбор прекращается сразу, даже
    если кандидаты ещё есть."""
    s = PackSettings(rounds=1, themes=1, questions=6, openings=6, endings=0,
                     inserts=0, parallel=1, random_mode=False,
                     similar_count=1, max_pack_mb=5,
                     users=[UserList("morr", "myanimelist", ["completed"])])
    pairs = [_pair(i, f"fr{i}") for i in range(1, 9)]
    gen = _generator(s, [p[0] for p in pairs], [p[1] for p in pairs],
                     user_ids={"morr": list(range(1, 9))})
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: True)
    # Каждый вопрос «весит» половину бюджета — после второго набор кончится.
    monkeypatch.setattr(gen, "_media_size",
                        lambda cand: int(gen._byte_budget) // 2 + 1)
    picked = gen.select_songs()
    assert len(picked) == 2


def test_pack_stops_before_it_grows_too_heavy(monkeypatch):
    """Ждать фактического перебора поздно: генератор смотрит на средний вес
    вопроса и останавливается, как только видно, что пак вылезет за потолок."""
    s = PackSettings(rounds=1, themes=1, questions=20, openings=20, endings=0,
                     inserts=0, parallel=1, random_mode=False,
                     similar_count=1, max_pack_mb=5,
                     users=[UserList("morr", "myanimelist", ["completed"])])
    pairs = [_pair(i, f"fr{i}") for i in range(1, 30)]
    gen = _generator(s, [p[0] for p in pairs], [p[1] for p in pairs],
                     user_ids={"morr": list(range(1, 30))})
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: True)
    # Десятая часть бюджета на вопрос: двадцать таких — вдвое больше потолка.
    monkeypatch.setattr(gen, "_media_size",
                        lambda cand: int(gen._byte_budget) // 10)
    picked = gen.select_songs()
    # Остановились на прогнозе (после «разогрева»), а не на фактическом переборе.
    assert 5 <= len(picked) <= 8
    assert gen._bytes_used < gen._byte_budget


def test_budget_warmup_does_not_stop_a_normal_pack(monkeypatch):
    """Лёгкий пак прогноз не трогает — все вопросы на месте."""
    s = PackSettings(rounds=1, themes=1, questions=6, openings=6, endings=0,
                     inserts=0, parallel=1, random_mode=False,
                     similar_count=1, max_pack_mb=150,
                     users=[UserList("morr", "myanimelist", ["completed"])])
    pairs = [_pair(i, f"fr{i}") for i in range(1, 9)]
    gen = _generator(s, [p[0] for p in pairs], [p[1] for p in pairs],
                     user_ids={"morr": list(range(1, 9))})
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: True)
    monkeypatch.setattr(gen, "_media_size", lambda cand: 700 * 1024)
    assert len(gen.select_songs()) == 6


def test_amq_base_is_only_for_song_packs():
    """Мастер-лист AMQ знает лишь тайтлы с песнями, поэтому пакам из кадров и
    персонажей база достаётся с Shikimori, что бы ни стояло в настройках."""
    songs = PackSettings(random_source="amq")
    assert songs.has_songs is True
    gen = AnimePackGenerator(songs, session=FakeSession({}))
    assert gen._random_source == "amq" and gen._ids_are_ann is True

    for kw in ({"pct_songs": 0, "pct_frames": 100},
               {"pct_songs": 0, "pct_chars": 100},
               {"pick_openings": False, "pick_endings": False,
                "pick_inserts": False}):
        s = PackSettings(random_source="amq", **kw)
        assert s.has_songs is False
        gen = AnimePackGenerator(s, session=FakeSession({}))
        assert gen._random_source == "shikimori"
        assert gen._ids_are_ann is False


def test_shikimori_is_the_default_base():
    assert PackSettings().random_source == "shikimori"


# ── Видео с AnimeThemes ──────────────────────────────────────────────────────
def test_animethemes_maps_tags_to_video_links():
    """Ролики раскладываются по метке «OP1»/«ED2» — вопросу нужен ровно тот
    опенинг, который выбран из AnisongDB."""
    payload = {"anime": [{
        "name": "Death Note",
        "resources": [{"site": "MyAnimeList", "external_id": 1535}],
        "animethemes": [
            {"type": "OP", "sequence": 1, "song": {"title": "the WORLD"},
             "animethemeentries": [{"videos": [
                 {"link": "https://v/DN-OP1-1080.webm", "resolution": 1080,
                  "size": 45_000_000},
                 {"link": "https://v/DN-OP1-720.webm", "resolution": 720,
                  "size": 20_000_000}]}]},
            {"type": "ED", "sequence": 2, "song": {"title": "Zetsubou Billy"},
             "animethemeentries": [{"videos": [
                 {"link": "https://v/DN-ED2.webm", "resolution": 480,
                  "size": 9_000_000}]}]},
        ]}]}
    session = FakeSession([("api.animethemes.moe/anime",
                            FakeResponse(json_data=payload))])
    out = api.AnimeThemesApi(session).themes_by_mal_ids([1535])
    assert set(out[1535]) == {"OP1", "ED2"}
    # Из двух пригодных вариантов берём тот, что легче качать.
    assert out[1535]["OP1"]["url"] == "https://v/DN-OP1-720.webm"
    assert out[1535]["ED2"]["resolution"] == 480


def test_video_question_replaces_audio_in_xml():
    s = PackSettings(rounds=1, themes=1, questions=1, song_video=True,
                     video_cut=15, hint=False)
    cand = make_candidate()
    cand.has_video = True
    cand.media_base = "Пак(Тетрадь смерти)"
    root, ns = _parse(build_content_xml([cand], s))
    items = root.findall(".//s:param[@name='question']/s:item", ns)
    assert [i.get("type") for i in items] == ["video"]
    assert items[0].text == "Пак(Тетрадь смерти).mp4"
    assert items[0].get("duration") == "00:00:15"
    # Ответ на месте: ролик заменяет только сам вопрос.
    assert root.find(".//s:right/s:answer", ns).text.startswith("Тетрадь смерти")


def test_video_falls_back_to_audio(monkeypatch):
    """Ролика для этой песни нет — вопрос всё равно состоится, просто звуком."""
    s = PackSettings(song_video=True, pct_videos=100, pct_songs=0)
    gen = AnimePackGenerator(s, session=FakeSession({}))
    gen.folder = "."
    cand = make_candidate()
    cand.kind = VIDEO_KIND
    monkeypatch.setattr(gen, "_theme_video", lambda c: "")
    calls = []
    monkeypatch.setattr(gen, "download_audio", lambda c: calls.append(c) or True)
    monkeypatch.setattr(gen, "download_images", lambda c: None)
    monkeypatch.setattr(gen, "_media_base", lambda c: "base")
    assert gen._fetch_media(cand) is True
    assert cand.has_video is False and len(calls) == 1


def test_video_start_is_random_like_a_song(monkeypatch):
    """Отрезок ролика берётся со случайной секунды — как отрезок песни, а не
    всегда с пятой (просьба пользователя). Заставку студии в начале опенинга
    по-прежнему пропускаем."""
    import random as _random
    gen = AnimePackGenerator(PackSettings(video_cut=15),
                             session=FakeSession({}),
                             rng=_random.Random(1234))
    monkeypatch.setattr(gen, "_video_seconds", lambda url: 90.0)
    cand = make_candidate()
    starts = {gen._video_start(cand, "u", 15) for _ in range(30)}
    assert len(starts) > 1                       # не одна и та же секунда
    assert min(starts) >= 5 and max(starts) <= 75


def test_video_start_falls_back_when_length_unknown(monkeypatch):
    """ffprobe не ответил — начало прежнее: 5 с у опенинга, 0 у эндинга."""
    gen = AnimePackGenerator(PackSettings(video_cut=15), session=FakeSession({}))
    monkeypatch.setattr(gen, "_video_seconds", lambda url: 0.0)
    op = make_candidate()
    ed = make_candidate(song={"songType": "Ending 1"})
    assert gen._video_start(op, "u", 15) == 5
    assert gen._video_start(ed, "u", 15) == 0
    # Ролик короче отрезка — берём его с самого начала, иначе выйдет пустышка.
    monkeypatch.setattr(gen, "_video_seconds", lambda url: 12.0)
    assert gen._video_start(op, "u", 15) == 0


def test_video_download_seeks_to_the_random_start(monkeypatch, tmp_path):
    """Случайное начало уходит в -ss ffmpeg, а повтор после неудачи режет
    ролик с нуля — вдруг длительность мы угадали неверно."""
    gen = AnimePackGenerator(PackSettings(video_cut=15), session=FakeSession({}))
    os.makedirs(tmp_path / "Video", exist_ok=True)
    gen.folder = str(tmp_path)
    cand = make_candidate()
    cand.media_base = "base"
    monkeypatch.setattr(gen, "_theme_video", lambda c: "https://v/op.webm")
    monkeypatch.setattr(gen, "_video_start", lambda c, u, d: 37)
    monkeypatch.setattr(animepack.time, "sleep", lambda *_: None)
    seeks = []

    def fake_run(cmd, timeout=180.0):
        seeks.append(cmd[cmd.index("-ss") + 1])
        return 1, "нет"

    monkeypatch.setattr(gen, "_run_killable", fake_run)
    assert gen.download_video(cand) is False
    assert seeks[0] == "37" and set(seeks[1:]) == {"0"}


def test_video_seconds_asks_ffprobe_once(monkeypatch):
    """Длительность спрашивается у ffprobe и кэшируется по ссылке."""
    gen = AnimePackGenerator(PackSettings(), session=FakeSession({}))
    calls = []

    def fake_run(cmd, timeout=180.0):
        calls.append(cmd)
        return 0, "89.567\n", ""

    monkeypatch.setattr(gen, "_run_capture", fake_run)
    assert gen._video_seconds("https://v/op.webm") == pytest.approx(89.567)
    assert gen._video_seconds("https://v/op.webm") == pytest.approx(89.567)
    assert len(calls) == 1
    assert "format=duration" in calls[0]


def test_video_encode_args_follow_settings():
    gen = AnimePackGenerator(PackSettings(video_crf=40, video_preset=6),
                             session=FakeSession({}))
    args = gen.video_encode_args()
    assert "libsvtav1" in args                      # тот же кодер, что в «Обработке»
    assert args[args.index("-crf") + 1] == "40"
    assert args[args.index("-preset") + 1] == "6"
    assert any("scale=-2:720" in a for a in args)


def test_video_defaults_are_fifteen_seconds_crf45_fastest():
    s = PackSettings()
    assert (s.video_cut, s.video_crf, s.video_preset) == (15, 45, 13)


def test_video_share_lives_in_the_mix_slider():
    """Ролики — такая же доля ползунка, как кадры: своя квота вопросов."""
    s = PackSettings(rounds=1, themes=1, questions=10, song_video=True,
                     pct_songs=50, pct_videos=30, pct_frames=20, pct_chars=0)
    assert s.percents == (50, 30, 20, 0, 0)
    q = s.question_quotas
    assert q[VIDEO_KIND] == 3 and q[FRAME_KIND] == 2
    assert sum(q[k] for k in ("opening", "ending", "insert")) == 5
    assert sum(q.values()) == 10


def test_video_share_only_counts_with_the_checkbox():
    """Снятая галочка «Вопрос — ролик» убирает долю роликов совсем."""
    s = PackSettings(rounds=1, themes=1, questions=10, song_video=False,
                     pct_songs=50, pct_videos=50)
    assert s.percents == (100, 0, 0, 0, 0)
    assert s.question_quotas[VIDEO_KIND] == 0
    # А роликам нужна песня ровно так же, как обычному вопросу.
    s.song_video, s.pct_songs, s.pct_videos = True, 0, 100
    assert s.has_songs is True and s.only_kind is None


def test_legacy_song_video_becomes_a_full_video_share():
    """Старая галочка делала роликами ВСЕ песни — читаем её как 100% роликов."""
    s = PackSettings.from_dict({"song_video": True, "pct_songs": 100})
    assert s.percents == (0, 100, 0, 0, 0)
    # Явно сохранённая доля старую галочку не переписывает.
    s = PackSettings.from_dict({"song_video": True, "pct_songs": 70,
                                "pct_videos": 30})
    assert s.percents == (70, 30, 0, 0, 0)


def test_video_question_answer_is_the_same_as_a_song():
    """Просьба пользователя: ролик отличается от песни только самим вопросом —
    ответ (тег, год, песня, исполнитель, постер) у них общий."""
    s = PackSettings(rounds=1, themes=1, questions=2, song_video=True,
                     pct_songs=50, pct_videos=50, hint=True)
    song = make_candidate(anime={"malId": 1})
    video = make_candidate(song={"annSongId": 9}, anime={"malId": 1})
    video.kind, video.has_video = VIDEO_KIND, True
    song.has_poster = video.has_poster = True
    root, ns = _parse(build_content_xml([song, video], s))
    answers = [[a.text for a in q.findall("s:right/s:answer", ns)]
               for q in root.findall(".//s:question", ns)]
    assert answers[0] == answers[1]
    assert video.main_answer == song.main_answer
    # «Опенинг» звучит у обоих, но по-разному: у песни это подпись на экране, у
    # ролика — устный текст ведущего (просьба пользователя).
    hints = root.findall(
        ".//s:param[@name='question']/s:item[@waitForFinish='False']", ns)
    assert [i.text for i in hints] == ["Опенинг", "Опенинг"]
    assert [i.get("placement") for i in hints] == [None, "replic"]
    # В ответе обоих — реплика с исполнителем и постер.
    for q in root.findall(".//s:question", ns):
        items = q.findall("s:params/s:param[@name='answer']/s:item", ns)
        assert items[0].text == "Исполнитель — 『Nightmare』"
        assert items[1].get("type") == "image"


def test_video_price_follows_its_song_type():
    """Ролик-эндинг стоит как эндинг: надбавка берётся от песни."""
    s = PackSettings(rounds=1, themes=1, questions=2)
    op = make_candidate(anime={"malId": 1})
    ed = make_candidate(song={"songType": "Ending 1", "annSongId": 2},
                        anime={"malId": 2})
    op.kind = ed.kind = VIDEO_KIND
    arrange_questions([op, ed], s)
    assert ed.price - op.price == 1


def test_video_audio_is_opus_like_every_other_track(monkeypatch):
    """Звук ролика кодируется тем же opus с нормализацией, что и песни."""
    s = PackSettings(song_video=True, video_cut=15)
    gen = AnimePackGenerator(s, session=FakeSession({}))
    gen.folder = "."
    cand = make_candidate()
    cand.kind = VIDEO_KIND
    seen = []
    monkeypatch.setattr("animepack.time.sleep", lambda *_a: None)
    monkeypatch.setattr(gen, "_theme_video", lambda c: "https://v/op.webm")
    monkeypatch.setattr(gen, "_run_killable",
                        lambda cmd, timeout=0: seen.append(cmd) or (1, "нет"))
    gen.download_video(cand)
    cmd = seen[0]
    assert cmd[cmd.index("-c:a") + 1] == "libopus"
    assert cmd[cmd.index("-b:a") + 1] == "192k"
    af = cmd[cmd.index("-af") + 1]
    assert af == gen.audio_filters(15)
    assert "loudnorm=I=-20.0" in af and "afade=t=out" in af


# ── Цена за сложность песни ──────────────────────────────────────────────────
@pytest.mark.parametrize("difficulty,bonus", [
    (100, 0), (90, 0), (50, 2), (5, 3), (0, 0), (None, 0),
])
def test_song_difficulty_bonus(difficulty, bonus):
    assert song_difficulty_bonus(difficulty) == bonus


def test_difficulty_bonus_only_for_songs():
    """Надбавка за сложность песни картинок не касается — у них её нет."""
    s = PackSettings(rounds=1, themes=1, questions=2, sort_by_index=True)
    song = make_candidate(song={"annSongId": 1, "songDifficulty": 5.0},
                          anime={"malId": 1})
    frame = make_candidate(song={"annSongId": 2, "songDifficulty": 5.0},
                           anime={"malId": 2})
    frame.kind = FRAME_KIND
    arrange_questions([song, frame], s)
    assert song.price - frame.price == 3


# ── Ползунок состава ─────────────────────────────────────────────────────────
def test_percents_normalise_and_split_all_questions():
    s = PackSettings(rounds=1, themes=1, questions=20,
                     pct_songs=60, pct_frames=25, pct_chars=15)
    assert s.percents == (60, 0, 25, 15, 0)
    q = s.question_quotas
    assert q[FRAME_KIND] == 5 and q[CHAR_KIND] == 3
    assert sum(q.values()) == 20
    # Доли, не дающие сотни, приводятся к ней.
    assert PackSettings(pct_songs=1, pct_frames=1,
                        pct_chars=2).percents == (25, 0, 25, 50, 0)


def test_legacy_mix_settings_become_percents():
    """Настройки, сохранённые до ползунка, читаются как доли."""
    assert PackSettings.from_dict({"frames_only": True}).percents == (0, 0, 100, 0, 0)
    assert PackSettings.from_dict({"chars_only": True}).percents == (0, 0, 0, 100, 0)
    assert PackSettings.from_dict(
        {"mix_frames": True, "mix_frames_per": 1}).percents == (50, 0, 50, 0, 0)
    # Новые настройки старые ключи не перебивают.
    assert PackSettings.from_dict(
        {"frames_only": True, "pct_songs": 100,
         "pct_frames": 0}).percents == (100, 0, 0, 0, 0)
