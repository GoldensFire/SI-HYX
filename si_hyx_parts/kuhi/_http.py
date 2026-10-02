# Native Kuhi/anime-api, MIT, Copyright (c) 2026 aryaniiil. See LICENSE.
from si_hyx_parts.kuhi import _transport as httpx

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

HTML_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


async def fetch_text(url: str, headers: dict | None = None, timeout: float = 20.0) -> str:
    h = dict(HTML_HEADERS)
    if headers:
        h.update(headers)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        res = await client.get(url, headers=h)
    if res.status_code != 200:
        raise RuntimeError(f"HTTP {res.status_code} fetching {url}")
    return res.text


async def fetch_json(url: str, headers: dict | None = None, timeout: float = 20.0):
    h = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        h.update(headers)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        res = await client.get(url, headers=h)
    if res.status_code != 200:
        raise RuntimeError(f"HTTP {res.status_code} fetching {url}")
    return res.json()
