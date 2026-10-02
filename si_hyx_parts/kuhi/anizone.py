# Native Kuhi/anime-api, MIT, Copyright (c) 2026 aryaniiil. See LICENSE.
import asyncio
import json
import math
import re
from urllib.parse import quote

from si_hyx_parts.kuhi import _transport as httpx

from si_hyx_parts.kuhi import _cache
from si_hyx_parts.kuhi._http import UA, fetch_text
from si_hyx_parts.kuhi._match import (
    build_titles, decode_entities, dice_coeff, episode_meta,
    expected_count, get_prequel_offset,
)
from si_hyx_parts.kuhi._media import build_ctx

NAME = "anizone"
BASE = "https://anizone.to"


def _normalize_url(value) -> str:
    return re.sub(r"\\+/", "/", str(value or ""))


def _decode_json_argument(raw):
    if not raw:
        return None
    marker = "\x01U\x01"
    value = re.sub(r"\\\\u([0-9a-fA-F]{4})", lambda m: marker + m.group(1), str(raw))
    value = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), value)
    value = value.replace(marker, "\\u")
    try:
        return json.loads(value)
    except Exception:
        return None


def _json_argument(html, name):
    pat = re.compile(
        re.escape(name) + r"\s*:\s*JSON\.parse\('((?:[^'\\]|\\.)*)'\)",
        re.IGNORECASE | re.DOTALL,
    )
    m = pat.search(str(html))
    return _decode_json_argument(m.group(1) if m else None)


def _player_data(html):
    m = re.search(
        r"vidstackPlayer\s*\(\s*JSON\.parse\('((?:[^'\\]|\\.)*)'\)\s*\)",
        str(html), re.IGNORECASE | re.DOTALL,
    )
    return _decode_json_argument(m.group(1) if m else None)


def _num(value) -> float:
    try:
        return float(str(value).strip())
    except (ValueError, TypeError, AttributeError):
        return float("nan")


def _response_cookies(res) -> list:
    try:
        values = list(res.headers.get_list("set-cookie"))
    except Exception:
        single = res.headers.get("set-cookie")
        values = [single] if single else []
    return [v for v in values if v]


def _merge_cookies(jar: dict, values) -> dict:
    for value in values or []:
        m = re.match(r"^\s*([^=;\s]+)=([^;]*)", str(value))
        if m:
            jar[m.group(1)] = m.group(2)
    return jar


def _cookie_header(jar: dict) -> str:
    return "; ".join(f"{k}={v}" for k, v in jar.items())


async def _request(url, *, method="GET", headers=None, json_body=None, cookies=None,
                   timeout=20.0) -> dict:
    h = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    if headers:
        h.update(headers)
    if cookies:
        h["Cookie"] = _cookie_header(cookies)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        if method == "POST":
            res = await client.post(url, headers=h, json=json_body)
        else:
            res = await client.get(url, headers=h)
    text = res.text
    if res.status_code != 200:
        raise RuntimeError(f"AniZone HTTP {res.status_code}: {url}")
    return {"text": text, "cookies": _response_cookies(res)}


async def _fetch_page(path) -> dict:
    return await _request(f"{BASE}{path}", headers={
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": f"{BASE}/",
    })


def _pick_title(titles) -> str:
    if isinstance(titles, list):
        for value in titles:
            if value:
                return value
        return ""
    if not isinstance(titles, dict) or not titles:
        return ""
    for key in ("1", "5", "8", 1, 5, 8):
        if titles.get(key):
            return titles[key]
    for value in titles.values():
        if value:
            return value
    return ""


def _title_values(item) -> list:
    item = item or {}
    tl = item.get("title_list") or {}
    tl_vals = tl.values() if isinstance(tl, dict) else (tl if isinstance(tl, list) else [])
    raw = [item.get("main_title"), *tl_vals]
    out = []
    for value in raw:
        if value and value not in out:
            out.append(value)
    return out


def _format_name(value) -> str:
    t = str(value or "").lower()
    if "special" in t:
        return "special"
    if "movie" in t:
        return "movie"
    if "ova" in t:
        return "ova"
    if "web" in t or "ona" in t:
        return "ona"
    if "tv" in t:
        return "tv"
    return ""


def _expected_format(value) -> str:
    return {
        "TV": "tv", "TV_SHORT": "tv", "MOVIE": "movie",
        "OVA": "ova", "ONA": "ona", "SPECIAL": "special",
    }.get(str(value or "").upper(), "")

_FAMILY_PATTERNS = [
    r"\b(?:the\s+)?final\s+chapters?\b",
    r"\bfinal\s+(?:arc|edition)\b",
    r"\b(?:kanketsu|kouhen|zenpen)\s*(?:hen)?\b",
    r"\b(?:the\s+)?movie\b",
    r"\b(?:season|part|cour|chapter)\s*(?:\d+|one|two|three|four|final)?\b",
    r"\b(?:final|special)\s*(?:\d+|one|two|three|four)?\b",
]


def _search_queries(titles) -> list:
    queries = []

    def _add(value):
        value = str(value or "")
        if len(value) >= 3 and value not in queries:
            queries.append(value)

    for raw in (titles or [])[:8]:
        title = re.sub(r"\s+", " ", str(raw or "")).strip()
        if not title:
            continue
        _add(title)
        plain = re.sub(r"\s+", " ", re.sub(r"[\W_]+", " ", title)).strip()
        if len(plain) >= 3:
            _add(plain)
        words = plain.split()
        if len(words) > 4:
            _add(" ".join(words[:4]))
        family = plain
        for pat in _FAMILY_PATTERNS:
            family = re.sub(pat, " ", family, flags=re.IGNORECASE)
        family = re.sub(r"\s+", " ", family).strip()
        if len(family) >= 3:
            _add(family)
    return [q for q in queries if len(q) >= 3][:8]


def _parse_search_items(html) -> list:
    items = _json_argument(html, "items")
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug") or "")
        if not re.match(r"^[a-z0-9-]+$", slug, re.IGNORECASE):
            continue
        title = _pick_title(item.get("title_list")) or item.get("main_title") or ""
        if not title:
            continue
        ep_raw = _num(item.get("episode_count"))
        year_raw = _num(item.get("start_year"))
        out.append({
            "slug": slug,
            "title": title,
            "titles": _title_values(item),
            "type": _format_name(item.get("type")),
            "year": int(year_raw) if math.isfinite(year_raw) and year_raw != 0 else None,
            "episodeCount": int(ep_raw) if math.isfinite(ep_raw) and ep_raw > 0 else 0,
        })
    return out


async def search(query: str) -> list:
    html = await fetch_text(f"{BASE}/anime?search={quote(query)}", {"Referer": f"{BASE}/"})
    return _parse_search_items(html)


def _candidate_title_score(titles, candidate) -> float:
    best = 0.0
    for title in titles or []:
        for value in candidate.get("titles") or []:
            best = max(best, dice_coeff(title, value))
    return best


def _coverage_score(candidate, expected, status) -> float:
    if not expected or expected < 1:
        return 0.5
    if (candidate.get("episodeCount") or 0) < 1:
        return 0.0
    if expected < 6:
        return 1.0
    needed = math.ceil(expected * 0.8) if status == "FINISHED" else max(1, expected - 3)
    return min(1.0, (candidate.get("episodeCount") or 0) / needed)


def _validate_candidate(candidate, media, titles, expected):
    title_score = _candidate_title_score(titles, candidate)
    media = media or {}
    fmt = _expected_format(media.get("format"))
    year_raw = _num(((media.get("startDate") or {}).get("year")) or media.get("seasonYear") or 0)
    year = int(year_raw) if math.isfinite(year_raw) and year_raw != 0 else None
    if title_score < 0.68:
        return None
    if fmt and candidate.get("type") and fmt != candidate.get("type"):
        return None
    if year and candidate.get("year") and year != candidate.get("year"):
        return None
    coverage = _coverage_score(candidate, expected, media.get("status"))
    if expected and expected >= 6 and coverage < 0.8:
        return None
    score = (title_score * 0.72
             + (0.14 if fmt and candidate.get("type") == fmt else 0.07)
             + (0.10 if year and candidate.get("year") == year else 0.04)
             + coverage * 0.04)
    return {**candidate, "titleScore": title_score, "coverage": coverage, "score": score}


async def resolve_series(anilist_id: int, ctx: dict | None = None) -> dict:
    ctx = ctx or await build_ctx(anilist_id)
    key = f"np:anizone:{anilist_id}"
    hit = _cache.cached(key, _cache.SHOW_IDENTITY_TTL)
    if hit is not None:
        return hit
    media = ctx["media"]
    titles = build_titles(media, ctx.get("anizip"))
    expected = expected_count(media, ctx.get("anizip"))

    async def _one(query):
        try:
            return await search(query)
        except Exception:
            return []

    discovered = {}
    for results in await asyncio.gather(*[_one(q) for q in _search_queries(titles)]):
        for candidate in results or []:
            if candidate.get("slug") not in discovered:
                discovered[candidate["slug"]] = candidate
    valid = [v for v in
             (_validate_candidate(c, media, titles, expected) for c in discovered.values()) if v]
    valid.sort(key=lambda c: c["score"], reverse=True)
    selected = valid[0] if valid else None
    runner_up = valid[1] if len(valid) > 1 else None
    if (not selected or selected["score"] < 0.82
            or (runner_up and selected["score"] - runner_up["score"] < 0.08)):
        raise RuntimeError(f"AniZone match not confident for AniList {anilist_id}")
    data = {"slug": selected["slug"], "title": selected["title"],
            "matchScore": selected["titleScore"], "score": selected["score"]}
    _cache.set(key, data, _cache.SHOW_IDENTITY_TTL)
    return data


def _snapshot(html) -> str:
    for m in re.finditer(r'wire:snapshot="([^"]*)"', str(html), re.IGNORECASE):
        if "pages.anime-detail" in (m.group(1) or ""):
            return decode_entities(m.group(1))
    return ""


def _cursor(html):
    m = re.search(r"nextCursor:\s*'([^']+)'", str(html), re.IGNORECASE)
    return m.group(1) if m else None


def _has_more(html) -> bool:
    return bool(re.search(r"hasMore:\s*true", str(html), re.IGNORECASE))


def _csrf(html) -> str:
    m = re.search(r'csrf-token"\s+content="([^"]+)"', str(html), re.IGNORECASE)
    return m.group(1) if m else ""


def _seconds(value):
    m = re.match(r"^(\d+):(\d{1,2})$", str(value or ""))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _episode_number(item):
    item = item or {}
    direct = _num(item.get("slug"))
    if math.isfinite(direct) and direct > 0:
        return int(direct)
    m = re.search(r"/(\d+)/?$", _normalize_url(item.get("url")))
    if m:
        number = int(m.group(1))
        return number if number > 0 else None
    return None


def _parse_episodes(items) -> list:
    seen = set()
    out = []
    for item in items or []:
        item = item or {}
        number = _episode_number(item)
        if not number or number in seen:
            continue
        seen.add(number)
        out.append({
            "number": number,
            "sourceNumber": number,
            "title": _pick_title(item.get("title_list")) or f"Episode {number}",
            "duration": _seconds(item.get("duration")),
            "description": item.get("summary") or None,
            "image": _normalize_url(item.get("snapshot")) or None,
            "airDate": item.get("air_date") or None,
            "hasSub": _num(item.get("videos_count")) > 0,
            "hasDub": False,
        })
    out.sort(key=lambda e: e["number"])
    return out


def _initial_page(html, cookies) -> dict:
    items = _json_argument(html, "items")
    data = {
        "items": items if isinstance(items, list) else [],
        "snapshot": _snapshot(html),
        "cursor": _cursor(html),
        "hasMore": _has_more(html),
        "csrf": _csrf(html),
        "cookies": _merge_cookies({}, cookies),
    }
    if not data["items"] or not data["snapshot"] or not data["csrf"]:
        raise RuntimeError("AniZone page payload not found")
    return data


async def _load_page(state, slug) -> dict:
    res = await _request(
        f"{BASE}/livewire/update",
        method="POST",
        headers={
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "X-Livewire": "",
            "X-CSRF-TOKEN": state["csrf"],
            "X-Requested-With": "XMLHttpRequest",
            "Origin": BASE,
            "Referer": f"{BASE}/anime/{slug}",
        },
        json_body={"components": [{
            "snapshot": state["snapshot"],
            "updates": {},
            "calls": [{"path": "", "method": "loadPage", "params": [state["cursor"]]}],
        }]},
        cookies=state["cookies"],
    )
    try:
        payload = json.loads(res["text"])
    except Exception:
        raise RuntimeError("AniZone returned invalid Livewire JSON")
    components = (payload or {}).get("components") or []
    component = components[0] if components and isinstance(components[0], dict) else {}
    dispatches = ((component.get("effects") or {}).get("dispatches")) or []
    dispatch = next((d for d in dispatches
                     if isinstance(d, dict) and d.get("name") == "items-loaded"), None)
    params = (dispatch or {}).get("params")
    if (not component.get("snapshot") or not isinstance(params, dict)
            or not isinstance(params.get("items"), list)):
        raise RuntimeError("AniZone page continuation payload not found")
    return {
        "items": params["items"],
        "snapshot": component["snapshot"],
        "cursor": params.get("nextCursor") or None,
        "hasMore": bool(params.get("hasMore")),
        "csrf": state["csrf"],
        "cookies": _merge_cookies(dict(state["cookies"]), res["cookies"]),
    }


async def scrape_series(slug: str, limit=None, max_pages=None) -> list:
    initial = await _fetch_page(f"/anime/{slug}")
    state = _initial_page(initial["text"], initial["cookies"])
    items = list(state["items"])
    pages = 1
    lim = limit if limit else float("inf")
    mp = max_pages if max_pages else float("inf")
    while state["hasMore"] and state["cursor"] and len(items) < lim and pages < mp:
        state = await _load_page(state, slug)
        items.extend(state["items"])
        pages += 1
    episodes = _parse_episodes(items)
    if not episodes:
        raise RuntimeError(f"AniZone has no episodes for {slug}")
    return episodes


def _choose_mode(episodes, expected, offset) -> str:
    if not expected or not offset:
        return "local"
    local = len([e for e in episodes if 1 <= e["number"] <= expected])
    shifted = len([e for e in episodes if offset < e["number"] <= offset + expected])
    return "offset" if shifted > local else "local"

_WORD_NUMS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
              "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


from .anizone_watch import _ordinal


from .anizone_watch import _align_episodes


from .anizone_watch import _build_lists


from .anizone_watch import _series_episodes


from .anizone_watch import get_episodes


from .anizone_watch import scrape_watch


from .anizone_watch import watch
