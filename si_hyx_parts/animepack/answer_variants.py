# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Варианты ответа без дублей. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


def _dedup_answers(variants) -> list[str]:
    """Схлопывает варианты ответа и фильтрует иероглифические ДОП-варианты.

    Первый вариант — готовый основной ответ. Его нельзя выбрасывать целиком
    только потому, что японское название ПЕСНИ стоит внутри русской строки:
    иначе следом первым оказывалось ромадзи тайтла без года и без песни.
    """
    out, seen = [], set()
    for v in variants:
        text = str(v or "").strip()
        if not text or text.casefold() in seen:
            continue
        if out and _api.has_cjk(text):
            continue
        seen.add(text.casefold())
        out.append(text)
    return out

_dedup_answers.__module__ = _api.__name__
_api._dedup_answers = _dedup_answers
