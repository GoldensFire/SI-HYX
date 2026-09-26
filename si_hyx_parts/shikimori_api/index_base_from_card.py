# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""index_base_from_card. Public namespace: shikimori_api."""
from __future__ import annotations
import shikimori_api as _api


def index_base_from_card(card: dict) -> float:
    """Взвешенная «база индекса» из rates_statuses_stats: каждый пользователь
    даёт столько баллов, сколько весит его статус (просмотрено=10, смотрю=8,
    брошено/отложено=6, запланировано=2). При отсутствии данных вернёт 0."""
    if not isinstance(card, dict):
        return 0.0
    total = 0.0
    for s in card.get("rates_statuses_stats") or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or "").strip().lower()
        w = _api._INDEX_STATUS_WEIGHTS.get(name)
        if w:
            try:
                total += w * int(s.get("value") or 0)
            except (TypeError, ValueError):
                pass
    return total

index_base_from_card.__module__ = _api.__name__
_api.index_base_from_card = index_base_from_card
