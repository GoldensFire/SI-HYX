# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_forget_user_lists. Public namespace: test_animepack."""
import test_animepack as _api


@_api.pytest.fixture(autouse=True)
def _forget_user_lists():
    """Кэш списков пользователей живёт в модуле и переживает тест — чистим его,
    иначе ники из соседнего теста «уже спрошены» и сеть не трогается вовсе."""
    _api.clear_user_list_cache()
    yield
    _api.clear_user_list_cache()

_forget_user_lists.__module__ = _api.__name__
_api._forget_user_lists = _forget_user_lists

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

make_song.__module__ = _api.__name__
_api.make_song = make_song

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

make_anime.__module__ = _api.__name__
_api.make_anime = make_anime

def make_candidate(**over):
    song = _api.make_song(**over.pop("song", {}))
    anime = _api.make_anime(**over.pop("anime", {}))
    cand = _api.SongCandidate(song=song, anime=anime,
                         kind=_api.song_kind(song["songType"]) or "opening",
                         **over)
    return cand

make_candidate.__module__ = _api.__name__
_api.make_candidate = make_candidate

# ── Чистые функции ───────────────────────────────────────────────────────────
@_api.pytest.mark.parametrize("difficulty,price", [
    (100, 6), (90, 6), (89.9, 8), (75, 9), (55, 12), (10, 18), (0, 20), (-1, 1),
    (None, 1), ("нет", 1),
])
def test_price_for_difficulty(difficulty, price):
    assert _api.price_for_difficulty(difficulty) == price

test_price_for_difficulty.__module__ = _api.__name__
_api.test_price_for_difficulty = test_price_for_difficulty

def test_fmt_duration_pads_and_clamps():
    # ASPG склеивал строку руками и выдавал «00:00:3»; отрицательное время
    # получалось, когда картинки просили больше секунд, чем длится отрезок.
    assert _api.fmt_duration(3) == "00:00:03"
    assert _api.fmt_duration(65) == "00:01:05"
    assert _api.fmt_duration(0) == "00:00:01"
    assert _api.fmt_duration(-7) == "00:00:01"
    assert _api.fmt_duration(None) == "00:00:01"

test_fmt_duration_pads_and_clamps.__module__ = _api.__name__
_api.test_fmt_duration_pads_and_clamps = test_fmt_duration_pads_and_clamps

def test_song_kind():
    assert _api.song_kind("Opening 1") == "opening"
    assert _api.song_kind("Ending 12") == "ending"
    assert _api.song_kind("Insert Song") == "insert"
    assert _api.song_kind("Что-то") is None

test_song_kind.__module__ = _api.__name__
_api.test_song_kind = test_song_kind

def test_filter_song_defaults_pass():
    assert _api.filter_song(_api.make_song(), _api.PackSettings()) is True

test_filter_song_defaults_pass.__module__ = _api.__name__
_api.test_filter_song_defaults_pass = test_filter_song_defaults_pass

def test_filter_song_bool_dub_and_rebroadcast():
    """AnisongDB перешёл на true/false: сравнение с 1 (как в ASPG) не работало."""
    s = _api.PackSettings()
    s.allow_dub = False
    assert _api.filter_song(_api.make_song(isDub=True), s) is False
    assert _api.filter_song(_api.make_song(isDub=1), s) is False
    s.allow_dub = True
    assert _api.filter_song(_api.make_song(isDub=True), s) is True

    s = _api.PackSettings()
    s.allow_rebroadcast = False
    assert _api.filter_song(_api.make_song(isRebroadcast=True), s) is False
    s.allow_rebroadcast = True
    assert _api.filter_song(_api.make_song(isRebroadcast=True), s) is True

test_filter_song_bool_dub_and_rebroadcast.__module__ = _api.__name__
_api.test_filter_song_bool_dub_and_rebroadcast = test_filter_song_bool_dub_and_rebroadcast

def test_filter_song_category_and_difficulty():
    s = _api.PackSettings()
    s.categories = dict(s.categories, standard=False)
    assert _api.filter_song(_api.make_song(), s) is False
    s = _api.PackSettings()
    s.difficulty_min, s.difficulty_max = 0, 50
    assert _api.filter_song(_api.make_song(songDifficulty=85.0), s) is False
    assert _api.filter_song(_api.make_song(songDifficulty=40.0), s) is True

test_filter_song_category_and_difficulty.__module__ = _api.__name__
_api.test_filter_song_category_and_difficulty = test_filter_song_category_and_difficulty

def test_filter_song_requires_media_fields():
    s = _api.PackSettings()
    assert _api.filter_song(_api.make_song(audio=None), s) is False
    assert _api.filter_song(_api.make_song(songLength=None), s) is False
    assert _api.filter_song(_api.make_song(songType="Ерунда"), s) is False
    assert _api.filter_song(_api.make_song(linked_ids={}), s) is False
    assert _api.filter_song(_api.make_song(songDifficulty=None), s) is False

test_filter_song_requires_media_fields.__module__ = _api.__name__
_api.test_filter_song_requires_media_fields = test_filter_song_requires_media_fields

def test_filter_anime_ranges():
    s = _api.PackSettings()
    assert _api.filter_anime(_api.make_anime(), s) is True
    assert _api.filter_anime(_api.make_anime(kind="music"), s) is False
    assert _api.filter_anime(_api.make_anime(airedOn={"year": 1900}), s) is False
    s2 = _api.PackSettings(); s2.score_from = 9.0
    assert _api.filter_anime(_api.make_anime(), s2) is False
    assert _api.filter_anime(_api.make_anime(poster={}), s) is False
    assert _api.filter_anime(_api.make_anime(malId=None), s) is False

test_filter_anime_ranges.__module__ = _api.__name__
_api.test_filter_anime_ranges = test_filter_anime_ranges

def test_filter_anime_screenshots_only_when_images_needed():
    """Скриншоты нужны только под коллаж; ASPG требовал их всегда."""
    s = _api.PackSettings()
    assert _api.filter_anime(_api.make_anime(screenshots=[]), s) is True
    s.images = True
    assert _api.filter_anime(_api.make_anime(screenshots=[]), s) is False
    assert _api.filter_anime(_api.make_anime(), s) is True

test_filter_anime_screenshots_only_when_images_needed.__module__ = _api.__name__
_api.test_filter_anime_screenshots_only_when_images_needed = test_filter_anime_screenshots_only_when_images_needed

def test_filter_anime_genres_include_exclude():
    s = _api.PackSettings()
    s.genres_exclude = [40]
    assert _api.filter_anime(_api.make_anime(), s) is False
    s = _api.PackSettings()
    s.genres_include = [27, 999]
    s.genres_partial = True
    assert _api.filter_anime(_api.make_anime(), s) is True
    s.genres_partial = False           # нужны ВСЕ выбранные
    assert _api.filter_anime(_api.make_anime(), s) is False

test_filter_anime_genres_include_exclude.__module__ = _api.__name__
_api.test_filter_anime_genres_include_exclude = test_filter_anime_genres_include_exclude

def test_franchise_key_unique_for_empty():
    a = _api.make_anime(franchise="", malId=1)
    b = _api.make_anime(franchise="", malId=2)
    assert _api.franchise_key(a) != _api.franchise_key(b)
    assert _api.franchise_key(_api.make_anime()) == "death_note"

test_franchise_key_unique_for_empty.__module__ = _api.__name__
_api.test_franchise_key_unique_for_empty = test_franchise_key_unique_for_empty

def test_song_kinds_are_a_ratio_not_a_count():
    """Опенинги/эндинги/OST — это ДОЛИ (ползунок), а не штуки: сколько бы ни
    стояло в них, они ужимаются под число песенных вопросов, и «распределите
    ещё N» больше не бывает."""
    s = _api.PackSettings(rounds=1, themes=1, questions=10)
    s.openings, s.endings, s.inserts = 10, 0, 0
    assert not any("распределите" in p for p in s.validate())
    assert s.question_quotas["opening"] == 10
    s.openings, s.endings, s.inserts = 50, 30, 20
    q = s.question_quotas
    assert (q["opening"], q["ending"], q["insert"]) == (5, 3, 2)

test_song_kinds_are_a_ratio_not_a_count.__module__ = _api.__name__
_api.test_song_kinds_are_a_ratio_not_a_count = test_song_kinds_are_a_ratio_not_a_count

def test_validate_images_longer_than_cut():
    s = _api.PackSettings(images=True, images_time=25, audio_cut=20)
    assert any("раньше, чем кончится песня" in p for p in s.validate())

test_validate_images_longer_than_cut.__module__ = _api.__name__
_api.test_validate_images_longer_than_cut = test_validate_images_longer_than_cut

def test_settings_roundtrip():
    s = _api.PackSettings(title="Мой пак", rounds=2, images=True,
                     users=[_api.UserList("morr", "shikimori", ["completed"])],
                     genres_include=[1, 2])
    back = _api.PackSettings.from_dict(s.to_dict())
    assert back.title == "Мой пак"
    assert back.rounds == 2 and back.images is True
    assert back.users[0].username == "morr"
    assert back.users[0].source == "shikimori"
    assert back.genres_include == [1, 2]

test_settings_roundtrip.__module__ = _api.__name__
_api.test_settings_roundtrip = test_settings_roundtrip

# ── content.xml ──────────────────────────────────────────────────────────────
def _parse(xml_bytes):
    root = _api.ET.fromstring(xml_bytes)
    ns = {"s": "https://github.com/VladimirKhil/SI/blob/master/assets/siq_5.xsd"}
    return root, ns

_parse.__module__ = _api.__name__
_api._parse = _parse

def test_build_content_xml_structure():
    s = _api.PackSettings(rounds=1, themes=1, questions=2, openings=2, endings=0, inserts=0)
    # Тайтл у обоих один и тот же, поэтому база цены одинаковая, а расходятся
    # они ровно надбавкой за сложность AMQ: у лёгкой песни её нет, у трудной —
    # все десять очков.
    easy = _api.make_candidate(song={"songDifficulty": 95.0})
    hard = _api.make_candidate(song={"songDifficulty": 5.0, "annSongId": 9})
    easy.has_poster = hard.has_poster = True
    root, ns = _api._parse(_api.build_content_xml([hard, easy], s))

    assert root.get("version") == "5"
    # Название заканчивается средней сложностью пака: «… (Ур. 4)».
    assert root.get("name").startswith(s.title + " (Ур. ")
    assert root.get("id") and root.get("date")
    questions = root.findall(".//s:question", ns)
    assert len(questions) == 2
    # Внутри темы вопросы идут по возрастанию цены (в ASPG порядок был случайный).
    base = _api.animepack.price_for_level(easy.level)
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

test_build_content_xml_structure.__module__ = _api.__name__
_api.test_build_content_xml_structure = test_build_content_xml_structure

def test_build_content_xml_images_and_hint():
    s = _api.PackSettings(rounds=1, themes=1, questions=1, images=True, images_time=7,
                     audio_cut=20, hint=True)
    cand = _api.make_candidate()
    cand.has_collage = True
    root, ns = _api._parse(_api.build_content_xml([cand], s))
    audio = root.find(".//s:item[@type='audio']", ns)
    assert audio.get("duration") is None             # таймера у дорожки нет
    img = root.find(".//s:param[@name='question']/s:item[@type='image']", ns)
    assert img is not None and img.get("duration") == "00:00:07"
    texts = [i.text for i in root.findall(".//s:param[@name='question']/s:item", ns)]
    assert "Опенинг" in texts

test_build_content_xml_images_and_hint.__module__ = _api.__name__
_api.test_build_content_xml_images_and_hint = test_build_content_xml_images_and_hint

def test_build_content_xml_skips_missing_media():
    """Коллаж/постер не скачались — ссылок на них в XML быть не должно."""
    s = _api.PackSettings(rounds=1, themes=1, questions=1, images=True)
    cand = _api.make_candidate()          # has_poster / has_collage = False
    root, ns = _api._parse(_api.build_content_xml([cand], s))
    assert root.find(".//s:item[@type='image']", ns) is None
    audio = root.find(".//s:item[@type='audio']", ns)
    assert audio.get("duration") is None

test_build_content_xml_skips_missing_media.__module__ = _api.__name__
_api.test_build_content_xml_skips_missing_media = test_build_content_xml_skips_missing_media

def test_build_content_xml_answer_text():
    """Основной ответ — «Название (год) — 『Песня』», дальше идут синонимы."""
    s = _api.PackSettings(rounds=1, themes=1, questions=1)
    cand = _api.make_candidate(users=["morr", "kao"])
    root, ns = _api._parse(_api.build_content_xml([cand], s))
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

test_build_content_xml_answer_text.__module__ = _api.__name__
_api.test_build_content_xml_answer_text = test_build_content_xml_answer_text

def test_answer_replic_is_artist_without_lists():
    """Без списков людей реплика ведущего — исполнитель песни."""
    s = _api.PackSettings(rounds=1, themes=1, questions=1)
    root, ns = _api._parse(_api.build_content_xml([_api.make_candidate()], s))
    replics = root.findall(".//s:param[@name='answer']/s:item[@placement='replic']", ns)
    assert [r.text for r in replics] == [
        "Исполнитель — 『Nightmare』 · Сложность AMQ — 85 · Рейтинг MAL — 『8.60⭐』"]

test_answer_replic_is_artist_without_lists.__module__ = _api.__name__
_api.test_answer_replic_is_artist_without_lists = test_answer_replic_is_artist_without_lists

def test_answer_year_not_doubled():
    """Shikimori держит год прямо в названии части тайтлов — второй раз его
    дописывать нельзя."""
    cand = _api.make_candidate(anime={"russian": "Могучий Атом (2003)",
                                 "airedOn": {"year": 2003}})
    assert cand.main_answer == "Могучий Атом OP1 (2003) — 『the WORLD』"

test_answer_year_not_doubled.__module__ = _api.__name__
_api.test_answer_year_not_doubled = test_answer_year_not_doubled

def test_answer_without_song_is_just_title():
    cand = _api.make_candidate(song={"songName": ""})
    assert cand.main_answer == "Тетрадь смерти OP1 (2006)"

test_answer_without_song_is_just_title.__module__ = _api.__name__
_api.test_answer_without_song_is_just_title = test_answer_without_song_is_just_title

def test_answer_content_has_no_text_block():
    """На экране в ответе только постер: подпись-плашка больше не рисуется, а
    исполнитель уходит в реплику ведущего (как в паках пользователя)."""
    s = _api.PackSettings(rounds=1, themes=1, questions=1)
    cand = _api.make_candidate()
    cand.has_poster = True
    root, ns = _api._parse(_api.build_content_xml([cand], s))
    items = root.findall(".//s:param[@name='answer']/s:item", ns)
    assert [i.get("type") or i.get("placement") for i in items] == ["replic", "image"]
    assert items[0].text == (
        "Исполнитель — 『Nightmare』 · Сложность AMQ — 85 · Рейтинг MAL — 『8.60⭐』")

test_answer_content_has_no_text_block.__module__ = _api.__name__
_api.test_answer_content_has_no_text_block = test_answer_content_has_no_text_block
