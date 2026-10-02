# Native Kuhi/anime-api, MIT, Copyright (c) 2026 aryaniiil. See LICENSE.
import asyncio
import base64
import hashlib
import hmac
import json
import re
import time
import unicodedata
from urllib.parse import quote, urljoin, urlparse
from si_hyx_parts.kuhi import _transport as httpx
from si_hyx_parts.kuhi import _cache
from si_hyx_parts.kuhi._http import UA, fetch_json, fetch_text
from si_hyx_parts.kuhi._match import build_titles, decode_entities, episode_meta, expected_count
from si_hyx_parts.kuhi._media import build_ctx

from . import mkissa as _api


def slugify_title(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


async def warm_watch_page(show_id: str, show, ep_num, audio: str) -> None:
    show = show or {}
    slug = show.get("slugTime") or _api.slugify_title(
        show.get("englishName") or show.get("name") or show.get("nativeName"))
    if not slug or not show_id:
        return
    page = f"{_api.REFERER}/anime/{slug}-{show_id}/{audio}/{ep_num}"
    try:
        await _api._session_get_text(page, {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": f"{_api.REFERER}/", "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1", "Upgrade-Insecure-Requests": "1"})
    except Exception:
        pass


def _normalize(value) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _extract_year(title):
    if not title:
        return None
    m = re.search(r"\b(19[0-9]{2}|20[0-9]{2})\b", str(title))
    return int(m.group(1)) if m else None


def find_best_match(results: list, titles: list, target_year, target_id):
    normalized = [_api._normalize(t) for t in titles or []]
    normalized = [t for t in normalized if t]
    best = None
    best_score = float("-inf")
    for item in results or []:
        if target_id and item.get("aniListId") and str(item["aniListId"]) != str(target_id):
            continue
        if target_id and item.get("aniListId") and str(item.get("aniListId")) == str(target_id):
            return item
        names = [_api._normalize(item.get(k)) for k in ("name", "englishName", "nativeName")]
        names = [n for n in names if n]
        if any(n in normalized for n in names):
            score = 100
        else:
            fuzzy = 0
            for name in names:
                for title in normalized:
                    if title in name or name in title:
                        value = min(len(name), len(title)) - abs(len(name) - len(title)) * 0.1
                        fuzzy = max(fuzzy, value)
            score = fuzzy
        item_year = (_api._extract_year(item.get("name")) or _api._extract_year(item.get("englishName"))
                     or _api._extract_year(item.get("nativeName")))
        year_score = 0
        if target_year and item_year:
            year_score = 50 if item_year == target_year else -200
        total = score + year_score
        if total > best_score:
            best_score = total
            best = item
    return best if best_score > 0 else None


async def resolve_series(anilist_id: int, ctx=None) -> dict:
    ctx = ctx or await build_ctx(int(anilist_id))
    key = f"np:mkissa:{anilist_id}"
    hit = _cache.cached(key, _cache.SHOW_IDENTITY_TTL)
    if hit is not None:
        return hit
    media = ctx.get("media") or {}
    anizip = ctx.get("anizip") or {}
    titles = []
    for title in build_titles(media, anizip) + list((anizip.get("titles") or {}).values()):
        if title and isinstance(title, str) and title not in titles:
            titles.append(title)
    if not titles:
        ap_id = (anizip.get("mappings") or {}).get("animeplanet_id")
        if ap_id:
            titles = [" ".join(w[:1].upper() + w[1:] for w in re.split(r"[-_]", ap_id) if w)]
    if not titles:
        raise RuntimeError(f"Could not resolve titles for AniList ID: {anilist_id}")
    start = media.get("startDate") or {}
    target_year = media.get("seasonYear") or start.get("year")
    seen = set()
    results = []
    for title in titles[:3]:
        batches = await asyncio.gather(_api.search_mkissa(title, "raw"),
                                       _api.search_mkissa(title, "sub"), return_exceptions=True)
        edges = [edge for batch in batches if isinstance(batch, list) for edge in batch]
        for edge in edges or []:
            eid = edge.get("_id")
            if eid and eid not in seen:
                seen.add(eid)
                results.append(edge)
        if any(str(row.get("aniListId") or "") == str(anilist_id) for row in results):
            break
    if not results:
        raise RuntimeError(f"No MKissa match for {titles[0]!r}")
    match = _api.find_best_match(results, titles, target_year, anilist_id)
    if not match:
        raise RuntimeError(f"No MKissa match for {titles[0]!r}")
    exact = bool(match.get("aniListId")) and str(match.get("aniListId")) == str(anilist_id)
    data = {"show_id": match.get("_id"),
            "title": match.get("englishName") or match.get("name"),
            "show": match, "mode": "local", "offset": 0,
            "score": 1.0 if exact else 0.85}
    _cache.set(key, data, _cache.SHOW_IDENTITY_TTL)
    return data


async def _fresh_show(series: dict) -> dict:
    try:
        edges = await _api.search_mkissa(series.get("title") or "", "sub")
    except Exception:
        return series.get("show") or {}
    for edge in edges or []:
        if edge.get("_id") == series.get("show_id"):
            return edge
    return series.get("show") or {}


def _coerce_numbers(values) -> list:
    nums = set()
    for value in values or []:
        if isinstance(value, bool):
            continue
        try:
            n = int(value)
        except (TypeError, ValueError):
            try:
                n = int(float(str(value)))
            except (TypeError, ValueError):
                continue
        if n > 0:
            nums.add(n)
    return sorted(nums)


def _build_lists(anilist_id: int, series: dict, sub_nums: list, dub_nums: list, ctx: dict, expected, raw_nums=()) -> dict:
    out = {"sub": [], "dub": [], "raw": []}
    for audio, nums in (("sub", sub_nums), ("dub", dub_nums), ("raw", raw_nums)):
        for n in nums:
            if n < 1:
                continue
            if expected and n > expected:
                continue
            meta = episode_meta(n, ctx)
            out[audio].append({
                "id": f"watch/mkissa/{anilist_id}/{audio}/mkissa-{n}",
                "number": n,
                "title": meta["title"] or f"Episode {n}",
                "duration": meta["duration"],
                "audio": audio,
                "filler": meta["filler"],
                "uncensored": meta["uncensored"],
                "description": meta["description"],
                "image": meta["image"],
                "airDate": meta["airDate"],
                "sourceNumber": n,
            })
    return out


async def get_episodes(anilist_id: int, ctx=None) -> dict:
    ctx = ctx or await build_ctx(int(anilist_id))
    media = ctx.get("media") or {}
    series = await _api.resolve_series(int(anilist_id), ctx)
    show = await _api._fresh_show(series)
    expected = expected_count(media, ctx.get("anizip"))
    detail = (show or {}).get("availableEpisodesDetail") or {}
    episodes = _api._build_lists(int(anilist_id), series, _api._coerce_numbers(detail.get("sub")), _api._coerce_numbers(detail.get("dub")), ctx, expected, _api._coerce_numbers(detail.get("raw")))
    return {
        "meta": {
            "id": series.get("show_id"),
            "title": series.get("title"),
            "source": _api.NAME,
            "matchScore": round(float(series.get("score") or 0), 3),
            "numbering": series.get("mode") or "local",
            "episodeOffset": series.get("offset") or 0,
        },
        "episodes": episodes,
    }
