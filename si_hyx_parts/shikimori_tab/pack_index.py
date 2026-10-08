# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ShikimoriHYX: индекс популярности и просмотры из базы генератора аниме-паков.

Огонёк в строке и сортировка «По индексу популярности» считаются ровно тем же
кодом, что и сложность вопросов пака (`db_rows.title_rows` → `SongCandidate.index`):
узнаваемость серии, надбавка «в избранном» по соседям, возраст по обоим краям
выпуска. Карточки берутся из той же базы (`animepack_shikimori_db.json`);
тайтлы, которых в ней нет, дозапрашиваются пачками GraphQL и ложатся туда же
(мешок `SHIKIMORIHYX_BUCKET`), вместе с частями их франшиз. Отдельного кеша
у вкладки больше нет.
"""
from __future__ import annotations

# Сколько карточек в одном GraphQL-запросе (предел Shikimori — 50).
BATCH = 50


def target_for(content_type: str) -> str:
    """Раздел базы генератора для типа контента вкладки."""
    return "anime" if str(content_type or "anime") == "anime" else "manga"


def views_from_stats(card: dict) -> int:
    """«Просмотры» (просмотрено + смотрю + брошено) из GraphQL-карточки."""
    total = 0
    for row in (card or {}).get("statusesStats") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "").strip().lower() in ("completed", "watching", "dropped"):
            try:
                total += int(row.get("count") or 0)
            except (TypeError, ValueError):
                pass
    return total


def _cards_by_shiki(cache, target: str) -> dict:
    out = {}
    for card in cache.all_cards(target):
        try:
            out.setdefault(int(card.get("id") or 0), card)
        except (TypeError, ValueError):
            continue
    out.pop(0, None)
    return out


def _fetch_missing(ap, cache, target, ids, stopped, progress) -> int:
    """Дозапрашивает карточки, которых нет в базе, и части их франшиз."""
    api = ap.ShikimoriApi(ap.make_session())
    fetch = api.mangas_by_ids if target == "manga" else api.animes_by_ids
    fresh = []
    total = len(ids)
    for start in range(0, total, BATCH):
        if stopped():
            break
        chunk = ids[start:start + BATCH]
        try:
            fresh.extend(fetch(chunk))
        except Exception:  # noqa: BLE001 — недоступная пачка просто без индекса
            pass
        progress(min(start + BATCH, total), total)
    if fresh:
        cache.add_cards(target, ap.SHIKIMORIHYX_BUCKET, fresh)
    keys = sorted({str(c.get("franchise") or "").strip() for c in fresh}
                  - {""})
    ask = [key for key in keys if cache.franchise(key) is None]
    if ask and not stopped():
        try:
            loaded = api.franchise_parts(ask) or {}
        except Exception:  # noqa: BLE001 — без частей индекс = свой у тайтла
            loaded = {}
        cache.add_franchises({key: list(rows) for key, rows in loaded.items()
                              if key in ask})
    return len(fresh)


def compute(ids, content_type: str, *, network: bool, stopped, progress) -> dict:
    """{id Shikimori: строка базы генератора} для указанных тайтлов.

    Строка — то же, что показывает панель «Обновить базу»: index, level,
    favorites, franchise_index, card, candidate. network=False — только то,
    что уже лежит в базе (режим «По кэшу»)."""
    import animepack as ap
    from si_hyx_parts.animepack_tab import db_rows
    target = target_for(content_type)
    cache = ap.ShikimoriDbCache()
    by_id = _cards_by_shiki(cache, target)
    wanted = [int(i) for i in ids]
    missing = [i for i in wanted if i not in by_id]
    if network and missing and not stopped():
        if _fetch_missing(ap, cache, target, missing, stopped, progress):
            cache.save()
            by_id = _cards_by_shiki(cache, target)
    cards = [by_id[i] for i in wanted if i in by_id]
    if not cards:
        return {}
    rows = db_rows.title_rows(cache, target, cards=cards)
    return {int(row["id"]): row for row in rows if row.get("id")}


def tooltip(row: dict) -> str:
    """Подсказка к огоньку: формула индекса генератора пака."""
    from si_hyx_parts.animepack_tab import index_tooltip
    cand = (row or {}).get("candidate")
    if cand is None:
        return ""
    body = index_tooltip.build_text(cand)
    if not body:
        return ""
    value = f"{int(round(float(row.get('index') or 0))):,}".replace(",", " ")
    return "\n".join([f"Индекс популярности — {value}", "", body, "",
                      "Тот же индекс и та же база Shikimori, что в генерации "
                      "аниме-пака."])
