# -*- coding: utf-8 -*-
"""Regression checks for preserving work and excluding precise repeats."""
import random
import zipfile
from xml.etree import ElementTree as ET

import animepack as ap
import animepack_plot as plot
from si_hyx_parts.animepack.author_lookup import _author
from si_hyx_parts.animepack.exact_repeat import candidate_keys, read_exact_keys


def _anime(title="Наруто", score=7.82):
    return {"id": "1", "malId": "1", "russian": title,
            "name": "Naruto", "score": score, "airedOn": {"year": 2002}}


def test_japanese_song_name_does_not_delete_the_main_russian_answer():
    card = _anime("Школьная жизнь!")
    card["name"] = "Gakkougurashi!"
    card["airedOn"] = {"year": 2015}
    cand = ap.SongCandidate(song={
        "songType": "Opening 1",
        "songName": "ふ・れ・ん・ど・し・た・い",
        "songArtist": "Gakuen Seikatsu-bu",
    }, anime=card, kind="opening")
    answers = cand.answer_variants()
    assert answers[0] == (
        "Школьная жизнь! OP1 (2015) — 『ふ・れ・ん・ど・し・た・い』")
    assert answers[0] == cand.main_answer


def test_exact_repeat_keeps_other_openings_of_same_anime(tmp_path):
    settings = ap.PackSettings(rounds=1, themes=1, questions=1)
    old = ap.SongCandidate(song={"songType": "Opening 10",
                                 "songName": "Song A"}, anime=_anime())
    archive_path = tmp_path / "old.siq"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("content.xml", ap.build_content_xml([old], settings))
    keys = read_exact_keys(str(archive_path))
    same = ap.SongCandidate(song={"songType": "Opening 10",
                                  "songName": "Song A"}, anime=_anime())
    other = ap.SongCandidate(song={"songType": "Opening 11",
                                   "songName": "Song B"}, anime=_anime())
    assert keys & candidate_keys(same, str(tmp_path))
    assert not keys & candidate_keys(other, str(tmp_path))


def test_exact_repeat_catches_a_song_of_a_title_with_a_dash(tmp_path):
    """Тире в самом НАЗВАНИИ не должно прятать вопрос от памяти повторов.

    Живая жалоба (просьба пользователя): «Код Гиас: Восставший Лелуш —
    Пробуждение OP3 (2017) — 『WORLD END』» приехал и в первый пак, и в
    двенадцатый, хотя первый стоял в списке «не повторять вопросы». Отпечаток
    песни искался до ПЕРВОГО тире, то есть в огрызке «Код Гиас: Восставший
    Лелуш» — тега песни там нет, и вопрос оставался без отпечатка вовсе."""
    card = dict(_anime(title="Код Гиас: Восставший Лелуш — Пробуждение"),
                airedOn={"year": 2017})
    song = {"songType": "Opening 3", "songName": "WORLD END"}
    old = ap.SongCandidate(song=song, anime=card)
    assert "— Пробуждение OP3 (2017) — 『WORLD END』" in old.main_answer
    archive_path = tmp_path / "dash.siq"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("content.xml", ap.build_content_xml(
            [old], ap.PackSettings(rounds=1, themes=1, questions=1)))
    keys = read_exact_keys(str(archive_path))
    assert any(key[0] == "song" for key in keys)
    same = ap.SongCandidate(song=dict(song), anime=dict(card))
    other = ap.SongCandidate(song={"songType": "Opening 1",
                                   "songName": "COLORS"}, anime=dict(card))
    assert keys & candidate_keys(same, str(tmp_path))
    assert not keys & candidate_keys(other, str(tmp_path))


def test_exact_repeat_uses_original_sakuga_post(tmp_path):
    old = ap.SongCandidate(song={}, anime=_anime(), kind=ap.SAKUGA_KIND)
    old.source_link = "https://www.sakugabooru.com/post/show/123"
    archive_path = tmp_path / "sakuga.siq"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("content.xml", ap.build_content_xml(
            [old], ap.PackSettings(rounds=1, themes=1, questions=1)))
    keys = read_exact_keys(str(archive_path))
    same = ap.SongCandidate(song={}, anime=_anime(), kind=ap.SAKUGA_KIND)
    same.source_link = old.source_link
    other = ap.SongCandidate(song={}, anime=_anime(), kind=ap.SAKUGA_KIND)
    other.source_link = "https://www.sakugabooru.com/post/show/124"
    assert keys & candidate_keys(same, str(tmp_path))
    assert not keys & candidate_keys(other, str(tmp_path))


def test_source_filters_adaptation_and_unmarked_season():
    # Вынесенный runtime обращается через публичный namespace animepack.
    assert ap.episode_number is plot.episode_number
    assert not plot.source_page_ok("Light Novel Volume 01", "", "Монолог фармацевта")
    assert not plot.source_page_ok("Episode 11", "", "Токийский гуль: Перерождение")
    assert plot.source_page_ok("Date A Live V Episode 8", "", "Рандеву с жизнью 5")
    assert not plot.source_page_ok("Episode 5", "", "Рандеву с жизнью 5")
    assert not plot.source_page_ok(
        "Arifureta_-_Season_2_Episode_01", "",
        "Арифурэта: Сильнейший ремесленник в мире")
    assert plot.source_page_ok(
        "Arifureta_-_Season_2_Episode_01", "",
        "Arifureta Shokugyou de Sekai Saikyou 2nd Season")
    assert not plot.source_page_ok("Dororo Episode 7", "2019 anime", "Дороро", 1969)
    assert plot.episode_number("Date_A_Live_V_Episode_8") == "8"
    assert plot.episode_number("Light_Novel_Volume_01") == ""
    assert plot.name_title("В аниме «Рандеву с жизнью» что произошло?",
                           "Рандеву с жизнью 5") == (
                               "В аниме «Рандеву с жизнью 5» что произошло?")
    assert plot.season_number("Арифурэта", "Arifureta 2nd Season") == 2
    assert plot.season_title(
        "Арифурэта: Сильнейший ремесленник в мире",
        "Arifureta 2nd Season") == (
            "Арифурэта: Сильнейший ремесленник в мире — 2-й сезон")


def test_running_episode_title_is_accepted_by_its_air_date():
    raw = """{{Episode Infobox
|Air Date = September 19, 2020
|Season = 3
|Episode = 47}}"""
    title = "Мастера Меча Онлайн: Алисизация — Война в Подмирье 2"
    assert plot.source_page_ok(
        "Sword Art Online Alicization Episode 47", raw, title, 2020)
    assert not plot.source_page_ok(
        "Sword Art Online Alicization Episode 47", raw, title, 2021)


def test_pick_plot_reads_infobox_before_rejecting_a_running_episode_title():
    raw = """{{Episode Infobox
|Air Date = September 19, 2020
|Season = 3
|Episode = 47}}
==Plot==
События финальной серии. """ + "Продолжение сюжета. " * 30

    class Wiki:
        def find_wiki(self, _names):
            return "swordartonline.fandom.com"
        def episode_pages(self, _host):
            return ["Sword Art Online Alicization Episode 47"]
        def search(self, _host, _query, limit=3):
            return []
        def page_source(self, _host, _page):
            return raw
        def plot_section(self, _text):
            return "Пересказ серии. " * 30

    got = plot.pick_plot(
        Wiki(), ["Sword Art Online Alicization"], random.Random(0),
        title="Мастера Меча Онлайн: Алисизация — Война в Подмирье 2",
        year=2020)
    assert got["page"] == "Sword Art Online Alicization Episode 47"
    assert got["source"] == raw


def test_movie_does_not_take_a_tv_episode_as_its_source():
    class Wiki:
        def find_wiki(self, _names):
            return "film.fandom.com"
        def episode_pages(self, _host):
            return ["Episode 1"]
        def search(self, _host, _name, limit=3):
            return ["Movie"]
        def page_text(self, _host, _page):
            return "Завязка фильма. " * 40
        def plot_section(self, text):
            return text
    got = plot.pick_plot(Wiki(), ["Movie"], random.Random(0),
                         title="Фильм", movie=True)
    assert got["page"] == "Movie"


def test_empty_spoken_answer_has_author_before_rating():
    cand = ap.SongCandidate(song={}, anime=_anime(), kind=ap.FRAME_KIND)
    cand.author_name = "Аки Акасака"
    xml = ap.build_content_xml([cand], ap.PackSettings(
        rounds=1, themes=1, questions=1))
    root = ET.fromstring(xml)
    spoken = [item.text for item in root.iter()
              if item.tag.endswith("item") and item.get("placement") == "replic"]
    assert spoken == ["Автор — 『Аки Акасака』 · "
                      "Рейтинг MAL — 『7.82⭐』 · "
                      "Индекс популярности — 0 (Ур. 15)"]
    assert _author({"personRoles": [
        {"rolesEn": ["Storyboard"], "person": {"russian": "Раскадровщик"}},
        {"rolesRu": ["Автор оригинала"],
         "person": {"russian": "Аки Акасака"}},
    ]}) == "Аки Акасака"


def test_sequel_poster_does_not_reuse_first_season_cache(monkeypatch):
    settings = ap.PackSettings(poster_cache=True)
    gen = ap.AnimePackGenerator(settings)
    cand = ap.SongCandidate(song={}, anime=_anime("Рандеву с жизнью 5"),
                            kind=ap.PLOT_KIND)
    monkeypatch.setattr(ap.poster_cache, "find", lambda _key: (b"season1", ".jpg"))
    monkeypatch.setattr(ap.poster_cache, "put", lambda *_args: None)
    gen._get_bytes = lambda _url: b"season5"
    gen._tmdb_poster = lambda _cand: (b"season1", ".jpg")
    assert gen._poster_bytes(cand, "https://example.test/poster.jpg")[0] == b"season5"
    assert gen._poster_bytes(cand, "")[0] == b""


def test_sequel_poster_is_detected_from_romanized_title(monkeypatch):
    settings = ap.PackSettings(poster_cache=True)
    gen = ap.AnimePackGenerator(settings)
    anime = _anime("Арифурэта: Сильнейший ремесленник в мире")
    anime["name"] = "Arifureta Shokugyou de Sekai Saikyou 2nd Season"
    cand = ap.SongCandidate(song={}, anime=anime, kind=ap.PLOT_KIND)
    monkeypatch.setattr(ap.poster_cache, "find", lambda _key: (b"season1", ".jpg"))
    monkeypatch.setattr(ap.poster_cache, "put", lambda *_args: None)
    gen._get_bytes = lambda _url: b"season2"
    assert gen._poster_bytes(cand, "https://example.test/s2.jpg")[0] == b"season2"


def test_stopped_generation_preserves_accepted_questions(tmp_path):
    settings = ap.PackSettings(out_dir=str(tmp_path), rounds=1, themes=1,
                               questions=2)
    settings.validate = lambda: []
    state = {"stop": False}
    gen = ap.AnimePackGenerator(settings, should_stop=lambda: state["stop"])
    cand = ap.SongCandidate(song={}, anime=_anime(), kind=ap.FRAME_KIND)
    def selected():
        state["stop"] = True
        return [cand]
    gen.select_songs = selected
    result = gen.run()
    assert result.cancelled
    assert result.songs == [cand]
    with zipfile.ZipFile(result.path) as archive:
        assert b"<question " in archive.read("content.xml")
