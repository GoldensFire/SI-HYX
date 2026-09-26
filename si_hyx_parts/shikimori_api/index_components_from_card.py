# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""index_components_from_card. Public namespace: shikimori_api."""
from __future__ import annotations
import shikimori_api as _api


def index_components_from_card(card: dict) -> list[tuple[str, float, int]]:
    """Разбивка «базы индекса» по статусам для подсказки: список кортежей
    (подпись, взвешенный_вклад, число_людей) по убыванию вклада. Подпись —
    каноничная RU (см. _INDEX_STATUS_LABELS). Возвращает только статусы с
    ненулевым числом людей; сумма взвешенных вкладов == index_base_from_card."""
    if not isinstance(card, dict):
        return []
    agg: dict[str, list] = {}  # подпись -> [взвешенный_вклад, число_людей]
    for s in card.get("rates_statuses_stats") or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or "").strip().lower()
        w = _api._INDEX_STATUS_WEIGHTS.get(name)
        if not w:
            continue
        try:
            cnt = int(s.get("value") or 0)
        except (TypeError, ValueError):
            cnt = 0
        if cnt <= 0:
            continue
        label = _api._INDEX_STATUS_LABELS.get(name, name.capitalize())
        cur = agg.setdefault(label, [0.0, 0])
        cur[0] += w * cnt
        cur[1] += cnt
    out = [(label, wv, cnt) for label, (wv, cnt) in agg.items()]
    out.sort(key=lambda x: x[1], reverse=True)
    return out

index_components_from_card.__module__ = _api.__name__
_api.index_components_from_card = index_components_from_card

def index_base_from_statuses_stats(stats) -> float:
    """То же, что index_base_from_card, но для GraphQL-формы
    `statusesStats { status count }` (там ключи английские, а не локализованные
    подписи REST-карточки). Нужна генератору аниме-паков: он и так тянет
    карточки через GraphQL пачками по 50 и не должен ради индекса ходить
    в REST по одному тайтлу."""
    total = 0.0
    for s in (stats or []):
        if not isinstance(s, dict):
            continue
        w = _api._INDEX_STATUS_WEIGHTS.get(str(s.get("status") or "").strip().lower())
        if w:
            try:
                total += w * int(s.get("count") or 0)
            except (TypeError, ValueError):
                pass
    return total

index_base_from_statuses_stats.__module__ = _api.__name__
_api.index_base_from_statuses_stats = index_base_from_statuses_stats
