# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ShikimoriHYX: поиск «По кэшу» — по базе Shikimori генератора аниме-паков.

Без сети и без постраничной выдачи сервера: карточки уже лежат в базе
(`animepack_shikimori_db.json`), поэтому вся выдача готова сразу. Фильтры
вкладки проверяются по самой карточке (те же правила, что у сервера:
название, тип, статус, жанры) и локально (`AnimeFilter.matches_local`).
Просмотры считаются прямо из карточки; индекс популярности — дороже (секунды
на всю базу), его досчитывает _ViewsTask только там, где он нужен.
"""
from __future__ import annotations

import random
from dataclasses import replace

from shikimori_api import Anime, kinds_for, statuses_for

from .pack_index import target_for, views_from_stats

# Длина сериала у фильтров «ТВ-сериал (до 13 эп.)» и т. п.: сервер делит tv
# по числу эпизодов, в карточке есть только kind=tv и episodes.
_TV_LENGTH = {"tv_13": (0, 16), "tv_24": (17, 28), "tv_48": (29, 1 << 30)}


def _num(v, cast, default):
    try:
        return cast(v)
    except (TypeError, ValueError):
        return default


def _date(d) -> str | None:
    """{year, month, day} карточки → «YYYY-MM-DD» (или короче, что известно)."""
    if not isinstance(d, dict):
        return None
    year = _num(d.get("year"), int, 0)
    if not year:
        return None
    out = f"{year:04d}"
    for key in ("month", "day"):
        part = _num(d.get(key), int, 0)
        if not part:
            break
        out += f"-{part:02d}"
    return out


def anime_from_card(card: dict) -> Anime:
    """Тайтл вкладки из GraphQL-карточки базы."""
    poster = card.get("poster") or {}
    return Anime(
        id=_num(card.get("id"), int, 0),
        name=str(card.get("name") or ""),
        russian=str(card.get("russian") or ""),
        kind=str(card.get("kind") or ""),
        score=_num(card.get("score"), float, 0.0),
        status=str(card.get("status") or ""),
        episodes=_num(card.get("episodes") or card.get("chapters"), int, 0),
        episodes_aired=0,
        aired_on=_date(card.get("airedOn")),
        released_on=_date(card.get("releasedOn")),
        image_url=str(poster.get("mainUrl") or poster.get("originalUrl") or ""),
        url=str(card.get("url") or ""),
    )


def _fold(s) -> str:
    return str(s or "").casefold().replace("ё", "е")


def _names(card: dict) -> list:
    names = [card.get(k) for k in ("russian", "name", "english", "japanese",
                                   "licenseNameRu")]
    names += list(card.get("synonyms") or [])
    return [_fold(n) for n in names if n]


def _genre_ids(card: dict) -> set:
    return {_num(g.get("id"), int, 0) for g in (card.get("genres") or [])
            if isinstance(g, dict)}


def card_matches(card: dict, criteria, words) -> bool:
    """Серверная часть фильтра — по карточке. words — слова запроса
    (_fold): все должны найтись в одном из названий тайтла."""
    ct = criteria.content_type
    if words and not any(all(w in n for w in words) for n in _names(card)):
        return False
    kind = str(card.get("kind") or "")
    if criteria.kind in kinds_for(ct):
        span = _TV_LENGTH.get(criteria.kind)
        if span is not None:
            eps = _num(card.get("episodes"), int, 0)
            if kind != "tv" or not span[0] <= eps <= span[1]:
                return False
        elif kind != criteria.kind:
            return False
    if criteria.status in statuses_for(ct) and card.get("status") != criteria.status:
        return False
    if criteria.genres or criteria.exclude_genres:
        have = _genre_ids(card)
        if not set(criteria.genres) <= have or have & set(criteria.exclude_genres):
            return False
    return True


# Порядок серверных сортировок для выдачи из базы: (ключ, по убыванию).
_ORDERS = {
    "ranked": (lambda a, views: a.score, True),
    "name": (lambda a, views: a.title.casefold(), False),
    "aired_on": (lambda a, views: a.aired_on or "", True),
    "episodes": (lambda a, views: a.episodes, True),
    "kind": (lambda a, views: a.kind, False),
    "id": (lambda a, views: a.id, False),
}


def sort_found(found: list, order: str, views: dict) -> None:
    """Сортирует выдачу на месте, как отдал бы сервер. По умолчанию (и для
    «по популярности») — по просмотрам: с этого порядка начинают и локальные
    сортировки «по просмотрам»/«по индексу»."""
    if order == "random":
        random.shuffle(found)
        return
    key, reverse = _ORDERS.get(order, (lambda a, v: v.get(a.id, -1), True))
    found.sort(key=lambda a: key(a, views), reverse=reverse)


def search(criteria, *, stopped=lambda: False):
    """(тайтлы, {id: (просмотры, ключ франшизы Shikimori)}) из базы генератора."""
    import animepack as ap
    target = target_for(criteria.content_type)
    cards = ap.ShikimoriDbCache().all_cards(target)
    if not cards:
        raise RuntimeError("база Shikimori пуста — наберите её кнопкой «Обновить "
                           "базу» во вкладке генерации аниме-пака")
    words = [w for w in _fold(criteria.query).split() if w]
    local = criteria
    if target == "manga":
        # Глав в карточках манги нет — граница по ним отсекла бы всё.
        local = replace(criteria, episodes_min=None, episodes_max=None)
    found, info = [], {}
    for card in cards:
        if stopped():
            break
        if not isinstance(card, dict) or not card_matches(card, criteria, words):
            continue
        a = anime_from_card(card)
        if not a.id or a.id in info or not local.matches_local(a):
            continue
        found.append(a)
        info[a.id] = (views_from_stats(card), str(card.get("franchise") or ""))
    sort_found(found, criteria.order, {aid: v for aid, (v, _fr) in info.items()})
    return found, info
