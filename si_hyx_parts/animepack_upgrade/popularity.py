# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""popularity. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


def popularity(card: dict) -> float:
    """Насколько тайтл известен — та же «база индекса», по которой генератор
    паков расставляет цены (взвешенное число людей, у которых он в списках).

    Нужна там, где на один ответ приходится НЕСКОЛЬКО точных совпадений: у
    старых и малоизвестных записей названия сплошь и рядом совпадают с чужими.
    Нет статистики — ноль, и тогда выбор идёт по прежним правилам.

    Готовое число в поле popularity, если оно у карточки уже есть, важнее
    статистики списков — считать её заново незачем."""
    ready = (card or {}).get("popularity")
    if ready is not None:
        try:
            return float(ready)
        except (TypeError, ValueError):
            return 0.0
    try:
        from shikimori_api import index_base_from_statuses_stats
        return float(index_base_from_statuses_stats(
            (card or {}).get("statusesStats")) or 0.0)
    except Exception:  # noqa: BLE001 — без статистики просто нет предпочтения
        return 0.0

popularity.__module__ = _api.__name__
_api.popularity = popularity
