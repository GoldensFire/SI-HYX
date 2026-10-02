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

from . import aniwaves as _api


def _parse_server_groups(html: str) -> list:
    markers = []
    for m in re.finditer(r"<div\b([^>]*)>", html or "", re.IGNORECASE):
        dtype = attr(m.group(1), "data-type").lower()
        if dtype in ("sub", "dub"):
            markers.append((m.start(), dtype))
    groups = []
    for i, (start, audio) in enumerate(markers):
        end = markers[i + 1][0] if i + 1 < len(markers) else len(html)
        for li in re.finditer(r"<li\b([^>]*)>([\s\S]*?)</li>", html[start:end], re.IGNORECASE):
            link_id = attr(li.group(1), "data-link-id")
            if not link_id:
                continue
            groups.append({"audio": audio, "linkId": link_id,
                           "serverId": attr(li.group(1), "data-sv-id") or None,
                           "server": strip_tags(li.group(2)) or "AniWaves"})
    return groups


async def _fetch_servers(series: dict, episode: dict) -> list:
    result = await _api._ajax(
        f"/ajax/server/list?servers={quote(str(series['siteId']), safe=_api._QSAFE)}"
        f"&eps={quote(str(episode['sourceNumber']), safe=_api._QSAFE)}",
        f"{_api.BASE}/watch/{series['slug']}/ep-{episode['sourceNumber']}")
    return _api._parse_server_groups(str(result or ""))


async def _fetch_source(link_id: str, referer: str) -> dict:
    result = await _api._ajax(f"/ajax/sources?id={quote(str(link_id), safe=_api._QSAFE)}&asi=0&autoPlay=0",
                         referer)
    if not isinstance(result, dict) or not result.get("url"):
        raise RuntimeError("AniWaves source response has no embed url")
    return result


def _aniwaves_can_vidplay(url: str) -> bool:
    return bool(re.search(r"play\.echovideo\.ru/embed-[01]/", str(url), re.IGNORECASE))


async def _aniwaves_extract_vidplay(embed_url: str, referer: str) -> list:
    parts = urlparse(str(embed_url))
    m = re.match(r"^/(embed-[01])/([^/]+)$", parts.path or "", re.IGNORECASE)
    if not m:
        raise RuntimeError(f"Cannot extract Vidplay id from {embed_url}")
    endpoint = (f"{parts.scheme}://{parts.netloc}/{m.group(1)}/getSources"
                f"?id={quote(m.group(2), safe=_api._QSAFE)}")
    data = await fetch_json(endpoint, {"Referer": embed_url,
                                       "X-Requested-With": "XMLHttpRequest"})
    raw = data.get("sources") if isinstance(data, dict) else None
    items = raw if isinstance(raw, list) else ([raw] if isinstance(raw, str) else [])
    out = []
    for item in items:
        file = item if isinstance(item, str) else (item or {}).get("file") or (item or {}).get("url")
        if file:
            out.append({"url": decode_entities(file), "type": "hls"})
    if not out:
        raise RuntimeError("Vidplay response has no sources")
    return out


def _aniwaves_can_datasv(url: str) -> bool:
    return bool(re.search(r"play\.echovideo\.ru/embed-20/", str(url), re.IGNORECASE))


async def _aniwaves_extract_datasv(embed_url: str, referer: str) -> list:
    parts = urlparse(str(embed_url))
    m = re.match(r"^/embed-20/([^/]+)$", parts.path or "", re.IGNORECASE)
    if not m:
        raise RuntimeError(f"Cannot extract DATASV id from {embed_url}")
    endpoint = (f"{parts.scheme}://{parts.netloc}/embed-20/getSources"
                f"?id={quote(m.group(1), safe=_api._QSAFE)}")
    data = await fetch_json(endpoint, {"Referer": embed_url,
                                       "X-Requested-With": "XMLHttpRequest"})
    raw = (data or {}).get("sources") or {}
    sources = []
    for quality, urls in raw.items():
        for item in urls if isinstance(urls, list) else [urls]:
            if isinstance(item, str) and item:
                sources.append({"url": decode_entities(item), "type": "mp4", "quality": quality})
    if not sources:
        raise RuntimeError("DATASV response has no sources")
    origin = f"{parts.scheme}://{parts.netloc}/"

    async def _head_ok(item):
        try:
            async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
                res = await client.head(item["url"], headers={"User-Agent": UA,
                                                                "Referer": origin})
            return item if res.status_code < 400 else None
        except Exception:
            return None

    valid = [s for s in await asyncio.gather(*[_head_ok(s) for s in sources]) if s]
    return valid or sources


def _aniwaves_can_megaplay(url: str) -> bool:
    return bool(re.search(r"megaplay\.[^/]+/stream/", str(url), re.IGNORECASE))


async def _aniwaves_extract_megaplay(embed_url: str, referer: str) -> list:
    parts = urlparse(str(embed_url))
    origin = f"{parts.scheme}://{parts.netloc}"
    page_html = await fetch_text(embed_url, {"Accept": "text/html,*/*",
                                              "Referer": referer or f"{origin}/"})
    file_match = re.search(r"data-id=[\"']([^\"']+)[\"']", page_html, re.IGNORECASE)
    if not file_match:
        raise RuntimeError(f"MegaPlay file id not found: {embed_url}")
    file_id = file_match.group(1)
    script_urls = [urljoin(embed_url, m.group(1)) for m in
                   re.finditer(r"<script[^>]+src=[\"']([^\"']+)[\"']", page_html, re.IGNORECASE)]

    async def _get_script(url: str):
        try:
            return await fetch_text(url, {"Referer": embed_url})
        except Exception:
            return None

    script = next((s for s in await asyncio.gather(*[_get_script(u) for u in script_urls])
                   if s and re.search(r"getSources", s, re.IGNORECASE)
                   and re.search(r"AES-CBC", s, re.IGNORECASE)), None)
    if not script:
        raise RuntimeError(f"MegaPlay client script not found: {embed_url}")
    routes = sorted(set(re.findall(r"[\"'](stream/getSources[\w/.-]*)[\"']", script, re.IGNORECASE)),
                    key=len)
    legacy = routes[0] if routes else None
    modern = next((r for r in routes if r != legacy and r.startswith(legacy or "\0")), None)
    if not legacy and not modern:
        raise RuntimeError(f"MegaPlay source routes not found: {embed_url}")

    async def _get_json(route):
        try:
            return await fetch_json(
                f"{origin}/{route.lstrip('/')}"
                f"?id={quote(file_id, safe=_api._QSAFE)}&id={quote(file_id, safe=_api._QSAFE)}",
                {"Accept": "application/json,*/*", "Referer": embed_url,
                 "X-Requested-With": "XMLHttpRequest"})
        except Exception:
            return None

    modern_data, legacy_data = await asyncio.gather(*[_get_json(r) for r in (modern, legacy)])
    urls = []
    for data in (modern_data, legacy_data):
        file = ((data or {}).get("sources") or {}).get("file")
        if isinstance(file, str) and file and file not in urls:
            urls.append(file)
    if not urls:
        raise RuntimeError(f"MegaPlay response has no sources: {embed_url}")
    return [{"url": decode_entities(u), "type": "hls"} for u in urls]


def _aniwaves_can_byse(url: str) -> bool:
    return bool(re.search(r"(?:bysesayeveum\.com|gn1r5n\.org)/e/", str(url), re.IGNORECASE))


async def _resolve_source(embed_url: str, referer: str) -> list:
    for _name, matches, extract in _api._ANIWAVES_EXTRACTORS:
        if matches(embed_url):
            try:
                streams = await extract(embed_url, referer)
            except Exception:
                return []
            return [s if isinstance(s, dict) else {"url": s, "type": "hls"} for s in streams]
    return []


def _skip_range(value):
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        start, end = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    if not end > start:
        return None
    return {"start": int(start) if start.is_integer() else start,
            "end": int(end) if end.is_integer() else end}


async def watch(anilist_id: int, audio: str, ep: int, ctx: dict | None = None) -> list:
    ctx = ctx or await build_ctx(anilist_id)
    media = ctx["media"]
    series = await _api.resolve_series(anilist_id, {**ctx, "media": media})
    expected = expected_count(media, ctx.get("anizip"))
    episodes = _api._align_episodes(await _api._fetch_episodes(series), media, expected)
    episode = next((e for e in episodes if e["number"] == int(ep)), None)
    audios = ["sub", "dub"] if audio == "all" else [audio]
    if not episode or not any(episode.get("hasSub" if a == "sub" else "hasDub") for a in audios):
        raise RuntimeError(f"AniWaves {audio} episode {ep} not found")
    servers = [s for s in await _api._fetch_servers(series, episode) if s["audio"] in audios]
    if not servers:
        raise RuntimeError(f"AniWaves has no {audio} servers for episode {ep}")
    referer = f"{_api.BASE}/watch/{series['slug']}/ep-{episode['sourceNumber']}"

    async def _one(server):
        try:
            return {"server": server, "source": await _api._fetch_source(server["linkId"], referer)}
        except Exception as err:
            return {"server": server, "error": err}

    settled = await asyncio.gather(*[_one(s) for s in servers])
    resolved = []
    for item in settled:
        direct = await _api._resolve_source(item["source"]["url"], referer) if item.get("source", {}).get("url") else []
        resolved.append({**item, "direct": direct})
    streams, intro, outro = [], None, None
    for item in resolved:
        if not item.get("source", {}).get("url"):
            continue
        try:
            source_referer = f"{urlparse(item['source']['url']).scheme}://{urlparse(item['source']['url']).netloc}/"
            if "://" not in source_referer:
                raise ValueError("bad url")
        except Exception:
            source_referer = referer
        skip = item["source"].get("skip_data") or {}
        if intro is None:
            intro = _api._skip_range(skip.get("intro"))
        if outro is None:
            outro = _api._skip_range(skip.get("outro"))
        for stream in item["direct"]:
            entry = {**stream, "url": stream["url"], "type": stream.get("type", "hls"),
                     "server": item["server"]["server"], "audio": item["server"]["audio"],
                     "referer": stream.get("referer") or source_referer,
                     "headers": dict(stream.get("headers") or {}), "embed": item["source"]["url"],
                     "priority": 5 if not streams else 4, "isActive": not streams}
            if stream.get("quality"):
                entry["quality"] = stream["quality"]
            streams.append(entry)
        streams.append({"url": item["source"]["url"], "type": "embed",
                        "server": item["server"]["server"], "audio": item["server"]["audio"],
                        "referer": source_referer, "embed": item["source"]["url"],
                        "priority": 5 if not streams else 4, "isActive": not streams})
    if not streams:
        failure = next((item.get("error") for item in settled if item.get("error")), None)
        raise failure if failure else RuntimeError(f"AniWaves sources unavailable for episode {ep}")
    for stream in streams:
        if intro and not stream.get("intro"):
            stream["intro"] = dict(intro)
        if outro and not stream.get("outro"):
            stream["outro"] = dict(outro)
    return streams
