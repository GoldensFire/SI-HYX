# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Карточки каталога из мешка с фильтрами ШИРЕ нынешних.

База Shikimori хранит карточки мешками по набору фильтров (год, типы, оценка,
исключённые жанры — см. `shiki_cache_signature`). Раньше генерация смотрела
только в мешок ровно своих фильтров: стоило исключить жанр «Исэкай», и пак
заводил пустой мешок и снова черпал каталог с сервера, хотя полный каталог
(12 811 аниме) уже лежал рядом и все нужные карточки в нём были (жалоба
пользователя: «нахуя он набирает каталог, если у меня уже все тайтлы»).

Теперь годится любой мешок, чьи фильтры ПОКРЫВАЮТ нынешние: лишнее из него
отсеивается здесь же, на месте, по полям самой карточки.
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
    if inner["years"] != outer["years"]:
        year = _card_year(card)
        if year is None or not inner["years"][0] <= year <= inner["years"][1]:
            return False
    if inner["kinds"] != outer["kinds"]:
        kind = str(card.get("kind") or "")
        if kind in outer["kinds"] and kind not in inner["kinds"]:
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

    Свой мешок идёт первым и берётся целиком, как раньше; из мешков с фильтрами
    шире — только то, что прошло бы нынешние фильтры. «Полон» значит, что хоть
    один из этих мешков был вычерпан до конца кнопкой «Обновить базу»:
    тогда сервер ничего нового под эти фильтры не отдаст."""
    inner = parse_signature(sig)
    cards = list(db_cache.cards(target, sig))
    complete = db_cache.is_complete(target, sig)
    if inner is None:
        return cards, complete
    for other, (rows, full) in db_cache.buckets(target).items():
        if other == sig:
            continue
        outer = parse_signature(other)
        if outer is None or not covers(outer, inner):
            continue
        cards += [c for c in rows if card_fits(c, outer, inner)]
        complete = complete or full
    return cards, complete
