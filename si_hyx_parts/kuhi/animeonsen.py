# Native Kuhi/anime-api, MIT, Copyright (c) 2026 aryaniiil. See LICENSE.
import asyncio
import base64
import re
from urllib.parse import quote, unquote, urlparse

from si_hyx_parts.kuhi import _transport as httpx

from si_hyx_parts.kuhi import _cache

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
)
from si_hyx_parts.kuhi._match import (
    build_titles, dice_coeff, episode_meta, expected_count, norm,
)
from si_hyx_parts.kuhi._media import build_ctx

NAME = "animeonsen"
SITE = "https://www.animeonsen.xyz"

_QSAFE = "-_.!~*'()"

_animeonsen_session = None
_animeonsen_lock = None


def _session_lock() -> asyncio.Lock:
    global _animeonsen_lock
    if _animeonsen_lock is None:
        _animeonsen_lock = asyncio.Lock()
    return _animeonsen_lock


def _tag_attr(tag: str, name: str) -> str:
    m = re.search(name + r"=[\"']([^\"']*)[\"']", tag or "", re.IGNORECASE)
    return m.group(1) if m else ""


def _meta_content(html: str, name: str) -> str:
    for m in re.finditer(r"<meta\b[^>]*>", html or "", re.IGNORECASE):
        if _tag_attr(m.group(0), "name").lower() == name.lower():
            return _tag_attr(m.group(0), "content")
    return ""


def _session_cookie(set_cookie_values: list) -> str:
    for value in set_cookie_values:
        m = re.search(r"(?:^|;\s*)ao\.session=([^;]+)", str(value or ""))
        if m:
            return m.group(1)
    return ""


def _decode_token(cookie: str) -> str:
    raw = unquote(cookie or "")
    raw += "=" * (-len(raw) % 4)
    try:
        decoded = base64.b64decode(raw).decode("utf-8")
    except Exception:
        raise RuntimeError("AnimeOnsen returned an invalid session token")
    token = "".join(chr(ord(ch) + 1) for ch in decoded)
    if not token or not re.fullmatch(r"[\x20-\x7e]+", token):
        raise RuntimeError("AnimeOnsen returned an invalid session token")
    return token


def _origin(value: str) -> str:
    parts = urlparse(value or "")
    return f"{parts.scheme}://{parts.netloc}"


async def _create_session() -> dict:
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        res = await client.get(f"{SITE}/", headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
    if res.status_code != 200:
        raise RuntimeError(f"AnimeOnsen homepage HTTP {res.status_code}")
    html = res.text
    try:
        raw_cookies = res.headers.get_list("set-cookie")
    except Exception:
        raw_cookies = []
    cookie = _session_cookie(raw_cookies) or _session_cookie([res.cookies.get("ao.session") or ""])
    api_origin = _meta_content(html, "ao-api-origin")
    search_origin = _meta_content(html, "ao-search-origin")
    search_token = _meta_content(html, "ao-search-token")
    if not cookie or not api_origin or not search_origin or not search_token:
        raise RuntimeError("AnimeOnsen session bootstrap data missing")
    return {"token": _decode_token(cookie), "apiOrigin": _origin(api_origin),
            "searchOrigin": _origin(search_origin), "searchToken": search_token}


async def _get_session(force: bool = False) -> dict:
    global _animeonsen_session
    if force:
        _animeonsen_session = None
    if _animeonsen_session is not None:
        return _animeonsen_session
    async with _session_lock():
        if _animeonsen_session is None:
            _animeonsen_session = await _create_session()
        return _animeonsen_session


async def _api_json(path: str, retry: bool = True):
    current = await _get_session()
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        res = await client.get(f"{current['apiOrigin']}{path}", headers={
            "Authorization": f"Bearer {current['token']}",
            "Accept": "application/json, text/plain, */*",
            "Origin": SITE,
            "Referer": f"{SITE}/",
            "User-Agent": UA,
        })
    if res.status_code in (401, 403) and retry:
        await _get_session(True)
        return await _api_json(path, False)
    if res.status_code != 200:
        raise RuntimeError(f"AnimeOnsen {path} HTTP {res.status_code}")
    try:
        return res.json()
    except Exception:
        raise RuntimeError(f"AnimeOnsen {path} returned invalid JSON")


async def _search(query: str, retry: bool = True) -> list:
    current = await _get_session()
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        res = await client.post(f"{current['searchOrigin']}/multi-search",
                                headers={
                                    "Authorization": f"Bearer {current['searchToken']}",
                                    "Accept": "application/json",
                                    "Origin": SITE,
                                    "Referer": f"{SITE}/",
                                    "User-Agent": UA,
                                },
                                json={"queries": [{"indexUid": "content", "q": query,
                                                   "limit": 20}]})
    if res.status_code in (401, 403) and retry:
        await _get_session(True)
        return await _search(query, False)
    if res.status_code != 200:
        raise RuntimeError(f"AnimeOnsen search: {query} HTTP {res.status_code}")
    try:
        data = res.json()
    except Exception:
        raise RuntimeError(f"AnimeOnsen search: {query} returned invalid JSON")
    results = (data or {}).get("results") or []
    hits = (results[0] or {}).get("hits") if results else None
    return hits if isinstance(hits, list) else []


async def search(query: str) -> list:
    return await _search(query)


def _search_queries(titles: list) -> list:
    queries: set = set()
    for raw in (titles or [])[:10]:
        title = re.sub(r"\s+", " ", str(raw or "")).strip()
        if not title:
            continue
        queries.add(title)
        plain = re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", title, flags=re.UNICODE).replace("_", " ")).strip()
        if len(plain) >= 3:
            queries.add(plain)
        words = [w for w in plain.split(" ") if w]
        if len(words) > 4:
            queries.add(" ".join(words[:6]))
        if len(words) > 6:
            queries.add(" ".join(words[:4]))
        family = plain
        family = re.sub(r"\b(?:the\s+)?final\s+chapters?\b", " ", family, flags=re.IGNORECASE)
        family = re.sub(r"\b(?:season|part|cour|chapter)\s*(?:\d+|one|two|three|four|five|final)?\b", " ", family, flags=re.IGNORECASE)
        family = re.sub(r"\b(?:the\s+)?movie\b", " ", family, flags=re.IGNORECASE)
        family = re.sub(r"\s+", " ", family).strip()
        if len(family) >= 3:
            queries.add(family)
    return [q for q in queries if len(q) >= 3][:16]


def _title_score(titles: list, candidate: dict) -> float:
    values = [candidate.get("content_title_en"), candidate.get("content_title"),
              candidate.get("content_title_jp")]
    score = 0.0
    for title in titles or []:
        for value in values:
            if not value or not norm(title) or not norm(value):
                continue
            score = max(score, dice_coeff(title, value))
    return score


async def _inspect_candidate(candidate: dict):
    content_id = str((candidate or {}).get("content_id") or "")
    if not content_id:
        return None
    try:
        video = await _api_json(f"/v4/content/{quote(content_id, safe=_QSAFE)}/video/1")
    except Exception:
        return None
    metadata = (video or {}).get("metadata")
    if not metadata:
        return None
    try:
        mal_id = int(metadata.get("mal_id") or 0) or None
    except (TypeError, ValueError):
        mal_id = None
    try:
        episode_count = int(metadata.get("total_episodes") or 0)
    except (TypeError, ValueError):
        episode_count = 0
    return {"contentId": content_id,
            "title": candidate.get("content_title_en") or candidate.get("content_title") or "",
            "candidate": candidate, "malId": mal_id, "episodeCount": episode_count,
            "isMovie": bool(metadata.get("is_movie"))}


def _coverage_score(episode_count, expected) -> float:
    if not expected or expected < 2:
        return 1.0
    if not episode_count:
        return 0.5
    if episode_count == expected:
        return 1.0
    if expected < episode_count <= expected + 2:
        return 0.95
    return min(1.0, episode_count / expected)


def _validate_candidate(candidate: dict, media: dict, titles: list, expected):
    title = _title_score(titles, candidate["candidate"])
    if bool(candidate.get("isMovie")) != ((media or {}).get("format") == "MOVIE"):
        return None
    coverage = _coverage_score(candidate.get("episodeCount", 0), expected)
    if (expected or 0) >= 6:
        if (media or {}).get("status") == "FINISHED":
            minimum = -(-expected * 8 // 10)
        else:
            minimum = max(1, expected - 3)
        if candidate.get("episodeCount") and candidate["episodeCount"] < minimum:
            return None
    if title < 0.7:
        return None
    return {**candidate, "titleScore": title, "coverage": coverage,
            "score": title * 0.7 + coverage * 0.2 + 0.1}


async def resolve_series(anilist_id: int, ctx: dict | None = None) -> dict:
    ctx = ctx or await build_ctx(anilist_id)
    key = f"np:animeonsen:{anilist_id}"
    hit = _cache.cached(key, _cache.SHOW_IDENTITY_TTL)
    if hit is not None:
        return hit
    media = ctx["media"]
    primary_titles = [(media.get("title") or {}).get("english"),
                      (media.get("title") or {}).get("romaji"),
                      (media.get("title") or {}).get("native")]
    seen, titles = set(), []
    for t in [*(x for x in primary_titles if x), *build_titles(media, ctx.get("anizip"))]:
        if t not in seen:
            seen.add(t)
            titles.append(t)
    if not titles:
        raise RuntimeError(f"AnimeOnsen has no AniList titles for {anilist_id}")
    expected = expected_count(media, ctx.get("anizip"))
    discovered: dict = {}

    async def _one(query: str):
        try:
            return await _search(query)
        except Exception:
            return []

    for results in await asyncio.gather(*[_one(q) for q in _search_queries(titles)]):
        for cand in results:
            if isinstance(cand, dict) and cand.get("content_id") \
                    and cand["content_id"] not in discovered:
                discovered[cand["content_id"]] = cand
    shortlist = sorted(
        ({"candidate": c, "score": _title_score(titles, c)} for c in discovered.values()),
        key=lambda x: x["score"], reverse=True)
    shortlist = [x["candidate"] for x in shortlist if x["score"] >= 0.42][:14]
    inspected = [c for c in await asyncio.gather(*[_inspect_candidate(c) for c in shortlist]) if c]
    try:
        expected_mal_id = int((media or {}).get("idMal") or 0) or None
    except (TypeError, ValueError):
        expected_mal_id = None
    exact = [c for c in inspected if expected_mal_id and c.get("malId") == expected_mal_id] \
        if expected_mal_id else []
    pool = exact if exact else [c for c in inspected
                                if not expected_mal_id or not c.get("malId")]
    validated = sorted(
        [v for v in (_validate_candidate(c, media, titles, expected) for c in pool) if v],
        key=lambda x: x["score"], reverse=True)
    selected = validated[0] if validated else None
    runner_up = validated[1] if len(validated) > 1 else None
    if not selected or (not exact and (selected["score"] < 0.82
                                        or (runner_up and selected["score"] - runner_up["score"] < 0.08))):
        raise RuntimeError(f"AnimeOnsen match not confident for AniList {anilist_id}")
    data = {"contentId": selected["contentId"], "title": selected["title"],
            "malId": selected["malId"], "episodeCount": selected["episodeCount"],
            "isMovie": selected["isMovie"], "matchScore": selected["titleScore"],
            "score": selected["score"]}
    _cache.set(key, data, _cache.SHOW_IDENTITY_TTL)
    return data


async def _fetch_episodes(series: dict) -> list:
    data = await _api_json(f"/v4/content/{quote(str(series['contentId']), safe=_QSAFE)}/episodes")
    episodes = []
    for source_number, detail in (data or {}).items():
        try:
            number = int(source_number)
        except (TypeError, ValueError):
            continue
        if number < 1:
            continue
        episodes.append({
            "number": number,
            "sourceNumber": str(source_number),
            "title": ((detail or {}).get("contentTitle_episode_en")
                        or (detail or {}).get("contentTitle_episode_jp")),
        })
    episodes.sort(key=lambda e: e["number"])
    if episodes:
        return episodes
    if series.get("isMovie"):
        return [{"number": 1, "sourceNumber": "1", "title": None}]
    raise RuntimeError(f"AnimeOnsen has no episodes for {series['contentId']}")


def _episode_list(anilist_id: int, episodes: list, ctx: dict, expected) -> list:
    out = []
    for episode in episodes:
        if expected and episode["number"] > expected:
            continue
        meta = episode_meta(episode["number"], ctx)
        out.append({
            "id": f"watch/animeonsen/{anilist_id}/sub/animeonsen-{episode['number']}",
            "number": episode["number"],
            "sourceNumber": episode["sourceNumber"],
            "title": meta["title"] or episode.get("title") or f"Episode {episode['number']}",
            "duration": meta["duration"],
            "audio": "sub",
            "filler": meta["filler"],
            "uncensored": False,
            "description": meta["description"],
            "image": meta["image"],
            "airDate": meta["airDate"],
        })
    return out


async def get_episodes(anilist_id: int, ctx: dict | None = None) -> dict:
    ctx = ctx or await build_ctx(anilist_id)
    media = ctx["media"]
    series = await resolve_series(anilist_id, ctx)
    expected = expected_count(media, ctx.get("anizip"))
    return {
        "meta": {
            "id": series["contentId"],
            "title": series["title"],
            "source": NAME,
            "matchScore": round(series["matchScore"], 3),
            "numbering": "standard",
            "episodeOffset": 0,
        },
        "episodes": {
            "sub": _episode_list(anilist_id, await _fetch_episodes(series), ctx, expected),
            "dub": [],
        },
    }


def _skip_range(start, end):
    try:
        start_f, end_f = float(start), float(end)
    except (TypeError, ValueError):
        return None
    if not end_f > start_f:
        return None
    return {"start": int(start_f) if start_f.is_integer() else start_f,
            "end": int(end_f) if end_f.is_integer() else end_f}


def _video_subtitles(video: dict, headers: dict) -> list:
    labels = ((video or {}).get("metadata") or {}).get("subtitles") or {}
    out = []
    for language, url in (((video or {}).get("uri") or {}).get("subtitles") or {}).items():
        out.append({"url": url, "label": labels.get(language) or language,
                    "srclang": language, "default": language == "en-US",
                    "headers": dict(headers)})
    return out


async def watch(anilist_id: int, audio: str, ep: int, ctx: dict | None = None) -> list:
    if audio == "dub":
        raise RuntimeError("AnimeOnsen only provides subtitled streams")
    if audio not in ("sub", "all"):
        raise RuntimeError(f"AnimeOnsen unknown audio '{audio}'")
    ctx = ctx or await build_ctx(anilist_id)
    media = ctx["media"]
    series = await resolve_series(anilist_id, {**ctx, "media": media})
    expected = expected_count(media, ctx.get("anizip"))
    episode = next((e for e in await _fetch_episodes(series)
                    if e["number"] == int(ep) and (not expected or e["number"] <= expected)), None)
    if not episode:
        raise RuntimeError(f"AnimeOnsen episode {ep} not found")
    video = await _api_json(f"/v4/content/{quote(str(series['contentId']), safe=_QSAFE)}"
                            f"/video/{quote(str(episode['sourceNumber']), safe=_QSAFE)}")
    stream = ((video or {}).get("uri") or {}).get("stream")
    if not stream:
        raise RuntimeError(f"AnimeOnsen has no stream for episode {ep}")
    current = await _get_session()
    headers = {"Authorization": f"Bearer {current['token']}"}
    skip = None
    candidates = ((video or {}).get("metadata") or {}).get("episode")
    if isinstance(candidates, list):
        skip = next((item for item in candidates
                     if isinstance(item, dict) and any(k in item for k in
                         ("skipIntro_s", "skipIntro_e", "skipOutro_s", "skipOutro_e"))), None)
    return [{"url": stream, "type": "dash", "server": "AnimeOnsen", "audio": "sub",
             "referer": f"{SITE}/", "headers": dict(headers),
             "subtitles": _video_subtitles(video, headers),
             "intro": _skip_range((skip or {}).get("skipIntro_s"), (skip or {}).get("skipIntro_e")),
             "outro": _skip_range((skip or {}).get("skipOutro_s"), (skip or {}).get("skipOutro_e")),
             "priority": 5, "isActive": True}]
