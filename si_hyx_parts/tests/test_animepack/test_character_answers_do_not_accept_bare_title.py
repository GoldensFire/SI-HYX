# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""test_character_answers_do_not_accept_bare_title. Public namespace: test_animepack."""
import test_animepack as _api


def test_character_answers_do_not_accept_bare_title():
    """Голое название аниме не должно засчитываться: угадывают персонажа."""
    cand = _api.make_candidate()
    cand.kind = _api.CHAR_KIND
    cand.character = {"id": 7, "name": "Лайт Ягами", "main": True}
    variants = cand.answer_variants()
    assert variants[0] == "Тетрадь смерти (2006) — 『Лайт Ягами』"
    assert "Лайт Ягами" in variants
    assert "Тетрадь смерти" not in variants

test_character_answers_do_not_accept_bare_title.__module__ = _api.__name__
_api.test_character_answers_do_not_accept_bare_title = test_character_answers_do_not_accept_bare_title

def test_character_answers_list_every_name_of_the_character():
    """В ответе перебираются имена ПЕРСОНАЖА (в том числе «Прочие» с его
    страницы Shikimori), а не названия аниме."""
    cand = _api.make_candidate()
    cand.kind = _api.CHAR_KIND
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

test_character_answers_list_every_name_of_the_character.__module__ = _api.__name__
_api.test_character_answers_list_every_name_of_the_character = test_character_answers_list_every_name_of_the_character

def test_chars_only_quotas_and_xml():
    s = _api.PackSettings(rounds=1, themes=1, questions=2, pct_songs=0, pct_chars=100)
    assert s.question_quotas[_api.CHAR_KIND] == 2
    assert not any(v for k, v in s.question_quotas.items() if k != _api.CHAR_KIND)
    cand = _api.make_candidate()
    cand.kind = _api.CHAR_KIND
    cand.character = {"id": 1, "name": "Рюк", "main": False}
    cand.has_frame = True
    root, ns = _api._parse(_api.build_content_xml([cand], s))
    items = root.findall(".//s:param[@name='question']/s:item", ns)
    # Задание «Назвать персонажа» запускается вместе с портретом,
    # чтобы его можно было отличить от обычного кадра.
    assert items[0].text == "Назвать персонажа"
    assert items[0].get("duration") is None
    assert items[0].get("waitForFinish") == "False"
    assert items[1].get("type") == "image"
    assert items[1].get("duration") == "00:00:04"
    assert items[1].text.endswith("_frame.avif")

test_chars_only_quotas_and_xml.__module__ = _api.__name__
_api.test_chars_only_quotas_and_xml = test_chars_only_quotas_and_xml

def test_mixed_quotas_split_frames_chars_and_songs():
    """Кадры и персонажи делят пак вместе с песнями по своим весам."""
    s = _api.PackSettings(rounds=1, themes=2, questions=6, pct_songs=25, pct_frames=50, pct_chars=25)
    q = s.question_quotas
    assert sum(q.values()) == 12
    # 1 песня : 2 кадра : 1 персонаж → 3 песни, 6 кадров, 3 персонажа.
    assert q[_api.FRAME_KIND] == 6
    assert q[_api.CHAR_KIND] == 3
    assert sum(q[k] for k in ("opening", "ending", "insert")) == 3

test_mixed_quotas_split_frames_chars_and_songs.__module__ = _api.__name__
_api.test_mixed_quotas_split_frames_chars_and_songs = test_mixed_quotas_split_frames_chars_and_songs

def test_hint_plays_together_with_song():
    """Подсказка идёт ПЕРЕД дорожкой и не ждёт её конца — иначе она
    показывалась бы уже после отрезка."""
    s = _api.PackSettings(rounds=1, themes=1, questions=1, hint=True)
    root, ns = _api._parse(_api.build_content_xml([_api.make_candidate()], s))
    items = root.findall(".//s:param[@name='question']/s:item", ns)
    assert items[0].text == "Опенинг"
    assert items[0].get("waitForFinish") == "False"
    assert items[1].get("type") == "audio"

test_hint_plays_together_with_song.__module__ = _api.__name__
_api.test_hint_plays_together_with_song = test_hint_plays_together_with_song

def test_hint_over_a_video_is_spoken_not_written():
    """У вопроса-ролика «Опенинг»/«Эндинг» ведущий ПРОИЗНОСИТ одновременно с
    видео: на экране надпись загородила бы картинку (просьба пользователя)."""
    s = _api.PackSettings(rounds=1, themes=1, questions=1, song_video=True,
                     pct_songs=0, pct_videos=100, hint=True)
    cand = _api.make_candidate()
    cand.kind, cand.has_video = _api.VIDEO_KIND, True
    cand.media_base = "Пак(Тетрадь смерти)"
    root, ns = _api._parse(_api.build_content_xml([cand], s))
    items = root.findall(".//s:param[@name='question']/s:item", ns)
    assert [i.get("type") for i in items] == [None, "video"]
    said = items[0]
    assert said.text == "Опенинг"
    assert said.get("placement") == "replic"      # устный текст, не подпись
    assert said.get("waitForFinish") == "False"   # одновременно с роликом

test_hint_over_a_video_is_spoken_not_written.__module__ = _api.__name__
_api.test_hint_over_a_video_is_spoken_not_written = test_hint_over_a_video_is_spoken_not_written

def test_video_hint_obeys_its_checkbox():
    """Галочка подсказки одна на всех: выключена — молчит и ведущий."""
    s = _api.PackSettings(rounds=1, themes=1, questions=1, song_video=True,
                     pct_songs=0, pct_videos=100, hint=False)
    cand = _api.make_candidate()
    cand.kind, cand.has_video = _api.VIDEO_KIND, True
    cand.media_base = "Пак(Тетрадь смерти)"
    root, ns = _api._parse(_api.build_content_xml([cand], s))
    items = root.findall(".//s:param[@name='question']/s:item", ns)
    assert [i.get("type") for i in items] == ["video"]

test_video_hint_obeys_its_checkbox.__module__ = _api.__name__
_api.test_video_hint_obeys_its_checkbox = test_video_hint_obeys_its_checkbox

def test_hint_calls_insert_song_ost():
    s = _api.PackSettings(rounds=1, themes=1, questions=1, hint=True)
    cand = _api.make_candidate(song={"songType": "Insert Song"})
    cand.kind = "insert"
    root, ns = _api._parse(_api.build_content_xml([cand], s))
    assert root.find(".//s:param[@name='question']/s:item", ns).text == "OST"

test_hint_calls_insert_song_ost.__module__ = _api.__name__
_api.test_hint_calls_insert_song_ost = test_hint_calls_insert_song_ost

def test_media_files_named_after_title(tmp_path):
    """Файлы в паке зовутся «Сгенерировано в SI-HYX(Тайтл)», а не числами."""
    gen = _api.AnimePackGenerator(_api.PackSettings(), session=_api.FakeSession({}))
    cand = _api.make_candidate()
    cand.media_base = gen._media_base(cand)
    assert cand.audio_out == f"{_api.MEDIA_NAME_PREFIX}(Тетрадь смерти).opus"
    assert cand.poster_file == f"{_api.MEDIA_NAME_PREFIX}(Тетрадь смерти)_poster.avif"
    # Второй вопрос того же тайтла не должен делить файл с первым.
    other = _api.make_candidate()
    other.media_base = gen._media_base(other)
    assert other.audio_out != cand.audio_out

test_media_files_named_after_title.__module__ = _api.__name__
_api.test_media_files_named_after_title = test_media_files_named_after_title

@_api.pytest.mark.parametrize("line,title", [
    ("Наруто OP1 (2002) — 『Song』", "Наруто"),
    ("Доктор Стоун (2019)", "Доктор Стоун"),
    ("Бляйч ED12", "Бляйч"),
    ("Тетрадь смерти (2006) — 『Лайт Ягами』", "Тетрадь смерти"),
])
def test_answer_title_strips_song_year_and_tag(line, title):
    assert _api.answer_title(line) == title

test_answer_title_strips_song_year_and_tag.__module__ = _api.__name__
_api.test_answer_title_strips_song_year_and_tag = test_answer_title_strips_song_year_and_tag

def test_siq_exclusion_skips_same_franchise(tmp_path):
    """Франшизы из чужого пака в новый не попадают."""
    old = tmp_path / "старый.siq"
    s = _api.PackSettings(rounds=1, themes=1, questions=1)
    cand = _api.make_candidate()
    with _api.zipfile.ZipFile(old, "w") as zf:
        zf.writestr("content.xml", _api.build_content_xml([cand], s))
    assert "тетрадь смерти" in _api.siq_answer_roots(str(old))

    gen = _api.AnimePackGenerator(_api.PackSettings(exclude_siq=[str(old)]),
                             session=_api.FakeSession({}))
    gen.load_exclusions()
    assert not gen._accept_anime(_api.make_anime(), 1535, set(), set())
    other = _api.make_anime(russian="Стальной алхимик", name="Fullmetal Alchemist",
                       english="Fullmetal Alchemist", malId=5, franchise="fma")
    assert gen._accept_anime(other, 5, set(), set())

test_siq_exclusion_skips_same_franchise.__module__ = _api.__name__
_api.test_siq_exclusion_skips_same_franchise = test_siq_exclusion_skips_same_franchise

# ── Потолок веса пака и выбор общей базы ─────────────────────────
def test_pack_stops_when_budget_is_spent(monkeypatch):
    """Набранное уже перевалило за потолок — отбор прекращается сразу, даже
    если кандидаты ещё есть."""
    s = _api.PackSettings(rounds=1, themes=1, questions=6, openings=6, endings=0,
                     inserts=0, parallel=1, random_mode=False,
                     similar_count=1, max_pack_mb=5,
                     users=[_api.UserList("morr", "myanimelist", ["completed"])])
    pairs = [_api._pair(i, f"fr{i}") for i in range(1, 9)]
    gen = _api._generator(s, [p[0] for p in pairs], [p[1] for p in pairs],
                     user_ids={"morr": list(range(1, 9))})
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: True)
    # Каждый вопрос «весит» половину бюджета — после второго набор кончится.
    monkeypatch.setattr(gen, "_media_size",
                        lambda cand: int(gen._byte_budget) // 2 + 1)
    picked = gen.select_songs()
    assert len(picked) == 2

test_pack_stops_when_budget_is_spent.__module__ = _api.__name__
_api.test_pack_stops_when_budget_is_spent = test_pack_stops_when_budget_is_spent

def test_pack_stops_before_it_grows_too_heavy(monkeypatch):
    """Ждать фактического перебора поздно: генератор смотрит на средний вес
    вопроса и останавливается, как только видно, что пак вылезет за потолок."""
    s = _api.PackSettings(rounds=1, themes=1, questions=20, openings=20, endings=0,
                     inserts=0, parallel=1, random_mode=False,
                     similar_count=1, max_pack_mb=5,
                     users=[_api.UserList("morr", "myanimelist", ["completed"])])
    pairs = [_api._pair(i, f"fr{i}") for i in range(1, 30)]
    gen = _api._generator(s, [p[0] for p in pairs], [p[1] for p in pairs],
                     user_ids={"morr": list(range(1, 30))})
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: True)
    # Десятая часть бюджета на вопрос: двадцать таких — вдвое больше потолка.
    monkeypatch.setattr(gen, "_media_size",
                        lambda cand: int(gen._byte_budget) // 10)
    picked = gen.select_songs()
    # Остановились на прогнозе (после «разогрева»), а не на фактическом переборе.
    assert 5 <= len(picked) <= 8
    assert gen._bytes_used < gen._byte_budget

test_pack_stops_before_it_grows_too_heavy.__module__ = _api.__name__
_api.test_pack_stops_before_it_grows_too_heavy = test_pack_stops_before_it_grows_too_heavy

def test_budget_warmup_does_not_stop_a_normal_pack(monkeypatch):
    """Лёгкий пак прогноз не трогает — все вопросы на месте."""
    s = _api.PackSettings(rounds=1, themes=1, questions=6, openings=6, endings=0,
                     inserts=0, parallel=1, random_mode=False,
                     similar_count=1, max_pack_mb=150,
                     users=[_api.UserList("morr", "myanimelist", ["completed"])])
    pairs = [_api._pair(i, f"fr{i}") for i in range(1, 9)]
    gen = _api._generator(s, [p[0] for p in pairs], [p[1] for p in pairs],
                     user_ids={"morr": list(range(1, 9))})
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: True)
    monkeypatch.setattr(gen, "_media_size", lambda cand: 700 * 1024)
    assert len(gen.select_songs()) == 6

test_budget_warmup_does_not_stop_a_normal_pack.__module__ = _api.__name__
_api.test_budget_warmup_does_not_stop_a_normal_pack = test_budget_warmup_does_not_stop_a_normal_pack

def test_amq_base_is_only_for_song_packs():
    """Мастер-лист AMQ знает лишь тайтлы с песнями, поэтому пакам из кадров и
    персонажей база достаётся с Shikimori, что бы ни стояло в настройках."""
    songs = _api.PackSettings(random_source="amq")
    assert songs.has_songs is True
    gen = _api.AnimePackGenerator(songs, session=_api.FakeSession({}))
    assert gen._random_source == "amq" and gen._ids_are_ann is True

    for kw in ({"pct_songs": 0, "pct_frames": 100},
               {"pct_songs": 0, "pct_chars": 100},
               {"pick_openings": False, "pick_endings": False,
                "pick_inserts": False}):
        s = _api.PackSettings(random_source="amq", **kw)
        assert s.has_songs is False
        gen = _api.AnimePackGenerator(s, session=_api.FakeSession({}))
        assert gen._random_source == "shikimori"
        assert gen._ids_are_ann is False

test_amq_base_is_only_for_song_packs.__module__ = _api.__name__
_api.test_amq_base_is_only_for_song_packs = test_amq_base_is_only_for_song_packs

def test_shikimori_is_the_default_base():
    assert _api.PackSettings().random_source == "shikimori"

test_shikimori_is_the_default_base.__module__ = _api.__name__
_api.test_shikimori_is_the_default_base = test_shikimori_is_the_default_base

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
    session = _api.FakeSession([("api.animethemes.moe/anime",
                            _api.FakeResponse(json_data=payload))])
    out = _api.api.AnimeThemesApi(session).themes_by_mal_ids([1535])
    assert set(out[1535]) == {"OP1", "ED2"}
    # Из двух пригодных вариантов берём тот, что легче качать.
    assert out[1535]["OP1"]["url"] == "https://v/DN-OP1-720.webm"
    assert out[1535]["ED2"]["resolution"] == 480

test_animethemes_maps_tags_to_video_links.__module__ = _api.__name__
_api.test_animethemes_maps_tags_to_video_links = test_animethemes_maps_tags_to_video_links

def test_video_question_replaces_audio_in_xml():
    s = _api.PackSettings(rounds=1, themes=1, questions=1, song_video=True,
                     video_cut=15, hint=False)
    cand = _api.make_candidate()
    cand.has_video = True
    cand.media_base = "Пак(Тетрадь смерти)"
    root, ns = _api._parse(_api.build_content_xml([cand], s))
    items = root.findall(".//s:param[@name='question']/s:item", ns)
    assert [i.get("type") for i in items] == ["video"]
    assert items[0].text == "Пак(Тетрадь смерти).mp4"
    assert items[0].get("duration") == "00:00:15"
    # Ответ на месте: ролик заменяет только сам вопрос.
    assert root.find(".//s:right/s:answer", ns).text.startswith("Тетрадь смерти")

test_video_question_replaces_audio_in_xml.__module__ = _api.__name__
_api.test_video_question_replaces_audio_in_xml = test_video_question_replaces_audio_in_xml

def test_video_falls_back_to_audio(monkeypatch):
    """Ролика для этой песни нет — вопрос всё равно состоится, просто звуком."""
    s = _api.PackSettings(song_video=True, pct_videos=100, pct_songs=0)
    gen = _api.AnimePackGenerator(s, session=_api.FakeSession({}))
    gen.folder = "."
    cand = _api.make_candidate()
    cand.kind = _api.VIDEO_KIND
    monkeypatch.setattr(gen, "_theme_video", lambda c: "")
    calls = []
    monkeypatch.setattr(gen, "download_audio", lambda c: calls.append(c) or True)
    monkeypatch.setattr(gen, "download_images", lambda c: None)
    monkeypatch.setattr(gen, "_media_base", lambda c: "base")
    assert gen._fetch_media(cand) is True
    assert cand.has_video is False and len(calls) == 1

test_video_falls_back_to_audio.__module__ = _api.__name__
_api.test_video_falls_back_to_audio = test_video_falls_back_to_audio

def test_video_start_is_random_like_a_song(monkeypatch):
    """Отрезок ролика берётся со случайной секунды — как отрезок песни, а не
    всегда с пятой (просьба пользователя). Заставку студии в начале опенинга
    по-прежнему пропускаем."""
    import random as _random
    gen = _api.AnimePackGenerator(_api.PackSettings(video_cut=15),
                             session=_api.FakeSession({}),
                             rng=_random.Random(1234))
    monkeypatch.setattr(gen, "_video_seconds", lambda url: 90.0)
    cand = _api.make_candidate()
    starts = {gen._video_start(cand, "u", 15) for _ in range(30)}
    assert len(starts) > 1                       # не одна и та же секунда
    assert min(starts) >= 5 and max(starts) <= 75

test_video_start_is_random_like_a_song.__module__ = _api.__name__
_api.test_video_start_is_random_like_a_song = test_video_start_is_random_like_a_song
