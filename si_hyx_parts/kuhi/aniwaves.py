# Native Kuhi/anime-api, MIT, Copyright (c) 2026 aryaniiil. See LICENSE.
import asyncio
import json
import re
from urllib.parse import quote, urljoin, urlparse

from si_hyx_parts.kuhi import _transport as httpx

from si_hyx_parts.kuhi import _cache
from si_hyx_parts.kuhi._http import UA, fetch_json, fetch_text
from si_hyx_parts.kuhi._match import (
    attr, build_titles, decode_entities, dice_coeff, episode_meta,
    expected_count, strip_tags,
)
from si_hyx_parts.kuhi._media import build_ctx

NAME = "aniwaves"
BASE = "https://aniwaves.ru"

_QSAFE = "-_.!~*'()"


def _format_name(value) -> str:
    name = str(value or "").upper()
    if "SPECIAL" in name:
        return "special"
    if name in ("TV", "TV_SHORT"):
        return "tv"
    if name == "MOVIE":
        return "movie"
    if name == "OVA":
        return "ova"
    if name == "ONA":
        return "ona"
    if name == "SPECIAL":
        return "special"
    return ""


def _search_queries(titles: list) -> list:
    queries: set = set()
    for raw in (titles or [])[:8]:
        title = re.sub(r"\s+", " ", str(raw or "")).strip()
        if not title:
            continue
        queries.add(title)
        plain = re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", title, flags=re.UNICODE).replace("_", " ")).strip()
        if len(plain) >= 3:
            queries.add(plain)
        words = [w for w in plain.split(" ") if w]
        if len(words) > 4:
            queries.add(" ".join(words[:4]))
        if len(words) > 6:
            queries.add(" ".join(words[:6]))
        family = plain
        family = re.sub(r"\b(?:the\s+)?final\s+chapters?\b", " ", family, flags=re.IGNORECASE)
        family = re.sub(r"\bfinal\s+(?:arc|edition)\b", " ", family, flags=re.IGNORECASE)
        family = re.sub(r"\b(?:kanketsu|kouhen|zenpen)\s*(?:hen)?\b", " ", family, flags=re.IGNORECASE)
        family = re.sub(r"\b(?:the\s+)?movie\b", " ", family, flags=re.IGNORECASE)
        family = re.sub(r"\b(?:season|part|cour|chapter)\s*(?:\d+|one|two|three|four|final)?\b", " ", family, flags=re.IGNORECASE)
        family = re.sub(r"\b(?:final|special)\s*(?:\d+|one|two|three|four)?\b", " ", family, flags=re.IGNORECASE)
        family = re.sub(r"\s+", " ", family).strip()
        if len(family) >= 3:
            queries.add(family)
    return [q for q in queries if len(q) >= 3][:18]


async def _ajax(path: str, referer: str):
    raw = await fetch_text(f"{BASE}{path}", {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": referer,
    })
    try:
        data = json.loads(raw)
    except Exception:
        raise RuntimeError(f"AniWaves returned invalid JSON: {path}")
    try:
        status = int((data or {}).get("status") or 0)
    except (TypeError, ValueError):
        status = 0
    if not isinstance(data, dict) or status != 200:
        msg = (data or {}).get("message") if isinstance(data, dict) else None
        raise RuntimeError(msg or f"AniWaves request failed: {path}")
    return data.get("result")


def _parse_search_cards(html: str) -> list:
    found: dict = {}
    for m in re.finditer(r"<a\b([^>]*)>([\s\S]*?)</a>", html or "", re.IGNORECASE):
        tag, inner = m.group(1), m.group(2)
        cls = attr(tag, "class")
        if not re.search(r"\bname\b", cls) or not re.search(r"\bd-title\b", cls):
            continue
        href = attr(tag, "href")
        sm = re.match(r"^/watch/([a-z0-9-]+)$", href or "", re.IGNORECASE)
        if not sm:
            continue
        slug = sm.group(1)
        if slug in found:
            continue
        tm = re.search(r"-(\d+)$", slug)
        try:
            site_id = int(tm.group(1)) if tm else 0
        except ValueError:
            site_id = 0
        if not site_id:
            continue
        title = strip_tags(inner)
        if not title:
            continue
        found[slug] = {"slug": slug, "siteId": site_id, "title": title,
                       "japanese": attr(tag, "data-jp")}
    return list(found.values())


async def search(query: str) -> list:
    html = await fetch_text(f"{BASE}/filter?keyword={quote(query, safe=_QSAFE)}", {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": f"{BASE}/",
    })
    return _parse_search_cards(html)


def _detail_field(html: str, label: str) -> str:
    m = re.search(r"<div>\s*" + re.escape(label) + r":\s*<span[^>]*>([\s\S]*?)</span>",
                  html or "", re.IGNORECASE)
    return strip_tags(m.group(1)) if m else ""


def _parse_episode_count(value) -> dict:
    numbers = [int(x) for x in re.findall(r"\d+", str(value or ""))]
    return {"available": numbers[0] if numbers else 0,
            "total": numbers[1] if len(numbers) > 1 else (numbers[0] if numbers else 0)}


async def _fetch_detail(candidate: dict) -> dict:
    html = await fetch_text(f"{BASE}/watch/{candidate['slug']}", {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": f"{BASE}/",
    })
    premiered = _detail_field(html, "Premiered")
    aired = _detail_field(html, "Date aired")
    ym = re.search(r"\d{4}", aired) or re.search(r"\d{4}", premiered)
    year = int(ym.group(0)) if ym else None
    title = candidate.get("title") or ""
    if not title:
        hm = re.search(r"<h1[^>]*>([\s\S]*?)</h1>", html, re.IGNORECASE)
        title = strip_tags(hm.group(1)) if hm else ""
    return {**candidate, "title": title, "type": _format_name(_detail_field(html, "Type")),
            "year": year, "episodes": _parse_episode_count(_detail_field(html, "Episodes"))}


def _candidate_title_score(titles: list, candidate: dict) -> float:
    values = [candidate.get("title"), candidate.get("japanese"),
              (candidate.get("slug") or "").replace("-", " ")]
    best = 0.0
    for title in titles or []:
        for value in values:
            if value:
                best = max(best, dice_coeff(title, value))
    return best


def _coverage_score(candidate: dict, expected, status) -> float:
    if not expected or expected < 1:
        return 0.5
    if (candidate.get("episodes") or {}).get("available", 0) < 1:
        return 0.0
    if expected < 6:
        return 1.0
    needed = -(-expected * 8 // 10) if status == "FINISHED" else max(1, expected - 3)
    return min(1.0, (candidate.get("episodes") or {}).get("available", 0) / needed)


def _validate_candidate(candidate: dict, media: dict, titles: list, expected):
    title_score = _candidate_title_score(titles, candidate)
    expected_type = _format_name((media or {}).get("format"))
    expected_year = int(((media or {}).get("startDate") or {}).get("year")
                          or (media or {}).get("seasonYear") or 0) or None
    if title_score < 0.68:
        return None
    if expected_type and candidate.get("type") and expected_type != candidate.get("type"):
        return None
    if expected_year and candidate.get("year") and expected_year != candidate.get("year"):
        return None
    coverage = _coverage_score(candidate, expected, (media or {}).get("status"))
    if (expected or 0) >= 6 and coverage < 0.8:
        return None
    score = (title_score * 0.72 + (0.14 if expected_type and candidate.get("type") == expected_type else 0.07)
             + (0.10 if expected_year and candidate.get("year") == expected_year else 0.04)
             + coverage * 0.04)
    return {**candidate, "titleScore": title_score, "coverage": coverage, "score": score}


async def resolve_series(anilist_id: int, ctx: dict | None = None) -> dict:
    ctx = ctx or await build_ctx(anilist_id)
    key = f"np:aniwaves:{anilist_id}"
    hit = _cache.cached(key, _cache.SHOW_IDENTITY_TTL)
    if hit is not None:
        return hit
    media = ctx["media"]
    titles = build_titles(media, ctx.get("anizip"))
    expected = expected_count(media, ctx.get("anizip"))
    discovered: dict = {}

    async def _one(query: str):
        try:
            return await search(query)
        except Exception:
            return []

    for results in await asyncio.gather(*[_one(q) for q in _search_queries(titles)]):
        for cand in results:
            if cand["slug"] not in discovered:
                discovered[cand["slug"]] = cand
    shortlist = sorted(
        ({"candidate": c, "score": _candidate_title_score(titles, c)} for c in discovered.values()),
        key=lambda x: x["score"], reverse=True)
    shortlist = [x for x in shortlist if x["score"] >= 0.5][:12]

    async def _detail(item):
        try:
            return await _fetch_detail(item["candidate"])
        except Exception:
            return None

    details = [d for d in await asyncio.gather(*[_detail(x) for x in shortlist]) if d]
    valid = sorted(
        [v for v in (_validate_candidate(d, media, titles, expected) for d in details) if v],
        key=lambda x: x["score"], reverse=True)
    selected = valid[0] if valid else None
    runner_up = valid[1] if len(valid) > 1 else None
    if (not selected or selected["score"] < 0.82
            or (runner_up and selected["score"] - runner_up["score"] < 0.08)):
        raise RuntimeError(f"AniWaves match not confident for AniList {anilist_id}")
    data = {"siteId": selected["siteId"], "slug": selected["slug"],
            "title": selected["title"], "score": selected["score"],
            "matchScore": selected["titleScore"],
            "episodeCount": (selected.get("episodes") or {}).get("available", 0)}
    _cache.set(key, data, _cache.SHOW_IDENTITY_TTL)
    return data


def _parse_episodes(html: str) -> list:
    episodes, seen = [], set()
    for m in re.finditer(r"<a\b([^>]*)>([\s\S]*?)</a>", html or "", re.IGNORECASE):
        attrs, inner = m.group(1), m.group(2)
        try:
            number = int(attr(attrs, "data-num") or "0")
        except ValueError:
            continue
        source_number = attr(attrs, "data-slug") or str(number)
        if number < 1 or number in seen:
            continue
        if not attr(attrs, "data-ids"):
            continue
        seen.add(number)
        try:
            duration = int(attr(attrs, "data-duration") or "0") or None
        except ValueError:
            duration = None
        episodes.append({
            "number": number,
            "sourceNumber": source_number,
            "ids": attr(attrs, "data-ids"),
            "title": re.sub(r"^\d+\s*", "", strip_tags(inner)) or f"Episode {number}",
            "airDate": attr(attrs, "data-aired") or None,
            "duration": duration,
            "filler": attr(attrs, "data-filler") == "1",
            "recap": attr(attrs, "data-recap") == "1",
            "hasSub": attr(attrs, "data-sub") == "1",
            "hasDub": attr(attrs, "data-dub") == "1",
        })
    return sorted(episodes, key=lambda e: e["number"])


async def _fetch_episodes(series: dict) -> list:
    result = await _ajax(f"/ajax/episode/list/{series['siteId']}?vrf=",
                         f"{BASE}/watch/{series['slug']}")
    episodes = _parse_episodes(str(result or ""))
    if not episodes:
        raise RuntimeError(f"AniWaves has no episodes for {series['slug']}")
    return episodes

_ORDINAL_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                  "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def _ordinal(value) -> int:
    m = re.search(r"\b(?:part|special|chapter)\s*(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b",
                  str(value or ""), re.IGNORECASE)
    if not m:
        return 0
    word = m.group(1).lower()
    try:
        return int(word)
    except ValueError:
        return _ORDINAL_WORDS.get(word, 0)


def _align_episodes(source_episodes: list, media: dict, expected) -> list:
    if not expected or len(source_episodes) <= expected:
        return source_episodes
    target_titles = [(media.get("title") or {}).get("english"),
                     (media.get("title") or {}).get("romaji"),
                     (media.get("title") or {}).get("native")]
    target_ordinal = max([0] + [_ordinal(t) for t in target_titles if t])
    if target_ordinal < 2:
        return source_episodes
    start = next((i for i, e in enumerate(source_episodes)
                  if _ordinal(e.get("title")) == target_ordinal), -1)
    if start < 0 or len(source_episodes) - start < expected:
        return source_episodes
    return [{**e, "number": i + 1} for i, e in
            enumerate(source_episodes[start:start + expected])]


def _build_lists(anilist_id: int, source_episodes: list, ctx: dict, expected) -> dict:
    sub, dub = [], []
    for src in source_episodes:
        if expected and src["number"] > expected:
            continue
        meta = episode_meta(src["number"], ctx)
        base = {
            "number": src["number"],
            "title": meta["title"] or src.get("title") or f"Episode {src['number']}",
            "duration": meta["duration"] if meta["duration"] is not None else src.get("duration"),
            "filler": meta["filler"] if meta["filler"] is not None else src.get("filler", False),
            "uncensored": meta["uncensored"],
            "description": meta["description"],
            "image": meta["image"],
            "airDate": meta["airDate"] if meta["airDate"] is not None else src.get("airDate"),
            "sourceNumber": src["sourceNumber"],
        }
        if src.get("hasSub"):
            sub.append({"id": f"watch/aniwaves/{anilist_id}/sub/aniwaves-{src['number']}",
                        **base, "audio": "sub"})
        if src.get("hasDub"):
            dub.append({"id": f"watch/aniwaves/{anilist_id}/dub/aniwaves-{src['number']}",
                        **base, "audio": "dub"})
    return {"sub": sub, "dub": dub}


async def get_episodes(anilist_id: int, ctx: dict | None = None) -> dict:
    ctx = ctx or await build_ctx(anilist_id)
    media = ctx["media"]
    series = await resolve_series(anilist_id, ctx)
    expected = expected_count(media, ctx.get("anizip"))
    episodes = _align_episodes(await _fetch_episodes(series), media, expected)
    return {
        "meta": {
            "id": series["slug"],
            "title": series["title"],
            "source": NAME,
            "matchScore": round(series["matchScore"], 3),
            "numbering": "standard",
            "episodeOffset": 0,
        },
        "episodes": _build_lists(anilist_id, episodes, ctx, expected),
    }


from .aniwaves_watch import _parse_server_groups


from .aniwaves_watch import _fetch_servers


from .aniwaves_watch import _fetch_source


from .aniwaves_watch import _aniwaves_can_vidplay


from .aniwaves_watch import _aniwaves_extract_vidplay


from .aniwaves_watch import _aniwaves_can_datasv


from .aniwaves_watch import _aniwaves_extract_datasv


from .aniwaves_watch import _aniwaves_can_megaplay


from .aniwaves_watch import _aniwaves_extract_megaplay


from .aniwaves_watch import _aniwaves_can_byse

_ANIWAVES_EXTRACTORS = [
    ("vidplay", _aniwaves_can_vidplay, _aniwaves_extract_vidplay),
    ("datasv", _aniwaves_can_datasv, _aniwaves_extract_datasv),
    ("megaplay", _aniwaves_can_megaplay, _aniwaves_extract_megaplay),
]


from .aniwaves_watch import _resolve_source


from .aniwaves_watch import _skip_range


from .aniwaves_watch import watch
