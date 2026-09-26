# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Названия тайтлов в виде, сравнимом с метками Pixiv.

Отдельным модулем, чтобы адаптер Pixiv оставался коротким: сюда же ходит и
кэш каталога Shikimori, когда собирает набор всех известных названий (см.
ShikimoriDbCache.title_index).
"""
from __future__ import annotations


# Короче этого числа знаков метку с названием тайтла не сверяем: «Air», «One»
# и подобные названия совпадают с обычными словами, и по ним отсеялась бы
# половина честных артов.
MIN_TITLE_TAG = 4


def norm_title(text) -> str:
    """Метка Pixiv и название тайтла в одном виде — для сравнения между собой.

    Пробелы и подчёркивания Pixiv в метках не держит вовсе, а одну и ту же
    франшизу Shikimori и Pixiv пишут разными звёздами (★ / ☆)."""
    word = str(text or "").casefold()
    for bad in (" ", "　", "_", "	"):
        word = word.replace(bad, "")
    return word.replace("☆", "★")


def card_titles(card) -> set[str]:
    """Все названия карточки Shikimori в сравнимом виде."""
    out = set()
    for key in ("japanese", "name", "english", "russian"):
        word = norm_title((card or {}).get(key))
        if word:
            out.add(word)
    return out
