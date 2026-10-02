# Native Kuhi/anime-api, MIT, Copyright (c) 2026 aryaniiil. See LICENSE.
import asyncio
import re
from urllib.parse import quote, urlparse

from si_hyx_parts.kuhi import _cache
from si_hyx_parts.kuhi._http import fetch_text
from si_hyx_parts.kuhi._match import (
    attr, build_titles, decode_entities, episode_meta, expected_count,
    find_top_slugs, get_prequel_offset, select_series, strip_tags,
)
from si_hyx_parts.kuhi._media import build_ctx

NAME = "anineko"
BASE = "https://anineko.to"


async def search(query: str) -> list:
    html = await fetch_text(f"{BASE}/browser?keyword={quote(query)}")
    results = []
    for m in re.finditer(
            r"<a\b[^>]*class=[\"'][^\"']*nv-anime-thumb[^\"']*[\"'][^>]*>[\s\S]*?</a>",
            html, re.IGNORECASE):
        tag = re.search(r"<a\b[^>]*>", m.group(0), re.IGNORECASE)
        href = attr(tag.group(0) if tag else "", "href")
        sm = re.search(r"/watch/([^/?#]+)", href)
        if not sm:
            continue
        tm = re.search(
            r"<(?:h3|[^>]+class=[\"'][^\"']*nv-anime-title[^\"']*[\"'][^>]*)>([\s\S]*?)</(?:h3|[^>]+)>",
            m.group(0), re.IGNORECASE)
        text = strip_tags(tm.group(1)) if tm else sm.group(1).replace("-", " ")
        results.append({"slug": sm.group(1), "text": text})
    return results


async def scrape_series(slug: str) -> list:
    html = await fetch_text(f"{BASE}/watch/{slug}")
    episodes = []
    for m in re.finditer(
            r"<article\b[^>]*class=[\"'][^\"']*nv-info-episode-item[^\"']*[\"'][^>]*>([\s\S]*?)</article>",
            html, re.IGNORECASE):
        block = m.group(1)
        link = re.search(
            r"<a\b[^>]*class=[\"'][^\"']*nv-info-episode-main[^\"']*[\"'][^>]*>",
            block, re.IGNORECASE)
        href = attr(link.group(0) if link else "", "href")
        nm = re.search(r"/ep-(\d+)", href)
        if not nm:
            continue
        tm = re.search(
            r"<a\b[^>]*class=[\"'][^\"']*nv-info-episode-main[^\"']*[\"'][^>]*>[\s\S]*?<span[^>]*>([\s\S]*?)</span>",
            block, re.IGNORECASE)
        title = strip_tags(tm.group(1)) if tm else ""
        badges = [strip_tags(b).lower()
                  for b in re.findall(r"<span\b[^>]*>([\s\S]*?)</span>", block, re.IGNORECASE)]
        episodes.append({
            "number": int(nm.group(1)),
            "title": title or f"Episode {nm.group(1)}",
            "epSlug": f"ep-{nm.group(1)}",
            "hasSub": "sub" in badges,
            "hasDub": "dub" in badges,
        })
    episodes.sort(key=lambda e: e["number"])
    seen, out = set(), []
    for e in episodes:
        if e["number"] not in seen:
            seen.add(e["number"])
            out.append(e)
    return out

HLS_PATTERNS = [
    re.compile(r"const\s+src\s*=\s*[\"'](https?://[^\"']+\.m3u8[^\"']*)[\"']", re.IGNORECASE),
    re.compile(r"file\s*:\s*[\"'](https?://[^\"']+\.m3u8[^\"']*)[\"']", re.IGNORECASE),
    re.compile(r"[\"'](https?://[^\"']+/master\.m3u8[^\"']*)[\"']", re.IGNORECASE),
    re.compile(r"[\"'](https?://[^\"']+\.m3u8[^\"']*)[\"']", re.IGNORECASE),
]


async def extract_hls(embed_url: str):
    try:
        html = await fetch_text(embed_url, {"Referer": f"{BASE}/"})
    except Exception:
        return None
    for pat in HLS_PATTERNS:
        m = pat.search(html)
        if m:
            return decode_entities(m.group(1))
    return None


async def scrape_episode_watch(series_slug: str, ep_slug: str, audio: str) -> list:
    html = await fetch_text(f"{BASE}/watch/{series_slug}/{ep_slug}",
                            {"Referer": f"{BASE}/watch/{series_slug}"})
    by_audio = {"sub": [], "dub": []}
    panels = re.finditer(
        r"<div\b[^>]*class=[\"'][^\"']*nv-server-grid[^\"']*[\"'][^>]*data-id=[\"']([^\"']+)[\"'][^>]*>([\s\S]*?)(?=<div\b[^>]*class=[\"'][^\"']*nv-server-grid|$)",
        html, re.IGNORECASE)
    for panel in panels:
        aud = "dub" if "dub" in panel.group(1).lower() else "sub"
        for btn in re.finditer(r"data-video=[\"']([^\"']+)[\"']", panel.group(2), re.IGNORECASE):
            by_audio[aud].append(decode_entities(btn.group(1)))
    audios = ["sub", "dub"] if audio == "all" else [audio]

    async def _resolve(embed, i, aud, total):
        hls = await extract_hls(embed)
        origin = urlparse(embed).scheme + "://" + urlparse(embed).netloc + "/"
        return {
            "url": hls or embed,
            "type": "hls" if hls else "embed",
            "embed": embed,
            "audio": aud,
            "server": "AniNeko",
            "priority": total - i,
            "referer": origin,
            "isActive": i == 0,
        }

    streams = []
    for aud in audios:
        embeds = by_audio.get(aud) or []
        resolved = await asyncio.gather(
            *[_resolve(e, i, aud, len(embeds)) for i, e in enumerate(embeds)])
        streams.extend(resolved)
    return streams


async def resolve_series(anilist_id: int, ctx: dict | None = None) -> dict:
    ctx = ctx or await build_ctx(anilist_id)
    key = f"np:anineko:{anilist_id}"
    hit = _cache.cached(key, _cache.SHOW_IDENTITY_TTL)
    if hit is not None:
        return hit
    media = ctx["media"]
    titles = build_titles(media, ctx.get("anizip"))
    candidates = await find_top_slugs(titles, search)
    expected = expected_count(media, ctx.get("anizip"))
    try:
        offset = await get_prequel_offset(anilist_id)
    except Exception:
        offset = 0
    selected = await select_series(candidates, scrape_series, expected, media.get("status"), offset)
    if not selected:
        raise RuntimeError(f"AniNeko match not found for AniList {anilist_id}")
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
            sub.append({"id": f"watch/anineko/{anilist_id}/sub/anineko-{number}", **base, "audio": "sub"})
        if src.get("hasDub"):
            dub.append({"id": f"watch/anineko/{anilist_id}/dub/anineko-{number}", **base, "audio": "dub"})
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
    return await scrape_episode_watch(series["slug"], f"ep-{provider_ep}", audio)
