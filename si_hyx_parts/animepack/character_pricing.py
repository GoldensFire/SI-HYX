# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Цена вопроса о персонаже: уровень по избранному, скидка и множитель. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


def char_fav_level(favorites) -> int:
    """Уровень персонажа 1…15 по числу добавивших в избранное."""
    try:
        value = int(favorites)
    except (TypeError, ValueError):
        return _api.CHAR_MAX_LEVEL
    for level, threshold in enumerate(_api.CHAR_FAV_LEVELS, start=1):
        if value >= threshold:
            return level
    return _api.CHAR_MAX_LEVEL

char_fav_level.__module__ = _api.__name__
_api.char_fav_level = char_fav_level

def char_question_level(title_level: int, favorites) -> int:
    """Сложность персонажа равна сложности показанного тайтла.

    ``favorites`` оставлен в сигнатуре для совместимости со старыми вызовами и
    кэшем, но больше не меняет уровень вопроса.
    """
    try:
        return max(1, min(_api.MAX_LEVEL, int(title_level)))
    except (TypeError, ValueError):
        return _api.MAX_LEVEL

char_question_level.__module__ = _api.__name__
_api.char_question_level = char_question_level


# (от скольких «в избранном», сколько очков скидки). Пороги взяты из лесенки
# CHAR_FAV_LEVELS: 2000+ — первая тройка уровней (у «Лелуша» 10 740),
# 600+ — заметный герой хита, 180+ — узнаваемый второстепенный.
CHAR_FAV_DISCOUNT = ((2000, 3), (600, 2), (180, 1))


def char_fav_price_shift(cand) -> int:
    """Скидка (≤ 0) к цене вопроса-персонажа за число «в избранном»."""
    if not getattr(cand, "is_character", False):
        return 0
    try:
        fav = int(getattr(cand, "char_favorites", -1))
    except (TypeError, ValueError):
        return 0
    for threshold, discount in CHAR_FAV_DISCOUNT:
        if fav >= threshold:
            return -discount
    return 0

char_fav_price_shift.__module__ = _api.__name__
_api.char_fav_price_shift = char_fav_price_shift


_api.CHAR_FAV_DISCOUNT = CHAR_FAV_DISCOUNT


def char_price_mult(cand) -> float:
    """Во сколько раз вопрос-персонаж дороже вопроса о самом тайтле."""
    if getattr(cand, "kind", "") != _api.CHAR_KIND:
        return 1.0
    main = bool((getattr(cand, "character", None) or {}).get("main"))
    return _api._CHAR_PRICE_MULT[main]

char_price_mult.__module__ = _api.__name__
_api.char_price_mult = char_price_mult
