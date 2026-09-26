# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""test_answer_bare_russian_title_goes_last. Public namespace: test_animepack."""
import test_animepack as _api


def test_answer_bare_russian_title_goes_last():
    """Сразу после «Название (год) — 『Песня』» голое название смотрится
    копией, поэтому идёт в самый конец — после ромадзи и синонимов."""
    cand = _api.make_candidate()
    variants = cand.answer_variants()
    assert variants[0] == "Тетрадь смерти OP1 (2006) — 『the WORLD』"
    assert variants[1] == "Death Note"                 # ромадзи
    assert variants[-1] == "Тетрадь смерти"            # копия — в хвосте

test_answer_bare_russian_title_goes_last.__module__ = _api.__name__
_api.test_answer_bare_russian_title_goes_last = test_answer_bare_russian_title_goes_last

def test_shuffle_questions_keeps_given_order():
    """«В разнобой»: вопросы идут как набрались, а не по возрастанию цены."""
    s = _api.PackSettings(rounds=1, themes=1, questions=3, shuffle_questions=True)
    hard = _api.make_candidate(song={"annSongId": 1, "songDifficulty": 10.0},
                          anime={"malId": 1, "russian": "Первое"})
    easy = _api.make_candidate(song={"annSongId": 2, "songDifficulty": 95.0},
                          anime={"malId": 2, "russian": "Второе"})
    mid = _api.make_candidate(song={"annSongId": 3, "songDifficulty": 50.0},
                         anime={"malId": 3, "russian": "Третье"})
    theme = _api.arrange_questions([hard, easy, mid], s)[0]
    assert [c.mal_id for c in theme] == [1, 2, 3]
    assert theme[0].price > theme[1].price          # цены НЕ по возрастанию
    s.shuffle_questions = False
    theme = _api.arrange_questions([hard, easy, mid], s)[0]
    assert [c.price for c in theme] == sorted(c.price for c in theme)

test_shuffle_questions_keeps_given_order.__module__ = _api.__name__
_api.test_shuffle_questions_keeps_given_order = test_shuffle_questions_keeps_given_order

def test_package_author():
    """В авторах пака — откуда он взялся."""
    s = _api.PackSettings(rounds=1, themes=1, questions=1)
    root, ns = _api._parse(_api.build_content_xml([_api.make_candidate()], s))
    assert root.find(".//s:info/s:authors/s:author", ns).text == \
        "Сгенерировано в программе SI-HYX"

test_package_author.__module__ = _api.__name__
_api.test_package_author = test_package_author

def test_answer_poster_is_not_simultaneous():
    """У постера не должно быть режима «воспроизводить одновременно»
    (waitForFinish="False") — просьба пользователя."""
    s = _api.PackSettings(rounds=1, themes=1, questions=1)
    cand = _api.make_candidate()
    cand.has_poster = True
    root, ns = _api._parse(_api.build_content_xml([cand], s))
    poster = root.find(".//s:param[@name='answer']/s:item[@type='image']", ns)
    assert poster.get("waitForFinish") is None
    assert poster.get("duration") == "00:00:03"

test_answer_poster_is_not_simultaneous.__module__ = _api.__name__
_api.test_answer_poster_is_not_simultaneous = test_answer_poster_is_not_simultaneous

def test_kind_price_step_is_fixed():
    """Эндинг ровно +2 к опенингу, OST ровно +4 (просьба пользователя).

    Узнаваемость у всех трёх одна и та же, сложность AMQ — сотня (надбавки за
    неё нет), так что видна ровно надбавка за тип песни."""
    s = _api.PackSettings(rounds=1, themes=1, questions=3)
    cands = []
    for i, kind in enumerate(("Opening 1", "Ending 1", "Insert Song")):
        c = _api.make_candidate(song={"annSongId": i + 1, "songType": kind,
                                 "songDifficulty": 100.0},
                           anime={"malId": i + 1})
        c.kind = _api.song_kind(kind)
        cands.append(c)
    theme = _api.arrange_questions(cands, s)
    base = _api.animepack.price_for_level(cands[0].level)
    assert [c.price for c in theme[0]] == [base, base + 2, base + 4]

test_kind_price_step_is_fixed.__module__ = _api.__name__
_api.test_kind_price_step_is_fixed = test_kind_price_step_is_fixed

def test_kind_price_step_opening_cheaper_than_insert():
    """Опенинг < эндинг < вставка при одинаковой сложности."""
    s = _api.PackSettings(rounds=1, themes=1, questions=3)
    op = _api.make_candidate(song={"annSongId": 1, "songType": "Opening 1"})
    ed = _api.make_candidate(song={"annSongId": 2, "songType": "Ending 1"})
    ins = _api.make_candidate(song={"annSongId": 3, "songType": "Insert Song"})
    for c, kind in ((op, "opening"), (ed, "ending"), (ins, "insert")):
        c.kind = kind
    theme = _api.arrange_questions([ins, ed, op], s)[0]
    assert [c.kind for c in theme] == ["opening", "ending", "insert"]
    assert theme[0].price < theme[1].price < theme[2].price

test_kind_price_step_opening_cheaper_than_insert.__module__ = _api.__name__
_api.test_kind_price_step_opening_cheaper_than_insert = test_kind_price_step_opening_cheaper_than_insert

def test_audio_filters_match_processing_tab():
    """Нормализация -20/11/-1.5, затухание в конце и фикс раскладки под opus."""
    from animepack import OPUS_LAYOUT_FIX, AnimePackGenerator as G
    af = G.audio_filters(20)
    assert af.startswith("loudnorm=I=-20.0:LRA=11.0:TP=-1.5,")
    assert "afade=t=out:st=19.000:d=1.0" in af
    assert af.endswith(OPUS_LAYOUT_FIX)
    # Отрезок короче фейда — старт затухания не уезжает в минус.
    assert "afade=t=out:st=0.000" in G.audio_filters(0.5)

test_audio_filters_match_processing_tab.__module__ = _api.__name__
_api.test_audio_filters_match_processing_tab = test_audio_filters_match_processing_tab

# ── Режим «только кадры» ─────────────────────────────────────────────────────
def test_frames_only_question_is_image_and_answer_has_no_song():
    s = _api.PackSettings(rounds=1, themes=1, questions=1, pct_songs=0, pct_frames=100)
    cand = _api.SongCandidate(song={}, anime=_api.make_anime(), kind=_api.FRAME_KIND)
    cand.has_frame = cand.has_poster = True
    root, ns = _api._parse(_api.build_content_xml([cand], s))
    q_items = root.findall(".//s:param[@name='question']/s:item", ns)
    assert len(q_items) == 1 and q_items[0].get("type") == "image"
    assert q_items[0].text == cand.frame_file == "1535_frame.avif"
    assert root.find(".//s:item[@type='audio']", ns) is None
    # Без песни ответ — просто название с годом.
    assert root.find(".//s:right/s:answer", ns).text == "Тетрадь смерти (2006)"

test_frames_only_question_is_image_and_answer_has_no_song.__module__ = _api.__name__
_api.test_frames_only_question_is_image_and_answer_has_no_song = test_frames_only_question_is_image_and_answer_has_no_song

def test_frames_only_takes_titles_without_shikimori_screenshots():
    """Кадры собираются ещё и с AniList/Kitsu, поэтому отсутствие скриншотов
    у Shikimori тайтл больше не выбраковывает."""
    s = _api.PackSettings(pct_songs=0, pct_frames=100)
    assert _api.filter_anime(_api.make_anime(screenshots=[]), s) is True
    assert _api.filter_anime(_api.make_anime(), s) is True
    # Квоты по типам песен в режиме кадров не проверяются.
    s = _api.PackSettings(pct_songs=0, pct_frames=100, openings=0, endings=0, inserts=0)
    assert not any("распределите" in p for p in s.validate())

test_frames_only_takes_titles_without_shikimori_screenshots.__module__ = _api.__name__
_api.test_frames_only_takes_titles_without_shikimori_screenshots = test_frames_only_takes_titles_without_shikimori_screenshots

def test_frames_only_candidates_skip_anisong_for_lists():
    """Списки людей дают MAL id сразу — AnisongDB в режиме кадров не нужен."""
    s = _api.PackSettings(random_mode=False, similar_count=1,
                     pct_songs=0, pct_frames=100,
                     users=[_api.UserList("morr", "myanimelist", ["completed"])])
    _s1, a1 = _api._pair(1, "naruto")
    _s2, a2 = _api._pair(2, "naruto")               # та же франшиза — отсеется
    _s3, a3 = _api._pair(3, "bleach")

    class Boom:
        def songs_by_mal_ids(self, ids):
            raise AssertionError("AnisongDB в режиме кадров не должен вызываться")
        songs_by_ann_ids = songs_by_mal_ids

    gen = _api._generator(s, [], [a1, a2, a3], user_ids={"morr": [1, 2, 3]})
    gen.anisong = Boom()
    cands = list(gen.iter_candidates())
    assert {c.mal_id for c in cands} == {1, 3}
    assert all(c.song == {} and c.kind == _api.FRAME_KIND for c in cands)

test_frames_only_candidates_skip_anisong_for_lists.__module__ = _api.__name__
_api.test_frames_only_candidates_skip_anisong_for_lists = test_frames_only_candidates_skip_anisong_for_lists

# ── Смешанный режим: кадры вперемешку с песнями ──────────────────────────────
def test_mixed_quotas_split_frames_and_songs():
    """На каждые 2 кадра — одна песня, а квоты по типам ужимаются под неё."""
    s = _api.PackSettings(rounds=1, themes=1, questions=9, pct_songs=34, pct_frames=66, openings=6, endings=2, inserts=1)
    q = s.question_quotas
    assert q[_api.FRAME_KIND] == 6
    assert sum(q[k] for k in ("opening", "ending", "insert")) == 3
    assert q["opening"] == 2                      # 6/9 от трёх песен
    # Поровну — 9 вопросов не делятся ровно, лишний достаётся картинкам.
    s.pct_songs, s.pct_frames = 50, 50
    assert s.question_quotas[_api.FRAME_KIND] == 5
    # Ползунок до упора — весь пак из кадров.
    s.pct_songs, s.pct_frames = 0, 100
    q = s.question_quotas
    assert q[_api.FRAME_KIND] == 9 and q[_api.CHAR_KIND] == 0
    assert sum(q[k] for k in ("opening", "ending", "insert")) == 0

test_mixed_quotas_split_frames_and_songs.__module__ = _api.__name__
_api.test_mixed_quotas_split_frames_and_songs = test_mixed_quotas_split_frames_and_songs

def test_mixed_select_songs_makes_both_kinds(monkeypatch):
    s = _api.PackSettings(rounds=1, themes=1, questions=6, pct_songs=34, pct_frames=66, openings=6, endings=0, inserts=0,
                     parallel=1, random_mode=False, similar_count=1,
                     users=[_api.UserList("morr", "shikimori", ["completed"])])
    pairs = [_api._pair(i, f"fr{i}") for i in range(1, 12)]
    gen = _api._generator(s, [p[0] for p in pairs], [p[1] for p in pairs],
                     user_ids={"morr": list(range(1, 12))})
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: True)
    picked = gen.select_songs()
    kinds = [c.kind for c in picked]
    assert len(picked) == 6
    assert kinds.count(_api.FRAME_KIND) == 4 and kinds.count("opening") == 2
    # У вопроса-кадра песни нет, даже если кандидат пришёл с ней.
    frame = next(c for c in picked if c.is_frame)
    assert frame.song_name == "" and frame.artist == ""
    assert frame.main_answer == frame.title_ru + " (2006)"

test_mixed_select_songs_makes_both_kinds.__module__ = _api.__name__
_api.test_mixed_select_songs_makes_both_kinds = test_mixed_select_songs_makes_both_kinds

def test_mixed_pack_xml_has_image_and_audio_questions():
    s = _api.PackSettings(rounds=1, themes=1, questions=2, pct_songs=50, pct_frames=50, hint=False)
    song = _api.make_candidate(song={"annSongId": 1}, anime={"malId": 1})
    frame = _api.make_candidate(song={"annSongId": 2}, anime={"malId": 2})
    frame.kind = _api.FRAME_KIND
    frame.has_frame = True
    root, ns = _api._parse(_api.build_content_xml([song, frame], s))
    q_items = root.findall(".//s:param[@name='question']/s:item", ns)
    assert {i.get("type") for i in q_items} == {"audio", "image"}

test_mixed_pack_xml_has_image_and_audio_questions.__module__ = _api.__name__
_api.test_mixed_pack_xml_has_image_and_audio_questions = test_mixed_pack_xml_has_image_and_audio_questions

def test_frame_question_works_without_shikimori_screenshots(monkeypatch):
    """Кадр добирается с AniList/Kitsu, так что тайтл без скриншотов Shikimori
    вопросом-кадром стать может."""
    s = _api.PackSettings(rounds=1, themes=1, questions=2, pct_songs=50, pct_frames=50, openings=2, endings=0, inserts=0,
                     parallel=1, random_mode=False, similar_count=1,
                     users=[_api.UserList("morr", "shikimori", ["completed"])])
    pairs = [_api._pair(i, f"fr{i}", anime_over={"screenshots": []})
             for i in range(1, 6)]
    gen = _api._generator(s, [p[0] for p in pairs], [p[1] for p in pairs],
                     user_ids={"morr": [1, 2, 3, 4, 5]})
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: True)
    picked = gen.select_songs()
    assert picked and any(c.is_frame for c in picked)

test_frame_question_works_without_shikimori_screenshots.__module__ = _api.__name__
_api.test_frame_question_works_without_shikimori_screenshots = test_frame_question_works_without_shikimori_screenshots

# ── Сложность по узнаваемости и франшизы ─────────────────────────────────────
@_api.pytest.mark.parametrize("index,level", [
    (5_000_000, 1), (700_000, 1), (699_999, 2), (336_000, 2), (215_000, 3),
    (66_000, 5), (7_000, 7), (6_000, 8), (30, 14), (29, 15),
    (0, 15), (None, 15),
])
def test_index_level(index, level):
    assert _api.index_level(index) == level

test_index_level.__module__ = _api.__name__
_api.test_index_level = test_index_level

@_api.pytest.mark.parametrize("name,root", [
    ("Доктор Стоун: Научное будущее. Часть 3", "доктор стоун"),
    ("Доктор Стоун", "доктор стоун"),
    ("Доктор Стоун 4", "доктор стоун"),
    ("Магическая битва 0. Фильм", "магическая битва"),
    ("Тетрадь смерти (2006)", "тетрадь смерти"),
    ("Ван-Пис", "ван-пис"),
    ("Тор", ""),                           # слишком короткий корень
    # Буквенная приписка части серии: «Покемон XY: Хупа и столкновение веков»
    # и «Покемон: Хроники приключений» оказывались в одном паке.
    ("Покемон XY: Хупа и столкновение веков", "покемон"),
    ("Покемон: Хроники приключений", "покемон"),
    ("Dragon Ball GT", "dragon ball"),
    # Обычное последнее слово с заглавной так не режется.
    ("Мастера меча онлайн", "мастера меча онлайн"),
])
def test_title_root(name, root):
    assert _api.title_root(name) == root

test_title_root.__module__ = _api.__name__
_api.test_title_root = test_title_root

def test_sequel_inherits_franchise_index():
    """Сиквел узнаваем настолько же, насколько оригинал серии."""
    sequel = _api.make_anime(malId=62568, russian="Доктор Стоун: Часть 3",
                        franchise="dr_stone", airedOn={"year": 2026},
                        statusesStats=[{"status": "completed", "count": 9098}])
    cand = _api.SongCandidate(song={}, anime=sequel, kind=_api.FRAME_KIND)
    alone = cand.level
    cand.franchise_index = 550_000.0
    assert cand.index == 550_000.0 and cand.own_index < 550_000.0
    assert cand.level < alone                    # стал заметно легче

test_sequel_inherits_franchise_index.__module__ = _api.__name__
_api.test_sequel_inherits_franchise_index = test_sequel_inherits_franchise_index

def test_level_filter_skips_too_easy(monkeypatch):
    """«Сложность пака от 2» выбрасывает самые заезженные тайтлы."""
    s = _api.PackSettings(rounds=1, themes=1, questions=2, level_min=2, level_max=10,
                     random_mode=False, similar_count=1, parallel=1,
                     users=[_api.UserList("morr", "shikimori", ["completed"])])
    hot = _api.make_anime(malId=1, id=1, russian="Мега известное", franchise="a",
                     airedOn={"year": 2024},
                     statusesStats=[{"status": "completed", "count": 500_000}])
    mid = _api.make_anime(malId=2, id=2, russian="Обычное такое", franchise="b",
                     airedOn={"year": 2015},
                     statusesStats=[{"status": "completed", "count": 20_000}])
    songs = [_api.make_song(linked_ids={"myanimelist": i}, annSongId=i * 10)
             for i in (1, 2)]
    gen = _api._generator(s, songs, [hot, mid], user_ids={"morr": [1, 2]})
    got = [c.mal_id for c in gen.iter_candidates()]
    assert got == [2]                            # первый — уровень 1, не подошёл

test_level_filter_skips_too_easy.__module__ = _api.__name__
_api.test_level_filter_skips_too_easy = test_level_filter_skips_too_easy

def test_dedup_by_title_root_when_franchise_missing():
    """У свежих тайтлов Shikimori иногда не проставил franchise — серия всё
    равно не должна попасть в пак дважды (в паке пользователя так пролезли две
    части «Доктора Стоуна»)."""
    s = _api.PackSettings(random_mode=False, similar_count=1,
                     pct_songs=0, pct_frames=100,
                     users=[_api.UserList("morr", "shikimori", ["completed"])])
    part2 = _api.make_anime(malId=61322, id=61322, franchise="dr_stone",
                       russian="Доктор Стоун: Научное будущее. Часть 2")
    part3 = _api.make_anime(malId=62568, id=62568, franchise=None,
                       russian="Доктор Стоун: Научное будущее. Часть 3")
    other = _api.make_anime(malId=7, id=7, franchise="bleach", russian="Блич")
    gen = _api._generator(s, [], [part2, part3, other], user_ids={"morr": [61322, 62568, 7]})
    got = [c.mal_id for c in gen.iter_candidates()]
    assert got == [61322, 7]

test_dedup_by_title_root_when_franchise_missing.__module__ = _api.__name__
_api.test_dedup_by_title_root_when_franchise_missing = test_dedup_by_title_root_when_franchise_missing

# ── Галочки сжатия ───────────────────────────────────────────────────────────
def test_compression_off_copies_source_stream():
    """Выключенное сжатие аудио = поток копируется: никакого второго
    перекодирования поверх того, что отдал сервер."""
    s = _api.PackSettings(compress_audio=False)
    gen = _api.AnimePackGenerator(s, session=object())
    assert gen.audio_encode_args(20) == ["-c:a", "copy"]
    args = _api.AnimePackGenerator(_api.PackSettings(), session=object()).audio_encode_args(20)
    assert "libopus" in args and "-af" in args

test_compression_off_copies_source_stream.__module__ = _api.__name__
_api.test_compression_off_copies_source_stream = test_compression_off_copies_source_stream

def test_compression_off_keeps_source_extensions(tmp_path):
    s = _api.PackSettings(compress_images=False, compress_audio=False)
    gen = _api.AnimePackGenerator(s, session=object())
    gen.folder = str(tmp_path)
    _api.os.makedirs(_api.os.path.join(gen.folder, "Images"), exist_ok=True)
    cand = _api.make_candidate(compress_audio=False, compress_images=False)
    assert cand.audio_out == "7868.mp3"           # как приехало с CDN
    name = gen._save_image(b"\x89PNG", f"{cand.media_key}_poster", ".png")
    assert name == "7868_poster.png"
    with open(_api.os.path.join(gen.folder, "Images", name), "rb") as f:
        assert f.read() == b"\x89PNG"             # байты не тронуты
    cand.poster_name = name
    assert cand.poster_file == "7868_poster.png"
    # Со сжатием имена всегда .opus/.avif.
    on = _api.make_candidate()
    assert on.audio_out == "7868.opus" and on.poster_file == "7868_poster.avif"

test_compression_off_keeps_source_extensions.__module__ = _api.__name__
_api.test_compression_off_keeps_source_extensions = test_compression_off_keeps_source_extensions

def test_url_ext_ignores_query():
    ext = _api.AnimePackGenerator._url_ext
    assert ext("https://shiki/original/1535.jpeg?1690") == ".jpeg"
    assert ext("https://shiki/x.webp") == ".webp"
    assert ext("https://shiki/no-ext") == ".jpg"

test_url_ext_ignores_query.__module__ = _api.__name__
_api.test_url_ext_ignores_query = test_url_ext_ignores_query
