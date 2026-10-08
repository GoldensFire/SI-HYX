# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Сколько узнаваемости франшизы достаётся конкретной части.

Продолжение основной истории узнают по всей серии: «Доктор Стоун: Научное
будущее. Часть 3» знают ровно как «Доктора Стоуна». Короткое ответвление —
фильм, спешл, OVA — такой узнаваемости не наследует: «Наруто 3: Бунт зверей»
по своей карточке уровня 5, а с индексом франшизы выходил уровнем 2, и
вспомогательные фильмы становились удобными кандидатами под лёгкий пак.

Ответвлению засчитывается среднее геометрическое своего индекса и индекса
серии: на лесенке уровней это примерно середина между ними.
"""
from __future__ import annotations

import math

# Основная история: сериал и длинный ONA (сиквелы бывают и такими —
# «ДжоДжо: Каменный океан»). Короткий ONA — обычно спешл.
MAIN_KINDS = frozenset({"tv"})
LONG_KINDS = frozenset({"ona"})
MAIN_MIN_EPISODES = 6


def is_main_part(card: dict) -> bool:
    """Часть основной истории франшизы, а не короткое ответвление."""
    kind = str((card or {}).get("kind") or "").lower()
    if kind in MAIN_KINDS:
        return True
    if kind in LONG_KINDS:
        try:
            return int((card or {}).get("episodes") or 0) >= MAIN_MIN_EPISODES
        except (TypeError, ValueError):
            return False
    return False


def inherited_index(card: dict, own: float, franchise: float) -> float:
    """Индекс франшизы, который засчитывается этой части."""
    franchise = float(franchise or 0.0)
    if franchise <= 0 or is_main_part(card):
        return franchise
    return math.sqrt(max(0.0, float(own or 0.0)) * franchise)
