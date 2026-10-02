# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Объединение пригодных карточек кэша и отдельная проверка его полноты.

Более узкая выборка тоже содержит полезные карточки. Она не доказывает,
что весь текущий запрос вычерпан, но отбрасывать её содержимое нельзя.
"""
from __future__ import annotations


def parse_signature(sig: str):
    """Фильтры мешка из его ключа или None, если ключ не разобрать."""
    try:
        years, kinds, score, excl = str(sig).split("|")
        y_from, y_to = (int(y) for y in years.split("-"))
        return {"years": (y_from, y_to),
                "kinds": frozenset(k for k in kinds.split(",") if k),
                "score": int(score),
                "excl": frozenset(int(g) for g in excl.split(",") if g)}
    except (TypeError, ValueError):
        return None


def covers(outer: dict, inner: dict) -> bool:
    """Все ли карточки с фильтрами inner найдутся в мешке с фильтрами outer."""
    return (outer["years"][0] <= inner["years"][0]
            and outer["years"][1] >= inner["years"][1]
            and outer["kinds"] >= inner["kinds"]
            and outer["score"] <= inner["score"]
            and outer["excl"] <= inner["excl"])


def _card_year(card: dict):
    aired = card.get("airedOn")
    if isinstance(aired, dict):
        try:
            return int(aired.get("year") or 0) or None
        except (TypeError, ValueError):
            return None
    return None


def _card_genres(card: dict) -> set:
    out = set()
    for g in card.get("genres") or []:
        try:
            out.add(int(g.get("id")))
        except (AttributeError, TypeError, ValueError):
            continue
    return out


def card_fits(card: dict, outer: dict, inner: dict) -> bool:
    """Прошла бы карточка из мешка outer через фильтры inner на сервере.

    Каждый фильтр проверяется, только если он и правда УЖЕ, чем у мешка:
    у карточки может не быть года, и отбрасывать её там, где сервер её отдал
    бы и так, незачем. Карточки чужого рода (манхва и маньхуа, добранные
    отдельным запросом, — manga_catalog_topup) типы мешка не ограничивают."""
    if not (inner["years"][0] <= outer["years"][0]
            and inner["years"][1] >= outer["years"][1]):
        year = _card_year(card)
        if year is None or not inner["years"][0] <= year <= inner["years"][1]:
            return False
    kind = str(card.get("kind") or "")
    if kind and kind not in inner["kinds"]:
        return False
    if inner["score"] > outer["score"]:
        try:
            if float(card.get("score") or 0) < inner["score"]:
                return False
        except (TypeError, ValueError):
            return False
    extra = inner["excl"] - outer["excl"]
    if extra and _card_genres(card) & extra:
        return False
    return True


def cached_catalog(db_cache, target: str, sig: str) -> tuple[list, bool]:
    """(карточки под фильтры sig из всех подходящих мешков, полон ли каталог).

    Сначала собственная выборка, затем остальные, без дублей по MAL id.
    Полнота доказывается отдельно для каждого запрошенного типа: несколько
    полных выборок манги и манхвы могут вместе покрыть весь запрос."""
    inner = parse_signature(sig)
    cards = list(db_cache.cards(target, sig))
    complete = db_cache.is_complete(target, sig)
    if inner is None:
        return cards, complete
    seen = {str(c.get("malId") or c.get("id")) for c in cards}
    covered = set(inner["kinds"]) if complete else set()
    for other, (rows, full) in db_cache.buckets(target).items():
        outer = parse_signature(other)
        if outer is None:
            continue
        if full:
            covered.update(kind for kind in inner["kinds"]
                           if covers(outer, dict(inner, kinds={kind})))
        if other == sig:
            continue
        for card in rows:
            key = str(card.get("malId") or card.get("id") or "")
            if key and key not in seen and card_fits(card, outer, inner):
                cards.append(card)
                seen.add(key)
    return cards, complete or bool(inner["kinds"] <= covered)
