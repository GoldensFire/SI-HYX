# -*- coding: utf-8 -*-
"""MangaDex: из каких глав берётся разворот для вопроса.

Карточка у тайтла ровно одна — найденная по ссылке на MyAnimeList или по
точному названию. Соседние записи выдачи с пометкой в скобках
(«Tsuredure Children (Pre-Serialization)») не берутся: пометка не доказывает,
что это та же вещь, а страница не той манги хуже, чем отсутствие вопроса.
"""
import random

from animepack_api import MangaDexApi
from si_hyx_parts.animepack_api.mangadex_api import page_skip

MAIN = "main"
FAMILY = "main-pre"


def _row(row_id, title, langs, mal=""):
    return {"id": row_id, "attributes": {
        "title": {"en": title}, "altTitles": [],
        "links": ({"mal": mal} if mal else {}),
        "availableTranslatedLanguages": list(langs)}}


def _chapter(chapter_id, pages, number="1"):
    return {"id": chapter_id, "attributes": {"pages": pages, "chapter": number}}


def _session(fake_session, fake_response, rows, feeds, pages=16):
    """Выдача поиска, ленты глав по (карточка, язык) и раздача страниц."""
    def feed(url, **kw):
        entry = url.split("/manga/")[1].split("/feed")[0]
        lang = ((kw.get("params") or {}).get("translatedLanguage[]") or [""])[0]
        body = feeds.get((entry, lang), {"data": []})
        return fake_response(json_data=body)

    def at_home(url, **kw):
        count = pages
        return fake_response(json_data={"baseUrl": "https://cdn.md", "chapter": {
            "hash": "abc", "data": [f"p{i}.png" for i in range(count)],
            "dataSaver": []}})

    return fake_session([
        ("/feed", feed),
        ("/at-home/server/", at_home),
        ("/manga", fake_response(json_data={"data": rows})),
    ])


def _card(**over):
    card = {"malId": 58027, "name": "Tsurezure Children",
            "english": "Tsuredure Children", "japanese": "徒然チルドレン",
            "synonyms": []}
    card.update(over)
    return card


# ── короткие главы (ёнкома) ──────────────────────────────────────────────────
def test_page_skip_shrinks_with_the_chapter():
    """У обычной главы срезаем по пять страниц, у ёнкомы — по одной."""
    assert page_skip(16) == 5
    assert page_skip(13) == 5
    assert page_skip(10) == 2
    assert page_skip(7) == 2
    assert page_skip(5) == 1            # «Признания»: глава в пять страниц
    assert page_skip(4) == 1
    assert page_skip(3) == 0            # такую главу вовсе не берём


def test_five_page_chapters_are_still_usable(fake_session, fake_response):
    """Прежнее правило «меньше одиннадцати страниц — мимо» съедало всю ёнкому."""
    rows = [_row(MAIN, "Tsuredure Children", ["kk"], mal="58027")]
    feeds = {(MAIN, ""): {"data": [_chapter("kk-1", 5)]}}
    session = _session(fake_session, fake_response, rows, feeds, pages=5)
    api = MangaDexApi(session, rng=random.Random(1))
    url = api.panel_url(_card())
    assert url.startswith("https://cdn.md/data/abc/")
    # Титул и последняя страница по-прежнему не попадают в вопрос.
    assert url.rsplit("/", 1)[-1] not in ("p0.png", "p4.png")


def test_a_chapter_of_three_pages_is_skipped(fake_session, fake_response):
    rows = [_row(MAIN, "Tsuredure Children", ["kk"], mal="58027")]
    feeds = {(MAIN, ""): {"data": [_chapter("kk-1", 3)]}}
    session = _session(fake_session, fake_response, rows, feeds, pages=3)
    assert MangaDexApi(session, rng=random.Random(1)).panel_url(_card()) == ""


# ── соседние карточки выдачи ────────────────────────────────────────────────
def test_a_qualified_card_is_never_used(fake_session, fake_response):
    """«… (Pre-Serialization)» — НЕ та же вещь: пометка в скобках ничего не
    доказывает, а страница не той манги хуже, чем отсутствие вопроса (просьба
    пользователя). Берём только найденную карточку."""
    rows = [_row(MAIN, "Tsuredure Children", ["ru"], mal="58027"),
            _row(FAMILY, "Tsuredure Children (Pre-Serialization)", ["en"])]
    feeds = {(MAIN, "ru"): {"data": []},           # объявлен, но лента пуста
             (MAIN, ""): {"data": []},
             (FAMILY, "en"): {"data": [_chapter("en-1", 16)]}}
    session = _session(fake_session, fake_response, rows, feeds)
    api = MangaDexApi(session, rng=random.Random(1))
    assert api.panel_url(_card()) == ""
    asked = [url for _m, url, _kw in session.calls if "/feed" in url]
    assert all(FAMILY not in url for url in asked)


def test_a_spin_off_without_brackets_is_not_used_either(fake_session,
                                                        fake_response):
    """«Vagabond Gaiden» — другая манга и всегда ею была."""
    rows = [_row(MAIN, "Tsuredure Children", ["ru"], mal="58027"),
            _row("gaiden", "Tsuredure Children Gaiden", ["en"])]
    feeds = {(MAIN, "ru"): {"data": []}, (MAIN, ""): {"data": []},
             ("gaiden", "en"): {"data": [_chapter("en-1", 16)]}}
    session = _session(fake_session, fake_response, rows, feeds)
    api = MangaDexApi(session, rng=random.Random(1))
    assert api.panel_url(_card()) == ""


def test_chosen_language_still_wins_over_everything(fake_session, fake_response):
    """Раз человек выбрал язык, подсовывать другой нельзя."""
    rows = [_row(MAIN, "Tsuredure Children", ["ru", "en"], mal="58027")]
    feeds = {(MAIN, "ru"): {"data": [_chapter("ru-1", 16)]}}
    session = _session(fake_session, fake_response, rows, feeds)
    api = MangaDexApi(session, language="ru", rng=random.Random(1))
    assert api.panel_url(_card())
    asked = {((kw.get("params") or {}).get("translatedLanguage[]") or [""])[0]
             for _m, url, kw in session.calls if "/feed" in url}
    assert asked == {"ru"}


def test_the_unfiltered_feed_of_the_main_card_stays_in_the_plan(fake_session,
                                                                fake_response):
    """«Ван-Пис»: все объявленные языки лежат на стороне — спасает только она."""
    rows = [_row(MAIN, "Tsuredure Children", ["ru", "en", "ca", "it", "fr"],
                 mal="58027")]
    session = _session(fake_session, fake_response, rows, {})
    api = MangaDexApi(session, rng=random.Random(1))
    plan = api._plan(api.manga_id(_card()))
    assert len(plan) <= 6
    assert (MAIN, "") in plan
