# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Строки для окна «Что в базе»: тайтлы и персонажи из кэша Shikimori.

Отдельно от самого окна, потому что здесь нет ни одного виджета: это чистый
разбор кэша в готовые к показу значения (узнаваемость, сложность, избранное).
Так его можно посчитать и проверить без запущенного интерфейса.
"""
from __future__ import annotations

import animepack as ap


def filter_kinds(cards, kinds=None) -> list:
    """Карточки только разрешённых родов (None — все, как есть)."""
    if kinds is None:
        return list(cards)
    allowed = {str(k) for k in kinds}
    return [c for c in cards if str((c or {}).get("kind") or "") in allowed]


def title_rows(cache, target: str = "anime", kinds=None, *, cards=None) -> list[dict]:
    """Тайтлы каталога: название, год, оценка, индекс и сложность.

    Индекс считается ровно тем же кодом, что и в паке (SongCandidate), — иначе
    таблица показывала бы одно, а вопросы стоили бы по другому. Узнаваемость
    франшизы тоже берётся из кэша: у сиквела она и решает и индекс, и цену.

    kinds — собственный фильтр типов в окне базы (None — все). Настройки
    генерации на содержимое этого окна не влияют.

    cards — только эти карточки базы (ShikimoriHYX считает индекс найденных
    тайтлов, а не всего каталога); None — весь раздел."""
    manga = str(target) == "manga"
    favorites = _favorites(cache, manga)
    access = cache.memo_group("favorites_access_status_v1")
    # Надбавка «в избранном» меряется по соседям по индексу — теми же, что у
    # генератора, иначе панель показывала бы другие уровни (favorites_norm).
    ap.install_favorites_norms(cache)
    cards = filter_kinds(cache.all_cards(target) if cards is None else cards, kinds)
    fr_index = _franchise_indexes(cache, cards)
    screens = _adaptation_indexes(cache, cards) if manga else {}
    ru = None
    if manga:
        from si_hyx_parts.animepack.ru_popularity_store import RuPopularityStore
        ru = RuPopularityStore(cache, {"remanga": None, "mangalib": None}, persist=False)
        ru.prefetch(cards)
    rows = []
    for card in cards:
        try:
            shiki_id = int(card.get("id") or 0)
        except (TypeError, ValueError):
            shiki_id = 0
        fav = favorites.get(shiki_id, -1)
        franchise = str(card.get("franchise") or "").strip()
        # У книги «индекс франшизы» — это узнаваемость её АНИМЕ: либо прямой
        # экранизации, либо сериала той же серии. Без неё панель показывала бы
        # «Ван-Пис» неэкранизованной книгой, а генератор — уровнем сериала.
        parts = cache.franchise(franchise) if franchise else []
        branch = ap.franchise_branch_key(card, parts)
        screen = max(fr_index.get((franchise, branch), 0.0),
                     screens.get(shiki_id, 0.0))
        cand = ap.SongCandidate(
            song={}, anime=card,
            kind=ap.MANGA_KIND if manga else ap.FRAME_KIND,
            media="manga" if manga else "anime",
            franchise_index=screen, favorites=fav)
        if ru is not None:
            cand.ru_popularity = ru.evaluate(cand, network=False)
        if manga and screen:
            # Для предпросмотра цены важен сам факт экранизации: у такой
            # страницы манги та же надбавка +2, что и в готовом паке.
            cand.adapted_from = {"cached": True}
        try:
            mal = int(card.get("malId") or 0)
        except (TypeError, ValueError):
            mal = 0
        # Индекс спрашиваем РОВНО один раз: у SongCandidate это свойство, а не
        # запомненное число, и `cand.level` пересчитал бы всю цепочку заново —
        # на полусотне тысяч карточек это лишние секунды на каждое открытие.
        index = cand.index
        rows.append({
            "id": shiki_id,
            "mal": mal,
            "url": str(card.get("url") or ""),
            "title": cand.title_ru or str(card.get("name") or ""),
            "kind": str(card.get("kind") or ""),
            "year": cand.year or 0,
            "score": cand.score,
            "base": cand.own_base,
            "favorites": fav,
            "favorites_status": ("NORMAL" if fav >= 0 else
                                 (access.get(f"{target}:{shiki_id}") or {}).get("status", "UNKNOWN")),
            "index": index,
            "level": ap.index_level(index),
            # Карточка и франшиза нужны подсказке «из чего сложился индекс»:
            # она строится по наведению, а не на все 50 тысяч строк сразу.
            "card": card,
            "media": "manga" if manga else "anime",
            "franchise": franchise,
            "franchise_branch": branch,
            "franchise_index": screen,
            "candidate": cand,
        })
    rows.sort(key=lambda row: row["index"], reverse=True)
    _rank_and_price(rows)
    return rows


def _favorites(cache, manga: bool) -> dict:
    """{id Shikimori: сколько человек добавили тайтл в избранное} из кэша.

    Ключ здесь — номер Shikimori, а не MAL: по нему открывается страница, с
    которой это число и считывается (см. ShikimoriApi.title_favorites)."""
    out = {}
    for key, value in cache.memo_group(
            "manga_favorites" if manga else "anime_favorites").items():
        try:
            out[int(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return out


def title_levels(rows, target: str) -> dict:
    """{«<раздел>:<MAL id>»: строка тайтла} — в таком виде их ищут персонажи.

    Ключ memo «characters» — «anime:<malId>», поэтому тайтлы раскладываются по
    MAL id, а не по номеру Shikimori."""
    return {f"{target}:{row['mal']}": row for row in rows}


def character_rows(cache, levels=None) -> list[dict]:
    """Персонажи, о которых база уже спрашивала, с их избранным и сложностью.

    Уровень персонажа равен уровню тайтла. levels — уже разобранные тайтлы
    (см. title_levels): панель считает их один раз на все свои вкладки, а не
    заново на каждую."""
    if levels is None:
        levels = {}
        for target in ("anime", "manga"):
            levels.update(title_levels(title_rows(cache, target), target))
    favorites = {}
    for key, value in cache.memo_group("character_favorites").items():
        try:
            favorites[int(key)] = int(value)
        except (TypeError, ValueError):
            continue
    rows, seen = [], set()
    for key, people in cache.memo_group("characters").items():
        owner = levels.get(str(key)) or {}
        for person in (people or []):
            if not isinstance(person, dict):
                continue
            try:
                cid = int(person.get("id") or 0)
            except (TypeError, ValueError):
                continue
            if cid in seen:
                continue
            seen.add(cid)
            fav = favorites.get(cid, -1)
            title_level = int(owner.get("level") or ap.MAX_LEVEL)
            cand = ap.SongCandidate(
                song={}, anime=owner.get("card") or {}, kind=ap.CHAR_KIND,
                media=str(owner.get("media") or "anime"),
                franchise_index=float(owner.get("franchise_index") or 0.0),
                favorites=int(owner.get("favorites", -1)),
                character={"id": cid, "name": person.get("name") or "",
                           "main": bool(person.get("main"))},
                char_favorites=fav)
            if cand.is_manga and cand.franchise_index:
                cand.adapted_from = {"cached": True}
            rows.append({
                "id": cid,
                "name": str(person.get("name") or ""),
                "title": str(owner.get("title") or str(key)),
                "role": "главный" if person.get("main") else "второстепенный",
                "favorites": fav,
                "title_level": title_level,
                "level": ap.char_question_level(title_level, fav),
                "owner_media": str(owner.get("media") or "anime"),
                "owner_id": int((owner.get("card") or {}).get("id") or 0),
                "owner_mal": int(owner.get("mal") or 0),
                "candidate": cand,
            })
    rows.sort(key=lambda row: (-row["favorites"], row["name"]))
    _rank_and_price(rows)
    return rows


def _rank_and_price(rows: list[dict]) -> None:
    """Место по узнаваемости и цена внутри всей открытой вкладки."""
    candidates = [row.get("candidate") for row in rows]
    candidates = [cand for cand in candidates if cand is not None]
    if candidates:
        ap.assign_prices(candidates, None)
    ordered = sorted(rows, key=lambda row: float(
        getattr(row.get("candidate"), "price_index", 0.0)), reverse=True)
    place, previous = 0, None
    for number, row in enumerate(ordered, 1):
        index = float(getattr(row.get("candidate"), "price_index", 0.0))
        if previous is None or index != previous:
            place = number
            previous = index
        row["place"] = place
        cand = row.get("candidate")
        row["price"] = int(getattr(cand, "price", 0) or 0)


def _adaptation_indexes(cache, cards) -> dict:
    """{id книги: индекс её самой заметной аниме-экранизации}.

    Карточки экранизаций берутся из того же кэша, из каталога аниме: ходить в
    сеть панель не должна. Экранизации, которой в базе нет, здесь просто не
    будет — тогда книга покажется такой, какой её видит генератор до того, как
    догрузит аниме (см. load_adaptations)."""
    by_shiki: dict = {}
    for card in cache.all_cards("anime"):
        try:
            by_shiki[int((card or {}).get("id") or 0)] = card
        except (TypeError, ValueError):
            continue
    out: dict = {}
    for card in cards:
        try:
            book_id = int((card or {}).get("id") or 0)
        except (TypeError, ValueError):
            continue
        best = 0.0
        for anime_id in ap.adaptation_ids(card or {}):
            anime = by_shiki.get(anime_id)
            if anime:
                best = max(best, ap.SongCandidate(song={}, anime=anime).own_index)
        if best:
            out[book_id] = best
    return out


def _franchise_indexes(cache, cards) -> dict:
    """{(франшиза, ветка): индекс} по частям, какие лежат в кэше.

    Части франшиз общие для аниме и манги и спрашиваются один раз на все
    генерации; здесь мы только считаем по ним индекс серии — тем же кодом, что
    и генератор (shikimori_api.franchise_parts_index)."""
    out: dict = {}
    for card in cards:
        key = str((card or {}).get("franchise") or "").strip()
        if not key:
            continue
        parts = cache.franchise(key)
        branch = ap.franchise_branch_key(card, parts)
        cache_key = (key, branch)
        if cache_key not in out:
            out[cache_key] = ap.branch_franchise_index(card, parts)
    return out


def explain_title(row, column: str = "") -> str:
    """Подсказка строки тайтла: из чего сложился индекс и откуда уровень."""
    if column == "Цена":
        return _explain_price(row)
    from . import index_tooltip
    card = row.get("card")
    if not isinstance(card, dict):
        return ""
    cand = ap.SongCandidate(song={}, anime=card,
                            media=str(row.get("media") or "anime"),
                            franchise_index=float(row.get("franchise_index")
                                                  or 0.0),
                            favorites=int(row.get("favorites", -1)))
    return index_tooltip.build_text(cand)


def explain_character(row, column: str = "") -> str:
    """Подсказка строки персонажа: почему у вопроса такой уровень."""
    if column == "Цена":
        return _explain_price(row)
    title_level = int(row.get("title_level") or ap.MAX_LEVEL)
    fav = int(row.get("favorites", -1))
    lines = [f"Персонаж — {row.get('name') or '?'}",
             "",
             f"Уровень его тайтла «{row.get('title') or '?'}» — {title_level} "
             "(из узнаваемости тайтла, см. подсказку в списке аниме)."]
    if fav >= 0:
        shift = ap.char_fav_price_shift(row.get("candidate"))
        effect = (f"скидка {shift} к цене вопроса" if shift else
                  "скидки к цене нет")
        lines += ["", f"В избранном на Shikimori: {fav} чел. — {effect} "
                       "(чем больше избранных, тем героя вернее узнают и тем "
                       "вопрос дешевле; уровень от этого не меняется)."]
    return "\n".join(lines)


def _explain_price(row) -> str:
    """Разбивка цены: уровень и все надбавки видны прямо в таблице."""
    from . import index_tooltip
    text = index_tooltip.build_price_text(row.get("candidate"))
    if not text:
        return ""
    return (text + "\n\nБазовая цена фиксирована уровнем тайтла: 1-й "
            "уровень стоит 6, каждый следующий на одно очко дороже, 15-й — "
            "20. Место в текущей сортировке на цену не влияет.")
