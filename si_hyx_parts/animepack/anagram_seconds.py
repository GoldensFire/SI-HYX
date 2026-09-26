# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""anagram_seconds. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


def anagram_seconds(text: str, chars_per_sec: float = _api.ANAGRAM_CHARS_PER_SEC) -> int:
    """Сколько секунд держать анаграмму на экране (0 — без таймера).

    Считаются ВСЕ символы вопроса, вместе с пробелами и знаками: игрок видит
    именно их. Дробь округляется ВВЕРХ — обрывать показ на середине секунды
    незачем, — а совсем короткому тексту достаётся ANAGRAM_MIN_SECONDS."""
    cps = max(0.0, float(chars_per_sec or 0.0))
    length = len(str(text or ""))
    if cps <= 0 or not length:
        return 0
    return max(_api.ANAGRAM_MIN_SECONDS, _api.math.ceil(length / cps))

anagram_seconds.__module__ = _api.__name__
_api.anagram_seconds = anagram_seconds
