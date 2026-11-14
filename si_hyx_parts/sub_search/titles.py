# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Тайтлы для «Поиска по сабам»: база Shikimori генератора аниме-паков и уровни.

Тайтлы — та же база, что у ShikimoriHYX «По кэшу» (`animepack_shikimori_db.json`),
уровень — заготовка `catalog_levels.json`, которую пишет «Обновить базу»
(та же формула, что огонёк ShikimoriHYX и цена вопроса пака: 1 — самый
узнаваемый). Если заготовки нет или тайтл новее неё — уровень считается
на месте тем же кодом (`pack_index.compute`).
"""
from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass


# Порядок обхода.
ORDER_EASY = "easy"        # от лёгкого к сложному
ORDER_HARD = "hard"        # от сложного к лёгкому
ORDER_VIEWS = "views"      # по просмотрам Shikimori
ORDER_RANDOM = "random"

ORDER_LABELS = {
    ORDER_EASY: "От лёгкого к сложному",
    ORDER_HARD: "От сложного к лёгкому",
    ORDER_VIEWS: "По просмотрам",
    ORDER_RANDOM: "Случайно",
}

# Группы типов → kind карточки Shikimori.
KIND_GROUPS = {
    "tv": ("tv", "tv_special"),
    "movie": ("movie",),
    "ova": ("ova", "ona"),
    "special": ("special",),
}
KIND_GROUP_LABELS = {"tv": "ТВ-сериалы", "movie": "Фильмы", "ova": "OVA / ONA",
                     "special": "Спешлы"}


@dataclass
class TitleInfo:
    id: int
    card: dict
    anime: object            # shikimori_api.Anime
    level: int               # 0 — неизвестен
    views: int
    franchise: str


def load_levels(db_path: str) -> dict:
    """{id: уровень} из catalog_levels.json рядом с базой (пусто — нет файла)."""
    path = os.path.join(os.path.dirname(db_path), "catalog_levels.json")
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return {}
    out = {}
    for k, v in ((raw or {}).get("anime") or {}).items():
        try:
            out[int(k)] = int(v[0])
        except (TypeError, ValueError, IndexError):
            continue
    return out


def compute_rows(ids, stopped=lambda: False) -> dict:
    """{id: строка базы генератора} (index, level…) — как огонёк ShikimoriHYX."""
    if not ids:
        return {}
    from si_hyx_parts.shikimori_tab import pack_index
    try:
        return pack_index.compute(list(ids), "anime", network=False,
                                  stopped=stopped, progress=lambda *_: None)
    except Exception:  # noqa: BLE001 — без индекса тайтл всё равно показывается
        return {}


def load_titles(kind_groups, level_min: int, level_max: int, order: str,
                stopped=lambda: False, log=lambda _m: None):
    """(упорядоченный список TitleInfo, {id: карточка}, {норм. название: id})."""
    import animepack as ap
    from si_hyx_parts.shikimori_tab.cache_search import anime_from_card
    from si_hyx_parts.shikimori_tab.pack_index import views_from_stats
    from .sources import _norm

    cache = ap.ShikimoriDbCache()
    cards = cache.all_cards("anime")
    if not cards:
        raise RuntimeError("база Shikimori пуста — наберите её кнопкой «Обновить базу» "
                           "во вкладке «Генерация аниме-пака»")
    kinds = set()
    for g in kind_groups or KIND_GROUPS:
        kinds |= set(KIND_GROUPS.get(g, ()))
    levels = load_levels(str(cache.path))
    by_id: dict[int, dict] = {}
    names: dict[str, int] = {}
    views_of: dict[int, int] = {}
    for card in cards:
        if not isinstance(card, dict):
            continue
        try:
            aid = int(card.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if not aid or aid in by_id:
            continue
        by_id[aid] = card
        views_of[aid] = views_from_stats(card)
    # Название → самый просматриваемый тайтл с ним (для каталогов архива без id).
    for aid in sorted(by_id, key=lambda i: -views_of[i]):
        card = by_id[aid]
        for n in [card.get("name"), card.get("english"), *(card.get("synonyms") or [])]:
            key = _norm(n)
            if key and key not in names:
                names[key] = aid

    missing = [aid for aid, c in by_id.items()
               if aid not in levels and str(c.get("kind") or "") in kinds]
    if missing and not stopped():
        log(f"Уровни {len(missing)} тайтлов нет в заготовке — считаю…")
        for aid, row in compute_rows(missing, stopped).items():
            try:
                levels[int(aid)] = int(row.get("level") or 0)
            except (TypeError, ValueError):
                pass

    out = []
    for aid, card in by_id.items():
        if str(card.get("kind") or "") not in kinds:
            continue
        level = int(levels.get(aid, 0) or 0)
        if level and not (level_min <= level <= level_max):
            continue
        if not level and (level_min > 1 or level_max < 99):
            continue  # неизвестный уровень не проходит заданную рамку
        out.append(TitleInfo(aid, card, anime_from_card(card), level, views_of[aid],
                             str(card.get("franchise") or "").strip()))
    if order == ORDER_RANDOM:
        random.shuffle(out)
    elif order == ORDER_VIEWS:
        out.sort(key=lambda t: -t.views)
    elif order == ORDER_HARD:
        out.sort(key=lambda t: (not t.level, -t.level, t.views))
    else:
        out.sort(key=lambda t: (t.level or 99, -t.views))
    return out, by_id, names
