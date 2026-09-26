# -*- coding: utf-8 -*-
"""AniZip, MangaDex и Sakugabooru — сетевой слой."""
import json
import os
import random
import re

import pytest

from animepack_api import AniZipApi, MangaDexApi, SakugaApi


# ── AniZip: превью серий ─────────────────────────────────────────────────────
def _anizip_body():
    return {"episodes": {
        "1": {"image": "https://tvdb/1.jpg", "title": {"en": "One"}},
        "2": {"title": {"en": "Two"}},              # серия без картинки
        "3": {"image": "https://tvdb/3.jpg"},
    }}


def test_anizip_takes_every_episode_image_by_mal_id(fake_session, fake_response):
    session = fake_session([("/mappings", fake_response(json_data=_anizip_body()))])
    api = AniZipApi(session)
    assert api.frames(20) == ["https://tvdb/1.jpg", "https://tvdb/3.jpg"]
    # Ищем прямо по MAL id — сводить каталоги, как с Kitsu, не нужно.
    assert session.calls[0][2]["params"] == {"mal_id": "20"}


def test_anizip_asks_once_per_title_and_survives_a_dead_server(fake_session,
                                                               fake_response):
    session = fake_session([("/mappings", fake_response(json_data=_anizip_body()))])
    api = AniZipApi(session)
    api.frames(20)
    api.frames(20)
    assert len(session.calls) == 1                  # второй раз — из памяти
    dead = AniZipApi(fake_session([("/mappings", fake_response(status_code=500))]))
    assert dead.frames(20) == []                    # доп. источник, не критичен


# ── MangaDex: страница-разворот ──────────────────────────────────────────────
def _mangadex_session(fake_session, fake_response, *, mal="656", pages=16,
                      langs=("ru", "en"), feeds=None, empty_chapters=()):
    search = {"data": [
        {"id": "wrong", "attributes": {"title": {"en": "Vagabond Gaiden"},
                                       "altTitles": [], "links": {},
                                       "availableTranslatedLanguages": []}},
        {"id": "right", "attributes": {"title": {"en": "Vagabond"},
                                       "altTitles": [],
                                       "links": {"mal": mal},
                                       "availableTranslatedLanguages": list(langs)}}]}
    default_feed = {"data": [
        {"id": "external", "attributes": {"pages": 0, "chapter": "1",
                                          "externalUrl": "https://viz.com/x"}},
        {"id": "tiny", "attributes": {"pages": 2, "chapter": "2"}},
        {"id": "good", "attributes": {"pages": pages, "chapter": "3"}}]}

    def feed(url, **kw):
        lang = (kw.get("params") or {}).get("translatedLanguage[]") or [""]
        body = (feeds or {}).get(lang[0], default_feed) if feeds else default_feed
        return fake_response(json_data=body)

    def at_home(url, **kw):
        if any(url.endswith(cid) for cid in empty_chapters):
            return fake_response(json_data={"baseUrl": "", "chapter": {}})
        return fake_response(json_data={"baseUrl": "https://cdn.md", "chapter": {
            "hash": "abc",
            "data": [f"p{i}.png" for i in range(pages)],
            "dataSaver": []}})

    return fake_session([
        ("/manga/right/feed", feed),
        ("/at-home/server/", at_home),
        ("/manga", fake_response(json_data=search)),
    ])


def _card(**over):
    card = {"malId": 656, "name": "Vagabond", "english": "Vagabond",
            "japanese": "バガボンド", "synonyms": []}
    card.update(over)
    return card


def test_mangadex_matches_the_title_by_its_mal_link(fake_session, fake_response):
    session = _mangadex_session(fake_session, fake_response)
    api = MangaDexApi(session, rng=random.Random(1))
    assert api.manga_id(_card()) == "right"
    # Возрастные метки: порнографию не просим никогда, erotica — по галочке.
    ratings = session.calls[0][2]["params"]["contentRating[]"]
    assert ratings == ["safe", "suggestive"]
    assert MangaDexApi(session, allow_erotica=True).ratings == [
        "safe", "suggestive", "erotica"]


def test_mangadex_falls_back_to_an_exact_title_when_mal_link_is_missing(
        fake_session, fake_response):
    session = _mangadex_session(fake_session, fake_response, mal="")
    api = MangaDexApi(session, rng=random.Random(1))
    assert api.manga_id(_card(malId=0)) == "right"
    # Похожее по смыслу, но иначе названное — не берём вовсе.
    assert api.manga_id(_card(malId=0, name="Vagabond Legends", english="",
                              japanese="", synonyms=[])) == ""


def test_mangadex_panel_skips_the_title_page_and_external_chapters(
        fake_session, fake_response):
    session = _mangadex_session(fake_session, fake_response, pages=16)
    api = MangaDexApi(session, rng=random.Random(2))
    url = api.panel_url(_card())
    assert url.startswith("https://cdn.md/data/abc/")
    # По пять страниц с каждого края — титул с названием, оглавление,
    # переводчики, реклама и «продолжение следует».
    skipped = [f"p{i}.png" for i in list(range(5)) + list(range(11, 16))]
    assert url.rsplit("/", 1)[-1] not in skipped
    assert all("/at-home/server/good" in call[1] for call in session.calls
               if "/at-home/" in call[1])


def test_mangadex_panel_respects_already_shown_pages(fake_session, fake_response):
    session = _mangadex_session(fake_session, fake_response, pages=13)
    api = MangaDexApi(session, rng=random.Random(3))
    # Середина главы из тринадцати страниц — ровно три штуки, и все уже были.
    seen = {f"https://cdn.md/data/abc/p{i}.png" for i in (5, 6, 7)}
    assert api.panel_url(_card(), seen) == ""


def test_chosen_language_is_the_only_one_asked(fake_session, fake_response):
    session = _mangadex_session(fake_session, fake_response)
    api = MangaDexApi(session, language="ru", rng=random.Random(1))
    assert api.panel_url(_card())
    feeds = [kw["params"]["translatedLanguage[]"]
             for _m, url, kw in session.calls if "/feed" in url]
    assert feeds == [["ru"]]


def test_language_order_prefers_russian_english_original_then_anything(
        fake_session, fake_response):
    session = _mangadex_session(fake_session, fake_response,
                                langs=("ca", "en", "ja", "pt-br", "ru"))
    api = MangaDexApi(session, rng=random.Random(1))
    manga = api.manga_id(_card())
    # Последним заходом идёт лента без фильтра вовсе — на случай, когда у всех
    # объявленных языков главы лежат на стороне.
    assert api.languages(manga) == ["ru", "en", "ja", ""]


def test_next_language_is_tried_when_the_chapter_has_no_pages(fake_session,
                                                              fake_response):
    # «Ван-Пис»: русская лента пуста, английская глава ровно одна и без
    # страниц, а каталанских глав сотня — вопрос обязан состояться.
    feeds = {
        "ru": {"data": []},
        "en": {"data": [{"id": "dead", "attributes": {"pages": 20,
                                                      "chapter": "1"}}]},
        "ca": {"data": [{"id": "alive", "attributes": {"pages": 16,
                                                       "chapter": "1"}}]},
    }
    session = _mangadex_session(fake_session, fake_response,
                                langs=("ru", "en", "ca"), feeds=feeds,
                                empty_chapters=("dead",))
    api = MangaDexApi(session, rng=random.Random(1))
    assert api.panel_url(_card()).startswith("https://cdn.md/data/abc/")
    asked = [url.rsplit("/", 1)[-1] for _m, url, _kw in session.calls
             if "/at-home/" in url]
    assert asked == ["dead", "alive"]


# ── Sakugabooru: вырезка анимации ────────────────────────────────────────────
def _sakuga_session(fake_session, fake_response):
    tags = [{"name": "sousou_no_frieren_series", "count": 641, "type": 3},
            {"name": "sousou_no_frieren", "count": 597, "type": 3},
            {"name": "sousou_no_frieren_staff", "count": 900, "type": 1}]
    posts = [
        {"id": 1, "file_ext": "mp4", "file_url": "https://sb/a.mp4",
         "file_size": 3_000_000, "source": "#19"},
        {"id": 2, "file_ext": "png", "file_url": "https://sb/b.png",
         "file_size": 2_000_000},
        {"id": 3, "file_ext": "webm", "file_url": "https://sb/c.webm",
         "file_size": 900_000_000},
    ]
    return fake_session([("/tag.json", fake_response(json_data=tags)),
                         ("/post.json", fake_response(json_data=posts))])


def test_sakuga_prefers_the_exact_copyright_tag(fake_session, fake_response):
    session = _sakuga_session(fake_session, fake_response)
    api = SakugaApi(session, rng=random.Random(1))
    card = {"malId": 52991, "name": "Sousou no Frieren", "english": "Frieren"}
    assert api.tag_for(card) == "sousou_no_frieren"
    assert session.calls[0][2]["params"]["name"] == "sousou_no_frieren"


def test_sakuga_takes_only_light_video_clips(fake_session, fake_response):
    api = SakugaApi(_sakuga_session(fake_session, fake_response),
                    rng=random.Random(1))
    clips = api.clips("sousou_no_frieren")
    assert [row["url"] for row in clips] == ["https://sb/a.mp4"]


def test_sakuga_safe_switch_reaches_the_query(fake_session, fake_response):
    session = _sakuga_session(fake_session, fake_response)
    SakugaApi(session).clips("frieren")
    assert session.calls[0][2]["params"]["tags"] == "frieren animated rating:s"
    session.calls.clear()
    SakugaApi(session, safe_only=False).clips("frieren")
    assert session.calls[0][2]["params"]["tags"] == "frieren animated"


# ── Язык поиска: русское название наружу не уходит ───────────────────────────
_CYR = re.compile(r"[Ѐ-ӿ]")


def test_mangadex_never_searches_by_the_russian_title(fake_session,
                                                      fake_response):
    """Запрос идёт ромадзи/английским/японским, русские синонимы пропускаются.

    На MangaDex карточка подписана ромадзи, английским и оригиналом; русского
    названия там нет, и заход на него — впустую потраченный запрос к API."""
    session = _mangadex_session(fake_session, fake_response, mal="")
    api = MangaDexApi(session, rng=random.Random(1))
    card = _card(malId=0, name="Berserk Deluxe", english="", japanese="",
                 synonyms=["Берсерк", "Берсёрк", "Kenpuu Denki Berserk"])
    api.manga_id(card)
    asked = [kw["params"]["title"] for _m, url, kw in session.calls
             if url.endswith("/manga")]
    assert asked and not any(_CYR.search(q) for q in asked)
    assert "Kenpuu Denki Berserk" in asked


def test_sakuga_asks_in_japanese_or_romaji(fake_session, fake_response):
    """Sakugabooru спрашивает ромадзи и английское название, не русское."""
    session = _sakuga_session(fake_session, fake_response)
    SakugaApi(session, rng=random.Random(1)).tag_for(
        {"malId": 52991, "name": "Sousou no Frieren", "english": "Frieren",
         "russian": "Провожающая в последний путь Фрирен"})
    names = [kw["params"]["name"] for _m, _u, kw in session.calls]
    assert names and not any(_CYR.search(q) for q in names)
