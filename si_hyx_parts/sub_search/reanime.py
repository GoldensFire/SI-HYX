# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Ссылка «смотреть серию с этого момента» на Re:ANIME (reanime.to).

У сайта открытый JSON: `/api/v1/search?q=` отдаёт `anime_id` (slug страницы) и
`anilist_id`, `/api/v1/anime/<slug>` — ещё и `mal_id` (= id Shikimori). Страница
`/watch/<slug>?ep=<n>&t=<секунды>` открывает серию, плеер начинает с `t`
(параметр читает сам сайт: `start_at` или `t`). Найденный slug кэшируется в
corpus.sqlite рядом с сопоставлениями AniZip.
"""
from __future__ import annotations

import re
from urllib.parse import quote, urlencode

import sub_search as _api

from .engine import _ep_num
from .http_client import HttpError
from .sources import AniZip

# slug из ответа сайта идёт в путь ссылки — только такой вид.
_SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,160}")
NOT_FOUND_TTL = 3 * 86400          # «на сайте нет» — спросить снова через 3 дня
SEARCH_RESULTS = 8                 # сколько результатов поиска сверять
DETAIL_CHECKS = 4                  # …из них — карточкой с mal_id (если AniList не знаем)
LEAD_IN_S = 2                      # начать чуть раньше реплики


def _valid_slug(slug) -> str:
    slug = str(slug or "").strip()
    return slug if _SLUG.fullmatch(slug) else ""


def watch_url(slug: str, episode=None, seconds: float = 0.0) -> str:
    """Ссылка на серию с моментом (ep — номер серии, фильм — 1)."""
    slug = _valid_slug(slug)
    if not slug:
        return ""
    ep = _ep_num(episode) or 1
    params = {"ep": max(1, ep)}
    t = int(max(0.0, float(seconds or 0.0) - LEAD_IN_S))
    if t:
        params["t"] = t
    return f"{_api.REANIME_BASE}/watch/{quote(slug)}?{urlencode(params)}"


def _int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def find_slug(http, corpus, shiki_id: int, names) -> str:
    """slug тайтла на Re:ANIME по id Shikimori ("" — не нашёлся).

    Поиск по названиям; верным считается результат с тем же AniList id, что у
    AniZip, а без него — тот, чья карточка называет тот же MAL id."""
    shiki_id = int(shiki_id)
    k = f"reanime:{shiki_id}"
    known = corpus.kv_get(k, _api.MAPPING_TTL)
    if isinstance(known, dict):
        slug = _valid_slug(known.get("slug"))
        if slug or corpus.kv_get(k, NOT_FOUND_TTL) is not None:
            return slug
    anilist = _int(AniZip(http, corpus).mappings("mal_id", shiki_id).get("anilist_id"))
    slug, checked, net_ok = "", set(), False
    for name in dict.fromkeys(str(n or "").strip() for n in names):
        if not name or slug:
            continue
        try:
            resp = http.get(f"{_api.REANIME_BASE}/api/v1/search", params={"q": name})
            results = (resp.json() or {}).get("results") or []
            net_ok = True
        except (HttpError, ValueError, AttributeError):
            continue
        rows = [r for r in results[:SEARCH_RESULTS] if isinstance(r, dict)]
        if anilist:
            slug = next((_valid_slug(r.get("anime_id")) for r in rows
                         if _int(r.get("anilist_id")) == anilist), "")
            if slug:
                break
        for r in rows[:DETAIL_CHECKS]:
            cand = _valid_slug(r.get("anime_id"))
            if not cand or cand in checked:
                continue
            checked.add(cand)
            try:
                card = http.get(f"{_api.REANIME_BASE}/api/v1/anime/{quote(cand)}").json()
            except (HttpError, ValueError):
                continue
            if isinstance(card, dict) and _int(card.get("mal_id")) == shiki_id:
                slug = cand
                break
    if slug or net_ok:   # сетевую ошибку не запоминаем
        corpus.kv_set(k, {"slug": slug})
    return slug


def episode_link(shiki_id: int, names, episode=None, seconds: float = 0.0,
                 stop=None) -> str:
    """Готовая ссылка на серию с моментом ("" — тайтла на сайте нет или сеть
    недоступна). Блокирует — звать из фонового потока."""
    from .corpus import Corpus
    from .http_client import Http
    http = Http(stop, timeout=(8, 20), retries=1)
    corpus = Corpus()
    try:
        return watch_url(find_slug(http, corpus, shiki_id, names), episode, seconds)
    finally:
        http.close()
        corpus.close()
