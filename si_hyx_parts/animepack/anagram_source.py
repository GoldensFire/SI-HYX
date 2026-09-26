# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""anagram_source. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


def anagram_source(anime: dict, lang: str = "russian",
                   max_chars: int = 0) -> str:
    """Название, из которого делается анаграмма («» — годного нет).

    Язык берётся с карточки Shikimori СТРОГО тот, что просят: русское —
    russian, английское — english, ромадзи — name. Подмены на соседний язык
    больше нет (просьба пользователя): раньше при отсутствующем, слишком
    коротком или слишком длинном русском названии вопрос молча уезжал на
    латиницу, и в русском паке всплывали анаграммы вида «HHA CEYIG MOR NN».
    Теперь такой тайтл просто уступает место следующему.

    Заодно проверяется сама письменность: у Shikimori в поле russian нередко
    лежит латиница («Ao Ashi»), а в name — иероглифы. Для русского нужны
    кириллические буквы и ни одной латинской, для английского и ромадзи —
    наоборот.

    Отсеиваются и продолжения с приписками — «Мастера меча онлайн:
    Порядковый ранг», «Второй Мэйджор 2», «Log Horizon: Entaku Houkai»
    (см. is_plain_title): в анаграмму идёт только простое название.

    max_chars (0 — без потолка) отсекает названия-простыни."""
    card = anime or {}
    by_lang = {"russian": card.get("russian"), "english": card.get("english"),
               "romaji": card.get("name")}
    key = lang if lang in _api.ANAGRAM_LANGS else "russian"
    text = " ".join(str(by_lang.get(key) or "").split())
    limit = max(0, int(max_chars or 0))
    if not text or (limit and len(text) > limit):
        return ""
    if _api.has_cjk(text) or not _api._is_lang_script(text, key):
        return ""
    if _api._letters_count(text) < _api.ANAGRAM_MIN_LETTERS or not _api.is_plain_title(text):
        return ""
    return text

anagram_source.__module__ = _api.__name__
_api.anagram_source = anagram_source
