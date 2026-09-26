# -*- coding: utf-8 -*-
"""Ссылка на ИСТОЧНИК вопроса последней строкой ответа.

Манга, сюжет и сакуга собраны не из карточки Shikimori, а с
чужого сайта, и по готовому паку раньше нельзя было понять, откуда взялась
картинка. Теперь адрес источника идёт последним вариантом ответа — как у арта
Pixiv и у кавера (просьба пользователя). Назвать его никто не назовёт: строка
нужна ведущему и редактору пака.

Сети здесь нет: все службы подменены теми же заглушками, что и в
test_animepack_manga_sakuga.
"""
import xml.etree.ElementTree as ET

import animepack
from animepack import (MANGA_KIND, PLOT_KIND, SAKUGA_KIND,
                       PackSettings, SongCandidate)
from test_animepack_manga_sakuga import (_fake_ffmpeg, generator,  # noqa: F401
                                         make_anime)


# ── как складывается сам адрес ───────────────────────────────────────────
def test_the_links_point_at_pages_and_not_at_files():
    """Адрес ФАЙЛА не годится: он протухает и ведущему ничего не говорит."""
    assert animepack.mangadex_chapter_link("ch-42") == \
        "https://mangadex.org/chapter/ch-42"
    assert animepack.sakuga_post_link("251547") == \
        "https://sakugabooru.com/post/show/251547"
    assert animepack.fandom_page_link("charlotte.fandom.com", "Yuu Otosaka") \
        == "https://charlotte.fandom.com/wiki/Yuu_Otosaka"


def test_an_unknown_source_gives_an_empty_link():
    """Пустая строка потом просто не попадёт в ответ (см. _dedup_answers)."""
    assert animepack.mangadex_chapter_link("") == ""
    assert animepack.sakuga_post_link(None) == ""
    assert animepack.fandom_page_link("wiki.fandom.com", "") == ""
    assert animepack.fandom_page_link("", "Страница") == ""


def test_a_page_name_with_spaces_and_cyrillic_survives():
    link = animepack.fandom_page_link("ru.wiki.fandom.com", "Серия 7")
    assert link.startswith("https://ru.wiki.fandom.com/wiki/")
    assert " " not in link


# ── откуда их берут загрузчики ───────────────────────────────────────────
def test_the_manga_answer_names_the_chapter(generator):  # noqa: F811
    cand = SongCandidate({}, make_anime(), kind=MANGA_KIND)
    assert generator._fetch_media(cand) is True
    assert cand.source_link == "https://mangadex.org/chapter/ch-42"
    assert cand.answer_variants()[-1] == cand.source_link


def test_the_sakuga_answer_names_the_post(generator, monkeypatch):  # noqa: F811
    _fake_ffmpeg(generator, monkeypatch)
    cand = SongCandidate({}, make_anime(), kind=SAKUGA_KIND)
    assert generator._fetch_media(cand) is True
    assert cand.source_link == "https://sakugabooru.com/post/show/251547"
    assert cand.answer_variants()[-1] == cand.source_link


# ── как это ложится в пак ────────────────────────────────────────────────
def _answers(cand, **kwargs) -> list[str]:
    settings = PackSettings(pct_songs=0, rounds=1, themes=1, questions=1,
                            **kwargs)
    root = ET.fromstring(animepack.build_content_xml([cand], settings))
    ns = {"s": animepack.SIQ_NS}
    return [a.text for a in root.findall(".//s:right/s:answer", ns)]


def test_the_plot_detail_answer_keeps_the_wiki_page_last():
    """У вопроса с ответом-деталью варианты свои — ссылка встаёт после них."""
    cand = SongCandidate({}, make_anime(), kind=PLOT_KIND)
    cand.plot_question = "Сколько длится способность героя?"
    cand.plot_answers = ["Пять секунд", "5 секунд"]
    cand.source_link = "https://charlotte.fandom.com/wiki/Yuu_Otosaka"
    answers = _answers(cand, pack_plot=True, pct_plot=100, plot_mode="detail",
                       gemini_key="k")
    assert answers == ["Пять секунд", "5 секунд", cand.source_link]


def test_an_empty_link_adds_no_answer():
    cand = SongCandidate({}, make_anime(), kind=PLOT_KIND)
    cand.plot_question = "Что нашёл герой?"
    cand.plot_answers = ["Тетрадь"]
    answers = _answers(cand, pack_plot=True, pct_plot=100, plot_mode="detail",
                       gemini_key="k")
    assert answers == ["Тетрадь"]
