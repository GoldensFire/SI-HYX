# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""song_difficulty_bonus. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


def song_difficulty_bonus(difficulty) -> int:
    """0…SONG_DIFF_BONUS_MAX очков сверху за сложность песни."""
    try:
        d = float(difficulty)
    except (TypeError, ValueError):
        return 0
    if d <= 0 or d > 100:
        return 0
    return int(round((100.0 - d) / 100.0 * _api.SONG_DIFF_BONUS_MAX))

song_difficulty_bonus.__module__ = _api.__name__
_api.song_difficulty_bonus = song_difficulty_bonus
