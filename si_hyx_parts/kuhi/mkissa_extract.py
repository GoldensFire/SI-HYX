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


def hex_to_bytes(hex_value: str) -> bytes:
    clean = re.sub(r"[^0-9a-fA-F]", "", hex_value or "")
    return bytes(int(clean[i:i + 2], 16) for i in range(0, len(clean), 2))


async def aes_decrypt(hex_value: str) -> str:
    plain = _api.aes_cbc_decrypt(b"kiemtienmua911ca", b"1234567890oiuytr", _api.hex_to_bytes(hex_value))
    return plain.decode("utf-8")


async def extract_mp4(embed_id: str):
    try:
        res = await _api._raw_get(f"https://www.mp4upload.com/embed-{embed_id}.html", {"User-Agent": _api.UA4, "Referer": "https://mp4upload.com/"})
        if res.status_code != 200:
            return None
        html = res.text
        m = re.search(r'''player\.src\s*\(\s*\{[^}]*\bsrc\s*:\s*"([^"]+)"''', html)
        if not m:
            m = re.search(r'''"file"\s*:\s*"(https?:[^"]+\.mp4[^"]*)"''', html)
        if not m:
            m = re.search(r'''\bsrc\s*:\s*"(https?:[^"]+\.mp4[^"]*)"''', html)
        return m.group(1).replace("\\", "") if m else None
    except Exception:
        return None


async def extract_uns(url: str):
    try:
        parsed = urlparse(url)
        vid = (parsed.fragment or "").split("&")[0]
        if not vid:
            return None
        base = f"{parsed.scheme}//{parsed.netloc}"
        res = await _api._raw_get(base + "/api/v1/video?id=" + quote(vid, safe='') + "&w=1280&h=720&r=", {"User-Agent": _api.UA4, "Referer": base + "/#" + vid, "Origin": base})
        if res.status_code != 200:
            return None
        hex_value = res.text.strip()
        if not hex_value or not re.fullmatch(r"[0-9a-fA-F]+", hex_value):
            return None
        data = json.loads(await _api.aes_decrypt(hex_value))
        return data.get("source") or data.get("cf")
    except Exception:
        return None


async def extract_ok(embed_id: str):
    try:
        res = await _api._raw_get(f"https://ok.ru/videoembed/{embed_id}", {"User-Agent": _api.UA4, "Referer": "https://ok.ru/"})
        if res.status_code != 200:
            return None
        m = re.search(r'''ondemandHls\\&quot;:\\&quot;(https?://.*?)\\&quot;''', res.text)
        return m.group(1).replace("\\u0026", "&") if m else None
    except Exception:
        return None


async def extract_stream_sb(embed_id: str):
    try:
        base_headers = {"User-Agent": _api.UA4, "Referer": f"{_api.REFERER}/", "watchsb": "streamsb", "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9"}
        r1 = await _api._raw_get(f"https://streamsb.net/api/v1/video?id={embed_id}", base_headers)
        sid_m = re.search(r"sid=([^;]+)", r1.headers.get("set-cookie", ""))
        sid = sid_m.group(1) if sid_m else ""
        m = re.search(r'''window\.location\.replace\('([^']+)'\)''', r1.text or "")
        if not m:
            return None
        data = await fetch_json(m.group(1), dict(base_headers, **{"Cookie": f"sid={sid}", "Referer": f"https://streamsb.net/e/{embed_id}.html"}))
        return ((data.get("stream_data") or {}).get("file") or (data.get("data") or {}).get("file"))
    except Exception:
        return None


async def extract_clock(url: str):
    try:
        parsed = urlparse(url)
        clock_url = url if "/clock.json" in (parsed.path or "") else url.replace("/clock", "/clock.json", 1)
        data = await fetch_json(clock_url, {"User-Agent": _api.UA4, "Referer": "https://allanime.day/player.html", "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9", "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin"})
        links = data.get("links") if isinstance(data, dict) else None
        links = links if isinstance(links, list) else []
        best = next((item for item in links if isinstance(item, dict) and item.get("hls") and item.get("link")), None)
        best = best or next((item for item in links if isinstance(item, dict) and item.get("link")), None)
        return best.get("link") if best else None
    except Exception:
        return None


async def extract_streamlare(embed_id: str):
    try:
        res = await _api._raw_post("https://streamlare.com/api/video/stream/get", {"id": embed_id}, {"Content-Type": "application/json", "User-Agent": _api.UA4, "Referer": "https://streamlare.com/", "Origin": "https://streamlare.com", "Accept": "application/json, */*"})
        if res.status_code != 200:
            return None
        data = res.json()
        return (data.get("data") or {}).get("file")
    except Exception:
        return None


def embed_media_type(url):
    if not url:
        return None
    if ".m3u8" in url:
        return "hls"
    if ".mp4" in url:
        return "mp4"
    return "direct"


def is_clock_url(url: str) -> bool:
    try:
        parsed = urlparse(url or "")
        host = (parsed.hostname or "").lower()
        path = parsed.path or ""
        return host == "allanime.day" and re.search("/apivtwo/clock", path) is not None
    except Exception:
        return False


async def extract_source(src: dict) -> dict:
    src = src or {}
    url = src.get("sourceUrl")
    if url and url.startswith("--"):
        url = _api.decode_hex_url(url[2:])
    if url and url.startswith("/apivtwo/clock"):
        url = "https://allanime.day" + url.replace("/clock", "/clock.json", 1)
    if url and re.match("https?://allanime[.]day/apivtwo/clock", url or "", re.IGNORECASE):
        if "/clock?" in url:
            url = url.replace("/clock?", "/clock.json?", 1)
    extracted_url = None
    try:
        parsed = urlparse(url or "")
        host = (parsed.hostname or "").lower().removeprefix("www.")
        path = parsed.path or ""
        if host == "allanime.day" and re.search("/apivtwo/clock", path, re.IGNORECASE):
            extracted_url = await _api.extract_clock(url)
        elif src.get("type") == "player":
            extracted_url = url
        elif host == "mp4upload.com":
            m = re.search(r"embed-([a-zA-Z0-9]+)[.]html", url or "", re.IGNORECASE)
            if m:
                extracted_url = await _api.extract_mp4(m.group(1))
        elif host == "uns.bio" or host.endswith(".uns.bio"):
            extracted_url = await _api.extract_uns(url)
        elif host == "ok.ru":
            m = re.search("/(?:videoembed/)?([0-9]+)(?:[/?#]|$)", url or "", re.IGNORECASE)
            if m:
                extracted_url = await _api.extract_ok(m.group(1))
        elif "streamsb." in host:
            m = re.search("/(?:e/|embed-)([a-zA-Z0-9]+)", url or "", re.IGNORECASE)
            if m:
                extracted_url = await _api.extract_stream_sb(m.group(1))
        elif "streamlare." in host:
            m = re.search("/e/([a-zA-Z0-9]+)", url or "", re.IGNORECASE)
            if m:
                extracted_url = await _api.extract_streamlare(m.group(1))
    except Exception:
        pass
    if extracted_url:
        extracted_url = decode_entities(extracted_url)
    return {"name": decode_entities(src.get("sourceName") or ""), "url": url, "extractedUrl": extracted_url, "extractedType": _api.embed_media_type(extracted_url), "type": src.get("type"), "priority": src.get("priority"), "headers": {"Referer": _api.REFERER, "User-Agent": _api.UA4}, "downloads": src.get("downloads")}


def _map_source(item: dict, audio: str):
    url = item.get("extractedUrl") or item.get("url")
    if not url:
        return None
    if _api.is_clock_url(item.get("url")) and not item.get("extractedUrl"):
        return None
    headers = item.get("headers") or {}
    return {"url": url, "type": item.get("extractedType") or "hls", "server": item.get("name") or "MKissa", "audio": audio, "referer": headers.get("Referer") or _api.REFERER, "headers": dict(headers)}


async def watch(anilist_id: int, audio: str, ep: int, ctx=None) -> list:
    if audio not in ("sub", "dub", "raw", "all"):
        raise ValueError(f"unknown audio: {audio!r}")
    ctx = ctx or await build_ctx(int(anilist_id))
    ep_num = int(ep)
    cache_key = f"{anilist_id}:{audio}:{ep_num}"
    captcha = ctx.get("captcha") if isinstance(ctx.get("captcha"), dict) else None
    entry = _api._watch_cache.get(cache_key)
    if entry and entry.get("expires_at", 0) > time.time() and not captcha:
        return entry["data"]
    series = await _api.resolve_series(int(anilist_id), ctx)
    show_id = series.get("show_id")
    if not show_id:
        raise RuntimeError(f"No MKissa match for AniList {anilist_id}")
    if not captcha:
        await _api.warm_watch_page(show_id, series.get("show"), ep_num, "sub" if audio == "all" else audio)
    audios = ["sub", "dub"] if audio == "all" else [audio]
    try:
        episodes = await asyncio.gather(*[_api.get_episode_sources(show_id, ep_num, aud, captcha) for aud in audios])
    except _api.NeedCaptchaError:
        if entry and entry.get("data"):
            return entry["data"]
        raise
    ranked = []
    for aud, episode in zip(audios, episodes):
        for src in (episode or {}).get("sourceUrls") or []:
            try:
                item = await _api.extract_source(src)
            except Exception:
                continue
            mapped = _api._map_source(item, aud)
            if mapped:
                ranked.append((item.get("priority") or 0, mapped))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    streams = [mapped for _, mapped in ranked]
    _api._watch_cache[cache_key] = {"data": streams, "expires_at": time.time() + _api.WATCH_MEMORY_TTL}
    return streams
