# Kuhi/anime-api, MIT, Copyright (c) 2026 aryaniiil. See LICENSE.
"""Kuhi's last-resort Miruro pipe, without its FastAPI endpoint layer."""
import asyncio
import base64
import gzip
import io
import json
from urllib.parse import urlsplit

from ._http import UA
from ._transport import AsyncClient, MAX_RESPONSE_BYTES

BASES = ("https://www.miruro.ru", "https://www.miruro.bz", "https://www.miruro.online")
RANKING = ("zoro", "bee", "telli", "arc", "yugen", "jet", "neo", "kiwi")


def encode(payload):
    return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")


def decode(value):
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        content = stream.read(MAX_RESPONSE_BYTES + 1)
    if len(content) > MAX_RESPONSE_BYTES:
        raise ValueError("Miruro: ответ превысил лимит")
    result = json.loads(content.decode("utf-8"))
    return result if isinstance(result, dict) else {}


async def pipe(path, query):
    request = encode({"path": path, "method": "GET", "query": query,
                      "body": None, "version": "0.1.0"})
    for base in BASES:
        try:
            async with AsyncClient(timeout=15, follow_redirects=True) as client:
                response = await client.get(f"{base}/api/secure/pipe?e={request}",
                                            headers={"Origin": base, "Referer": base + "/", "User-Agent": UA})
            if response.status_code == 200:
                return decode(response.text.strip())
        except Exception:
            continue
    return {}


def _translate_id(value):
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("utf-8")
        return decoded if ":" in decoded else value
    except (ValueError, UnicodeError):
        return value


async def episodes(aid):
    data = await pipe("episodes", {"anilistId": aid})
    for provider in (data.get("providers") or {}).values():
        for row in (provider.get("episodes") or {}).get("sub", ()):
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                row["id"] = _translate_id(row["id"])
    return data


def encode_id(identity):
    return base64.urlsafe_b64encode(identity.encode("utf-8")).decode("ascii").rstrip("=")


async def _streams(aid, name, row):
    try:
        identity = str(row.get("id") or "")
        if not identity or row.get("audio", "sub") != "sub":
            return []
        payload = await pipe("sources", {"episodeId": encode_id(identity), "provider": name,
                                        "category": "sub", "anilistId": aid})
        found = payload.get("streams") or payload.get("sources") or []
        if payload.get("audio", "sub") != "sub":
            return []
        out = []
        for source in found if isinstance(found, list) else []:
            url = str(source.get("url") or source.get("file") or "")
            path = urlsplit(url).path.lower()
            kind = source.get("type")
            if kind not in ("hls", "dash", "mp4"):
                kind = "hls" if path.endswith(".m3u8") else "dash" if path.endswith(".mpd") else "mp4" if path.endswith(".mp4") else "embed"
            if source.get("audio", "sub") == "sub":
                out.append({**source, "url": url, "type": kind, "audio": "sub",
                            "provider": "miruro/" + name,
                            "headers": {**(payload.get("headers") or {}), **(source.get("headers") or {})},
                            "subtitles": source.get("subtitles") or payload.get("subtitles") or [],
                            "intro": source.get("intro") or payload.get("intro"),
                            "outro": source.get("outro") or payload.get("outro")})
        return out
    except Exception:
        return []


async def streams(aid, episode, catalog):
    providers = catalog.get("providers") or {}
    order = list(RANKING) + [n for n in providers if n not in RANKING]
    jobs = []
    for name in order:
        for row in ((providers.get(name) or {}).get("episodes") or {}).get("sub", ()):
            if str(row.get("number")) in (str(episode), str(float(episode))):
                jobs.append(_streams(aid, name, row))
                break
    results = await asyncio.gather(*jobs)
    return [stream for result in results for stream in result]
