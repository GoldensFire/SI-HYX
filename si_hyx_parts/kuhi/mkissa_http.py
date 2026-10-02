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


def decode_hex_url(hex_value: str) -> str:
    out = []
    for i in range(0, len(hex_value), 2):
        pair = hex_value[i:i + 2].lower()
        out.append(_api.HEX_TABLE.get(pair, pair))
    return "".join(out)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hmac_bytes(key, value: str) -> bytes:
    if isinstance(key, str):
        key = key.encode("utf-8")
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()


def store_cookies(headers) -> None:
    try:
        raw = headers.get_list("set-cookie")
    except Exception:
        single = headers.get("set-cookie") if hasattr(headers, "get") else None
        raw = [single] if single else []
    for value in raw or []:
        for part in re.split(r",(?=[^;,]+?=)", str(value)):
            pair = part.split(";")[0].strip() if part else ""
            index = pair.find("=")
            if index > 0:
                _api._session_cookies[pair[:index]] = pair[index + 1:]


def cookie_header() -> str:
    return "; ".join(f"{k}={v}" for k, v in _api._session_cookies.items())


def browser_headers(extra=None):
    headers = {
        "User-Agent": _api.UA4,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "sec-ch-ua": '"Not=A?Brand";v="99", "Google Chrome";v="151", "Chromium";v="151"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }
    cookie = _api.cookie_header()
    if cookie:
        headers["Cookie"] = cookie
    if extra:
        headers.update(extra)
    return headers


def api_headers(build_id: str, extra=None):
    headers = {
        "Referer": f"{_api.REFERER}/",
        "Origin": _api.REFERER,
        "x-build-id": build_id,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Priority": "u=1, i",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site",
    }
    if extra:
        headers.update(extra)
    return headers


async def _session_get_text(url, headers=None, timeout=_api.FETCH_TIMEOUT):
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        res = await client.get(url, headers=_api.browser_headers(headers or {}))
    _api.store_cookies(res.headers)
    if res.status_code != 200:
        raise RuntimeError(f"Fetch {res.status_code}: {url}")
    return res.text


async def _api_request(method, url, headers=None, json_body=None, timeout=_api.FETCH_TIMEOUT):
    merged = _api.browser_headers(headers or {})
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        if method == "POST":
            res = await client.post(url, headers=merged, json=json_body)
        else:
            res = await client.get(url, headers=merged)
    _api.store_cookies(res.headers)
    return res


async def _raw_get(url, headers=None, timeout=_api.EXTRACT_TIMEOUT):
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        res = await client.get(url, headers=headers or {})
    _api.store_cookies(res.headers)
    return res


async def _raw_post(url, payload, headers=None, timeout=_api.EXTRACT_TIMEOUT):
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        res = await client.post(url, headers=headers or {}, json=payload)
    _api.store_cookies(res.headers)
    return res
