# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_best_by_popularity. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


def _best_by_popularity(cards: list) -> _api.Optional[dict]:
    """Самая известная карточка списка (при равенстве — первая: поиск Shikimori
    уже отранжировал выдачу сам)."""
    return max(cards, key=_api.popularity) if cards else None

_best_by_popularity.__module__ = _api.__name__
_api._best_by_popularity = _best_by_popularity

def pick_exact(own: list, syn: list) -> _api.Optional[dict]:
    """Кого выбрать из ТОЧНЫХ совпадений: пришедших по собственному названию
    (own) и пришедших только из синонимов (syn).

    Обычно берётся собственное название — синонимы на Shikimori правит кто
    угодно. Но если синонимом совпал тайтл, который известен в разы лучше, верен
    он: «За гранью» — это «Kyoukai no Kanata», а не одноимённая OVA, про которую
    не слышал никто."""
    best_own = _api._best_by_popularity(own)
    best_syn = _api._best_by_popularity(syn)
    if best_own is None:
        return None
    if best_syn is not None and _api.popularity(best_syn) >= max(
            1.0, _api.popularity(best_own) * _api.SYNONYM_POPULARITY_EDGE):
        return best_syn
    return best_own

pick_exact.__module__ = _api.__name__
_api.pick_exact = pick_exact
