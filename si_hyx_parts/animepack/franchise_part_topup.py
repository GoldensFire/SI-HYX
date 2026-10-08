# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Недостающие части известных франшиз в неполном каталоге.

Неполный каталог (страницы `order: random`, мешки под чужие фильтры) мог
содержать «Повелителя 4», но не первые три сезона. Число карточек тут ничего
не доказывает: 12 529 карточек хватало запасу `want`, и дозапроса не было.
Перемешивание не выберет тайтл, которого в пуле нет.

Список частей франшизы уже лежит в кэше (его спрашивают ради индекса
узнаваемости). Части, которые проходят фильтры пака по этому списку, но
отсутствуют в пуле, догружаются полными карточками пачками по 50 и
кладутся в мешок текущих фильтров — следующей генерации запрос не нужен.
Сеть для самих списков частей здесь не трогается.
"""
from __future__ import annotations

import animepack as _api

# Потолок дозапроса за одну генерацию: 30 запросов по 50 карточек.
MAX_TOPUP = 1500


def _mal(row) -> int:
    try:
        return int((row or {}).get("malId") or 0)
    except (TypeError, ValueError, AttributeError):
        return 0


def _year(row):
    aired = (row or {}).get("airedOn")
    try:
        return int((aired or {}).get("year") or 0) or None
    except (TypeError, ValueError, AttributeError):
        return None


def part_fits(row: dict, settings) -> bool:
    """Пройдёт ли часть франшизы фильтры пака по сведениям из списка частей.

    Жанров и постера в списке нет: их проверит filter_anime на полной карточке."""
    if not _mal(row) or _api.is_announced(row):
        return False
    kind = str(row.get("kind") or "").lower()
    if not settings.kinds.get(kind, False):
        return False
    year = _year(row)
    if year is None or not settings.year_from <= year <= settings.year_to:
        return False
    try:
        score = float(row.get("score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    return settings.score_from <= score <= settings.score_to


def missing_parts(db_cache, cards: list, settings) -> list[int]:
    """MAL id подходящих частей франшиз пула, которых в самом пуле нет."""
    have = {_mal(card) for card in cards}
    franchises = []
    seen_keys = set()
    for card in cards:
        key = str((card or {}).get("franchise") or "").strip()
        if key and key not in seen_keys:
            seen_keys.add(key)
            franchises.append(key)
    out, seen = [], set()
    for key in franchises:
        for row in db_cache.franchise(key) or ():
            mal = _mal(row)
            if mal and mal not in have and mal not in seen and part_fits(row, settings):
                seen.add(mal)
                out.append(mal)
    return out


def topup(gen, sig: str, take) -> int:
    """Догружает недостающие части в пул; отдаёт число добавленных карточек."""
    cards = list(gen._card_cache.values())
    missing = missing_parts(gen.db_cache, cards, gen.s)
    if not missing:
        return 0
    if len(missing) > MAX_TOPUP:
        gen.log(f"Каталог: недостающих частей франшиз {len(missing)}, "
                f"догружаю {MAX_TOPUP}; остальные — после «Обновить базу».")
        missing = missing[:MAX_TOPUP]
    else:
        gen.log(f"Каталог: догружаю {len(missing)} недостающих частей "
                "известных франшиз…")
    added = 0
    try:
        for batch in _api._chunks(missing, _api.SHIKIMORI_BATCH):
            if gen.stopped():
                break
            try:
                rows = gen.shikimori.animes_by_ids(batch)
            except _api.AnimePackApiError as error:
                gen.log(f"Shikimori: {error} — части франшиз догружены не все")
                break
            fits = [card for card in rows if _api.filter_anime(card, gen.s)]
            if fits:
                gen.db_cache.add_cards("anime", sig, fits)
                added += take(fits)
    finally:
        from .generation_checkpoint import checkpoint
        checkpoint(gen)
    gen.log(f"Каталог: добавлено {added} частей франшиз.")
    return added
