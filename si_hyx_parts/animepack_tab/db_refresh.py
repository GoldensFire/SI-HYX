# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Точечное обновление строк панели базы: тайтл и целая франшиза.

Идёт в рабочем потоке панели (DbTableDialog._work): здесь сеть и кэш, ни
одного виджета. Франшиза обновляется целиком по ПКМ на её строке (просьба
пользователя): карточки всех её частей, что уже лежат в базе, их «в
избранном» и сам список частей.
"""
from __future__ import annotations

# animes(ids:) у Shikimori отдаёт не больше пятидесяти карточек за запрос.
BATCH = 50


def _api():
    from animepack_api import ShikimoriApi
    return ShikimoriApi()


def _fetch(shiki, target: str):
    return shiki.mangas_by_ids if target == "manga" else shiki.animes_by_ids


def _remember_favorites(cache, shiki, target: str, card: dict,
                        fallback: int) -> None:
    shiki_id = int(card.get("id") or fallback)
    try:
        favorites = shiki.title_favorites(
            shiki_id, target, str(card.get("url") or ""))
    except TypeError:  # старая подмена клиента в тестах/плагинах
        favorites = shiki.title_favorites(shiki_id, target)
    if favorites >= 0:
        cache.remember_memo(f"{target}_favorites", shiki_id, favorites)


def _remember_parts(cache, shiki, keys) -> None:
    keys = sorted({str(key).strip() for key in keys if str(key).strip()})
    if not keys:
        return
    parts = shiki.franchise_parts(keys) or {}
    got = {key: parts[key] for key in keys if key in parts}
    if got:
        cache.add_franchises(got)


def read_title(cache, target: str, ident: int) -> str:
    """Перечитать одну карточку, её избранное и части франшизы."""
    shiki = _api()
    rows = _fetch(shiki, target)([ident])
    card = rows[0] if rows else None
    if not isinstance(card, dict):
        raise RuntimeError("Shikimori не вернул карточку")
    if not cache.replace_title_card(target, card):
        raise RuntimeError("карточка исчезла из локальной базы")
    _remember_favorites(cache, shiki, target, card, ident)
    _remember_parts(cache, shiki, [card.get("franchise") or ""])
    cache.save()
    return str(card.get("russian") or card.get("name") or ident)


def franchise_ids(cache, target: str, key: str) -> list[int]:
    """Номера Shikimori всех частей франшизы, что лежат в каталоге базы."""
    out = set()
    for card in cache.all_cards(target):
        if str(card.get("franchise") or "").strip() != key:
            continue
        try:
            ident = int(card.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if ident > 0:
            out.add(ident)
    return sorted(out)


def read_franchise(cache, target: str, key: str) -> int:
    """Перечитать все части франшизы в каталоге; вернуть, сколько обновлено."""
    ids = franchise_ids(cache, target, key)
    if not ids:
        raise RuntimeError("частей франшизы в локальной базе нет")
    shiki = _api()
    fetch = _fetch(shiki, target)
    done, keys = 0, {key}
    for start in range(0, len(ids), BATCH):
        for card in fetch(ids[start:start + BATCH]) or []:
            if not isinstance(card, dict):
                continue
            if not cache.replace_title_card(target, card):
                continue
            done += 1
            _remember_favorites(cache, shiki, target, card, 0)
            # Часть могла переехать в другую франшизу — её список тоже свежий.
            keys.add(str(card.get("franchise") or ""))
    if not done:
        raise RuntimeError("Shikimori не вернул карточки франшизы")
    _remember_parts(cache, shiki, keys)
    cache.save()
    return done
