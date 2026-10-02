# Native Kuhi/anime-api, MIT, Copyright (c) 2026 aryaniiil. See LICENSE.
import asyncio
import base64
import hashlib
import re
from urllib.parse import urlencode, urlparse
from si_hyx_parts.kuhi import _cache
from si_hyx_parts.kuhi._http import fetch_json, fetch_text
from si_hyx_parts.kuhi._match import build_titles, episode_meta, expected_count
from si_hyx_parts.kuhi._media import build_ctx

from . import reanime as _api


async def _resolve_stream(anilist_id: int, audio: str, ep: int, ctx: dict | None = None):
    series = await _api.resolve_series(anilist_id, ctx)
    title = series["title"]
    slug = series["animeId"]
    order = {"HD-2": 0, "HD-1": 1}

    async def _watch_api():
        try:
            return await fetch_json(f"{_api.BASE}/api/watch/{slug}/{ep}")
        except Exception:
            return None

    async def _flix_api():
        try:
            return await fetch_json(f"{_api.BASE}/api/flix/{anilist_id}/{ep}")
        except Exception:
            return None

    watch_data, flix_data = await asyncio.gather(_watch_api(), _flix_api())
    links = list((watch_data or {}).get("episode_links") or []) if isinstance(watch_data, dict) else []
    if isinstance(flix_data, dict) and flix_data.get("success") and isinstance(
            flix_data.get("servers"), list):
        seen_ids = {s.get("$id") for s in links if isinstance(s, dict)}
        for s in flix_data["servers"]:
            if isinstance(s, dict) and s.get("$id") not in seen_ids:
                seen_ids.add(s.get("$id"))
                links.append(s)
    if audio == "sub":
        audio_types = ("sub", "s-sub")
    elif audio == "dub":
        audio_types = ("dub", "s-dub")
    else:
        audio_types = ("sub", "s-sub", "dub", "s-dub")
    servers = sorted(
        [s for s in links if isinstance(s, dict) and s.get("dataType") in audio_types],
        key=lambda s: order.get(s.get("serverName"), 9),
    )
    if not servers:
        raise RuntimeError(f"No {audio} servers for \"{title}\" ep {ep}")
    seen, unique = set(), []
    for s in servers:
        k = (s.get("serverName"), s.get("dataType"), s.get("dataLink"))
        if k not in seen:
            seen.add(k)
            unique.append(s)

    async def _decrypt_one(server, index):
        try:
            embed_html = await fetch_text(server["dataLink"], {"Referer": _api.BASE + "/"})
            stream = await _api._extract_flixcloud(embed_html, referer=_api.BASE + "/")
            return {"server": server, "stream": stream, "index": index}
        except Exception as e:
            return {"server": server, "error": str(e), "index": index}

    decrypted = await asyncio.gather(
        *[_decrypt_one(s, i) for i, s in enumerate(unique)])
    streams = [d for d in decrypted if d.get("stream") and d["stream"].get("url")]
    if not streams:
        err = next((d.get("error") for d in decrypted if d.get("error")), "No decrypted streams")
        raise RuntimeError(err)
    return {"title": title, "slug": slug, "watchData": watch_data,
            "servers": unique, "streams": streams}


def _norm_audio(data_type: str, fallback: str) -> str:
    if isinstance(data_type, str) and "dub" in data_type.lower():
        return "dub"
    if isinstance(data_type, str) and "sub" in data_type.lower():
        return "sub"
    return fallback


async def watch(anilist_id: int, audio: str, ep: int, ctx: dict | None = None) -> list:
    if audio not in ("sub", "dub", "all"):
        raise ValueError("audio must be sub, dub or all")
    anilist_id, ep = int(anilist_id), int(ep)
    resolved = await _api._resolve_stream(anilist_id, audio, ep, ctx)
    total = len(resolved["streams"])
    out, seen_urls = [], set()
    for item in resolved["streams"]:
        server, stream = item["server"], item["stream"]
        if stream["url"] in seen_urls:
            continue
        seen_urls.add(stream["url"])
        try:
            parsed = urlparse(server.get("dataLink") or "")
            referer = parsed.scheme + "://" + parsed.netloc + "/" if parsed.netloc else _api.BASE + "/"
        except Exception:
            referer = _api.BASE + "/"
        entry = {
            "url": stream["url"],
            "type": "hls",
            "server": server.get("serverName"),
            "audio": _api._norm_audio(server.get("dataType"), audio if audio != "all" else "sub"),
            "embed": server.get("dataLink"),
            "referer": referer,
            "subtitles": stream.get("subtitles") or [],
            "priority": total - item["index"],
        }
        if stream.get("thumbnails_vtt") is not None:
            entry["thumbnails_vtt"] = stream["thumbnails_vtt"]
        if stream.get("video_title") is not None:
            entry["video_title"] = stream["video_title"]
        if stream.get("intro_chapter") is not None:
            entry["intro"] = stream["intro_chapter"]
        if stream.get("outro_chapter") is not None:
            entry["outro"] = stream["outro_chapter"]
        out.append(entry)
    return out
