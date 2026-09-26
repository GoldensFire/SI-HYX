# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""char_fav_level. Public namespace: animepack."""
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
