# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""views_from_card. Public namespace: shikimori_api."""
from __future__ import annotations
import shikimori_api as _api


def views_from_card(card: dict) -> int:
    """Считает «просмотры» (completed+watching+dropped) из карточки тайтла.
    Запланировано/отложено НЕ учитываются. При отсутствии данных вернёт 0."""
    if not isinstance(card, dict):
        return 0
    total = 0
    for s in card.get("rates_statuses_stats") or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or "").strip().lower()
        if name in _api.VIEW_STATUSES:
            try:
                total += int(s.get("value") or 0)
            except (TypeError, ValueError):
                pass
    return total

views_from_card.__module__ = _api.__name__
_api.views_from_card = views_from_card
