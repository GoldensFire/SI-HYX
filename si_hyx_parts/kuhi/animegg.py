# Native Kuhi/anime-api, MIT, Copyright (c) 2026 aryaniiil. See LICENSE.
import asyncio
import base64
import json as _json
import re
from urllib.parse import quote, unquote, urlparse

from si_hyx_parts.kuhi import _cache
from si_hyx_parts.kuhi._http import fetch_text
from si_hyx_parts.kuhi._match import (
    attr, build_titles, decode_entities, episode_meta, expected_count,
    find_top_slugs, get_prequel_offset, select_series, strip_tags,
)
from si_hyx_parts.kuhi._media import build_ctx

NAME = "animegg"
BASE = "https://www.animegg.org"


async def search(query: str) -> list:
    html = await fetch_text(f"{BASE}/search/?q={quote(query)}")
    results = []
    for m in re.finditer(
            r"<a\b[^>]*class=[\"'][^\"']*\bmse\b[^\"']*[\"'][^>]*>[\s\S]*?</a>",
            html, re.IGNORECASE):
        tag = re.search(r"<a\b[^>]*>", m.group(0), re.IGNORECASE)
        href = attr(tag.group(0) if tag else "", "href")
        sm = re.search(r"^/series/([^/?#]+)", href)
        if not sm:
            continue
        strong = re.search(r"<strong[^>]*>([\s\S]*?)</strong>", m.group(0), re.IGNORECASE)
        text = strip_tags(strong.group(1)) if strong else sm.group(1).replace("-", " ")
        results.append({"slug": sm.group(1), "text": text})
    return results


async def scrape_series(slug: str) -> list:
    html = await fetch_text(f"{BASE}/series/{slug}")
    episodes = []
    for m in re.finditer(r"<li\b[^>]*>([\s\S]*?)</li>", html, re.IGNORECASE):
        block = m.group(1)
        if not re.search(r"\banm_det_pop\b", block):
            continue
        link = re.search(
            r"<a\b[^>]*class=[\"'][^\"']*anm_det_pop[^\"']*[\"'][^>]*>",
            block, re.IGNORECASE)
        href = attr(link.group(0) if link else "", "href")
        href = re.sub(r"^/", "", re.sub(r"#.*$", "", href))
        strong = re.search(r"<strong[^>]*>([\s\S]*?)</strong>", block, re.IGNORECASE)
        strong_text = strip_tags(strong.group(1)) if strong else ""
        range_m = re.search(r"(\d+)-(\d+)\s*$", strong_text)
        num_m = range_m or re.search(r"(\d+)\s*$", strong_text)
        if not num_m or not href:
            continue
        number = int(num_m.group(1))
        title_m = re.search(
            r"<i\b[^>]*class=[\"'][^\"']*anititle[^\"']*[\"'][^>]*>([\s\S]*?)</i>",
            block, re.IGNORECASE)
        title = strip_tags(title_m.group(1)) if title_m else ""
        audio = []
        if re.search(r"\bbtn-subbed\b", block):
            audio.append("sub")
        if re.search(r"\bbtn-dubbed\b", block):
            audio.append("dub")
        episodes.append({
            "number": number,
            "title": title or strong_text,
            "epSlug": href,
            "hasSub": "sub" in audio,
            "hasDub": "dub" in audio,
        })
    episodes.sort(key=lambda e: e["number"])
    seen, out = set(), []
    for e in episodes:
        if e["number"] not in seen:
            seen.add(e["number"])
            out.append(e)
    return out


async def scrape_embed(embed_id: str) -> list:
    html = await fetch_text(f"{BASE}/embed/{embed_id}", {"Referer": BASE})
    m = re.search(r"var\s+videoSources\s*=\s*(\[[\s\S]*?\]);", html)
    if not m:
        return []
    try:
        as_json = re.sub(r"([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:",
                         r'\1"\2":', m.group(1))
        as_json = re.sub(r":\s*'([^']*)'", r': "\1"', as_json)
        parsed = _json.loads(as_json)
    except Exception:
        return []
    out = []
    for s in parsed:
        if not isinstance(s, dict):
            continue
        backup = None
        if s.get("bk"):
            try:
                backup = unquote(base64.b64decode(s["bk"]).decode("utf-8"))
            except Exception:
                backup = None
        file = s.get("file") or ""
        url = file if file.startswith("http") else (f"{BASE}{file}" if file else "")
        if url:
            out.append({
                "quality": s.get("label") or "unknown",
                "url": decode_entities(url),
                "backup": backup,
            })
    return out


async def scrape_episode_watch(ep_slug: str, audio: str) -> dict:
    html = await fetch_text(f"{BASE}/{ep_slug}", {"Referer": BASE})
    title_m = re.search(
        r"<div\b[^>]*class=[\"'][^\"']*info[^\"']*[\"'][^>]*>[\s\S]*?<a[^>]*>([\s\S]*?)</a>",
        html, re.IGNORECASE)
    title = strip_tags(title_m.group(1)) if title_m else ""
    tabs = []
    for m in re.finditer(r"<a\b[^>]*data-toggle=[\"']tab[\"'][^>]*>",
                         html, re.IGNORECASE):
        tag = m.group(0)
        embed_id = attr(tag, "data-id")
        server = attr(tag, "data-mirror") or "AnimeGG"
        version = attr(tag, "data-version") or "subbed"
        if not embed_id:
            continue
        normalized = "dub" if version.startswith("dub") else "sub"
        if audio == "all" or normalized == audio:
            tabs.append({
                "embedId": embed_id,
                "embedUrl": f"{BASE}/embed/{embed_id}",
                "server": server,
                "normalized": normalized,
            })

    async def _resolve(tab, i):
        sources = await scrape_embed(tab["embedId"])
        parts = urlparse(tab["embedUrl"])
        referer = f"{parts.scheme}://{parts.netloc}/"
        streams = []
        for j, s in enumerate(sources):
            streams.append({
                "url": s["url"],
                "type": "hls" if ".m3u8" in s["url"] else "mp4",
                "quality": s["quality"],
                "backup": s["backup"],
                "audio": tab["normalized"],
                "server": tab["server"],
                "embed": tab["embedUrl"],
                "referer": referer,
                "priority": len(tabs) - i,
                "isActive": i == 0 and j == 0,
            })
        streams.append({
            "url": tab["embedUrl"],
            "type": "embed",
            "audio": tab["normalized"],
            "server": f"{tab['server']}-embed",
            "referer": referer,
            "priority": 1,
            "isActive": False,
        })
        return streams

    results = await asyncio.gather(*[_resolve(t, i) for i, t in enumerate(tabs)],
                                   return_exceptions=True)
    streams = []
    for r in results:
        if isinstance(r, Exception):
            continue
        streams.extend(r)
    return {"title": title, "streams": streams}


async def search_fn(query: str) -> list:
    r1 = await search(query)

    first = (query.split() or [""])[0]
    compact = re.sub(r"[^a-zA-Z0-9]", "", first)
    if len(compact) >= 4 and compact.lower() != query.lower():
        try:
            r2 = await search(compact)
            seen = {r["slug"] for r in r1}
            for r in r2:
                if r["slug"] not in seen:
                    r1.append(r)
        except Exception:
            pass
    return r1


async def resolve_series(anilist_id: int, ctx: dict | None = None) -> dict:
    ctx = ctx or await build_ctx(anilist_id)
    key = f"np:{NAME}:{anilist_id}"
    hit = _cache.cached(key, _cache.SHOW_IDENTITY_TTL)
    if hit is not None:
        return hit
    media = ctx["media"]
    titles = build_titles(media, ctx.get("anizip"))
    candidates = await find_top_slugs(titles, search_fn)
    expected = expected_count(media, ctx.get("anizip"))
    try:
        offset = await get_prequel_offset(anilist_id)
    except Exception:
        offset = 0
    is_single_movie = str((media or {}).get("format") or "").upper() == "MOVIE" or expected == 1
    selected = await select_series(candidates, scrape_series, expected,
                                   media.get("status"), offset,
                                   min_score=0.9 if is_single_movie else 0.65)
    if not selected:
        raise RuntimeError(f"AnimeGG match not found for AniList {anilist_id}")
    data = {"slug": selected["slug"], "title": selected["title"],
            "mode": selected["mode"], "offset": offset, "score": selected["score"]}
    _cache.set(key, data, _cache.SHOW_IDENTITY_TTL)
    return data


def _build_lists(anilist_id: int, series: dict, provider_eps: list, ctx: dict, expected) -> dict:
    sub, dub = [], []
    for src in provider_eps:
        number = src["number"] - series["offset"] if series["mode"] == "offset" else src["number"]
        if number < 1:
            continue
        if expected and number > expected:
            continue
        meta = episode_meta(number, ctx)
        base = {
            "number": number,
            "title": meta["title"] or src.get("title") or f"Episode {number}",
            "duration": meta["duration"],
            "filler": meta["filler"],
            "uncensored": meta["uncensored"],
            "description": meta["description"],
            "image": meta["image"],
            "airDate": meta["airDate"],
            "sourceNumber": src["number"],
        }
        if src.get("hasSub"):
            sub.append({"id": f"watch/{NAME}/{anilist_id}/sub/{NAME}-{number}", **base, "audio": "sub"})
        if src.get("hasDub"):
            dub.append({"id": f"watch/{NAME}/{anilist_id}/dub/{NAME}-{number}", **base, "audio": "dub"})
    return {"sub": sub, "dub": dub}


async def get_episodes(anilist_id: int, ctx: dict | None = None) -> dict:
    ctx = ctx or await build_ctx(anilist_id)
    media = ctx["media"]
    series = await resolve_series(anilist_id, ctx)
    episodes = await scrape_series(series["slug"])
    expected = expected_count(media, ctx.get("anizip"))
    return {
        "meta": {
            "id": series["slug"],
            "title": series["title"],
            "source": NAME,
            "matchScore": round(series["score"], 3),
            "numbering": series["mode"],
            "episodeOffset": series["offset"] if series["mode"] == "offset" else 0,
        },
        "episodes": _build_lists(anilist_id, series, episodes, ctx, expected),
    }


async def watch(anilist_id: int, audio: str, ep: int, ctx: dict | None = None) -> list:
    ctx = ctx or await build_ctx(anilist_id)
    series = await resolve_series(anilist_id, ctx)
    provider_ep = int(ep) + series["offset"] if series["mode"] == "offset" else int(ep)
    episodes = await scrape_series(series["slug"])
    found = next((e for e in episodes if e["number"] == provider_ep), None)
    if not found:
        raise RuntimeError(f"AnimeGG episode {provider_ep} not found")
    result = await scrape_episode_watch(found["epSlug"], audio)
    return result["streams"]
