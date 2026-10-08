"""Генерация аниме-пака: ответы, цены, персонажи, квоты и подсказки."""
import os
import zipfile

import pytest

from conftest import FakeResponse, FakeSession

import animepack
import animepack_api as api
from animepack import (
    CHAR_KIND,
    FRAME_KIND,
    MEDIA_NAME_PREFIX,
    VIDEO_KIND,
    AnimePackGenerator,
    PackSettings,
    SongCandidate,
    UserList,
    arrange_questions,
    build_content_xml,
    filter_anime,
    index_level,
    song_kind,
    title_root,
    answer_title,
    siq_answer_roots,
)
from animepack_test_helpers import _forget_user_lists  # noqa: F401 — autouse-фикстура
from animepack_test_helpers import _generator, _pair, _parse, make_anime, make_candidate, make_song


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

def test_kind_price_step_is_fixed():
    """Эндинг ровно +2 к опенингу, OST ровно +4 (просьба пользователя).

    Узнаваемость у всех трёх одна и та же, сложность AMQ — сотня (надбавки за
    неё нет), так что видна ровно надбавка за тип песни."""
    s = PackSettings(rounds=1, themes=1, questions=3)
    cands = []
    for i, kind in enumerate(("Opening 1", "Ending 1", "Insert Song")):
        c = make_candidate(song={"annSongId": i + 1, "songType": kind,
                                 "songDifficulty": 100.0},
                           anime={"malId": i + 1})
        c.kind = song_kind(kind)
        cands.append(c)
    theme = arrange_questions(cands, s)
    base = animepack.price_for_level(cands[0].level)
    assert [c.price for c in theme[0]] == [base, base + 2, base + 4]

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
    (5_000_000, 1), (700_000, 1), (699_999, 2), (336_000, 2), (215_000, 3),
    (66_000, 5), (7_000, 7), (6_000, 8), (30, 14), (29, 15),
    (0, 15), (None, 15),
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
    # Буквенная приписка части серии: «Покемон XY: Хупа и столкновение веков»
    # и «Покемон: Хроники приключений» оказывались в одном паке.
    ("Покемон XY: Хупа и столкновение веков", "покемон"),
    ("Покемон: Хроники приключений", "покемон"),
    ("Dragon Ball GT", "dragon ball"),
    # Обычное последнее слово с заглавной так не режется.
    ("Мастера меча онлайн", "мастера меча онлайн"),
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
    # Задание «Назвать персонажа» запускается вместе с портретом,
    # чтобы его можно было отличить от обычного кадра.
    assert items[0].text == "Назвать персонажа"
    assert items[0].get("duration") is None
    assert items[0].get("waitForFinish") == "False"
    assert items[1].get("type") == "image"
    assert items[1].get("duration") == "00:00:04"
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
    """Вопрос, который не влезает в остаток потолка, в пак не берётся: пак
    не перерастает потолок, даже если кандидаты ещё есть."""
    s = PackSettings(rounds=1, themes=1, questions=6, openings=6, endings=0,
                     inserts=0, parallel=1, random_mode=False,
                     similar_count=1, max_pack_mb=5,
                     users=[UserList("morr", "myanimelist", ["completed"])])
    pairs = [_pair(i, f"fr{i}") for i in range(1, 9)]
    gen = _generator(s, [p[0] for p in pairs], [p[1] for p in pairs],
                     user_ids={"morr": list(range(1, 9))})
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: True)
    # Каждый вопрос «весит» чуть больше половины бюджета — второй уже не влезет.
    monkeypatch.setattr(gen, "_media_size",
                        lambda cand: int(gen._byte_budget) // 2 + 1)
    picked = gen.select_songs()
    assert len(picked) == 1
    assert gen._bytes_used <= gen._byte_budget

def test_pack_stops_before_it_grows_too_heavy(monkeypatch):
    """Вопросы берутся, пока помещаются под потолок: прогноз по первым
    вопросам не обрывает пак раньше времени (тяжёлое начало ещё не значит,
    что остальные вопросы будут такими же)."""
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
    # Десятый уже не влезает с запасом на служебные файлы архива.
    assert len(picked) == 9
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
