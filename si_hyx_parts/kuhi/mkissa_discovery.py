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


def app_entry_url(html: str):
    m = re.search(r'''(?:import\(|src=)"([^"]+/_app/immutable/entry/app\.[^"]+\.js)"''', html or "")
    return urljoin(_api.REFERER, m.group(1)) if m else None


def _chunk_imports(item_url: str, text: str) -> list:
    urls = []
    for m in re.finditer(r'''(?:import\(|from\s*)"([^"]+\.js)"''', text or ""):
        value = m.group(1)
        if value.startswith(".") or value.startswith("/"):
            nxt = urljoin(item_url, value)
            if nxt not in urls:
                urls.append(nxt)
    for m in re.finditer(r'''"(\.\./(?:chunks|nodes)/[^"\n]+\.js)"''', text or ""):
        nxt = urljoin(item_url, m.group(1))
        if nxt not in urls:
            urls.append(nxt)
    return urls


async def _fetch_chunk(url: str):
    try:
        headers = {"Accept": "application/javascript,*/*", "Referer": f"{_api.REFERER}/"}
        cookie = _api.cookie_header()
        if cookie:
            headers["Cookie"] = cookie
        return await fetch_text(url, headers)
    except Exception:
        return None


async def discover_crypto_config(force: bool = False) -> dict:
    global _crypto_config
    try:
        entry_url = f"{_api.REFERER}/"
        if force:
            entry_url += f"?_mkissa={int(time.time() * 1000)}"
        html = await _api._session_get_text(entry_url, {
            "Accept": "text/html,*/*", "Cache-Control": "no-cache", "Pragma": "no-cache"})
        app_url = _api.app_entry_url(html)
        if not app_url:
            raise RuntimeError("MKissa app entry not found")
        if not force and _api._crypto_config and _api._crypto_config.get("app_url") == app_url:
            return _api._crypto_config
        first = await _api._fetch_chunk(app_url)
        if first is None:
            raise RuntimeError("MKissa app entry fetch failed")
        queue = [app_url]
        seen = set()
        cached = {app_url: first}
        sem = asyncio.Semaphore(_api.DISCOVERY_CONCURRENCY)
        while queue and len(seen) < _api.DISCOVERY_LIMIT:
            batch = []
            while queue and len(batch) < _api.DISCOVERY_CONCURRENCY:
                url = queue.pop(0)
                if url in seen:
                    continue
                seen.add(url)
                batch.append(url)

            async def _one(url: str):
                if url in cached:
                    return {"url": url, "text": cached[url]}
                async with sem:
                    text = await _api._fetch_chunk(url)
                return {"url": url, "text": text} if text is not None else None

            chunks = await asyncio.gather(*[_one(u) for u in batch])
            for item in chunks:
                if not item:
                    continue
                for nxt in _api._chunk_imports(item["url"], item["text"]):
                    if nxt not in seen:
                        queue.append(nxt)
                if not re.search(r"client-crypto|x-aa-boot|aaReq|partB", item["text"]):
                    continue
                config = _api.eval_crypto_chunk(item["text"])
                if config:
                    _api._crypto_config = {**config, "app_url": app_url,
                                      "source_url": item["url"]}
                    return _api._crypto_config
        raise RuntimeError("MKissa crypto chunk not found")
    except Exception:
        _api._crypto_config = None
        raise


async def discover_episode_query(force: bool = False) -> str:
    global _episode_query_cache
    config = await _api.discover_crypto_config(force)
    if (not force and _api._episode_query_cache
            and _api._episode_query_cache.get("app_url") == config.get("app_url")
            and _api._episode_query_cache.get("buildId") == config.get("buildId")):
        return _api._episode_query_cache["query"]

    def inspect(text):
        global _episode_query_cache
        query = _api.eval_episode_query_chunk(text or "")
        if query:
            _api._episode_query_cache = {"app_url": config.get("app_url"),
                                    "buildId": config.get("buildId"), "query": query}
            return query
        return None

    if config.get("source_url"):
        try:
            found = inspect(await _api._fetch_chunk(config["source_url"]))
            if found:
                return found
        except Exception:
            pass
    try:
        html = await _api._session_get_text(f"{_api.REFERER}/", {
            "Accept": "text/html,*/*", "Cache-Control": "no-cache", "Pragma": "no-cache"})
        app_url = _api.app_entry_url(html)
    except Exception:
        app_url = None
    if not app_url:
        return _api.episode_query()
    queue = [app_url]
    seen = set()
    sem = asyncio.Semaphore(_api.DISCOVERY_CONCURRENCY)
    while queue and len(seen) < _api.DISCOVERY_LIMIT:
        batch = []
        while queue and len(batch) < _api.DISCOVERY_CONCURRENCY:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            batch.append(url)

        async def _one(url: str):
            async with sem:
                text = await _api._fetch_chunk(url)
            return {"url": url, "text": text} if text is not None else None

        chunks = await asyncio.gather(*[_one(u) for u in batch])
        for item in chunks:
            if not item:
                continue
            found = inspect(item["text"])
            if found:
                return found
            for nxt in _api._chunk_imports(item["url"], item["text"]):
                if nxt not in seen:
                    queue.append(nxt)
    return _api.episode_query()
