# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""char_fav_price_shift. Public namespace: animepack.

Скидка к цене вопроса-персонажа за его известность (просьба пользователя):
чем больше людей добавили героя в избранное на Shikimori, тем вернее его
узнают по портрету — и тем дешевле вопрос. Уровень вопроса при этом НЕ
меняется: он по-прежнему равен уровню тайтла, скидка снимается только с
надбавки за роль (+4 главному, +6 второстепенному). Работает только в минус:
малое или неизвестное избранное цену не поднимает — редкость героя уже
оплачена надбавкой за роль.
"""
from __future__ import annotations
import animepack as _api

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
