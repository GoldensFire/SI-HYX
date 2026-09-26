# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""index_level. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


def index_level(index, manga: bool = False) -> int:
    """Уровень сложности тайтла: 1 — узнают все, 15 — почти никто.

    manga=True — книжные пороги и книжный индекс. Лесенка у книг та же самая,
    но начинается она с MANGA_MIN_LEVEL: книгу, которую не экранизировали,
    знают только читавшие, и первые уровни («узнают все») ей не положены ни
    при какой начитанности (см. manga_scale.py). Это ровно то же число, что
    даёт index_level(manga_reach(index)) на общей шкале."""
    try:
        value = float(index)
    except (TypeError, ValueError):
        return _api.MAX_LEVEL
    if manga:
        ladder, first = _api.MANGA_INDEX_LEVELS, _api.MANGA_MIN_LEVEL
    else:
        ladder, first = _api.INDEX_LEVELS, 1
    for level, threshold in enumerate(ladder, start=first):
        if value >= threshold:
            return level
    return _api.MAX_LEVEL

index_level.__module__ = _api.__name__
_api.index_level = index_level
