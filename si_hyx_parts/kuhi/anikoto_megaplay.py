# Native Kuhi/anime-api, MIT, Copyright (c) 2026 aryaniiil. See LICENSE.
import asyncio
import base64
import json
import re
from urllib.parse import quote, urljoin, urlparse
from si_hyx_parts.kuhi import _cache
from si_hyx_parts.kuhi._http import fetch_json, fetch_text
from si_hyx_parts.kuhi._match import (
    attr, build_titles, decode_entities, episode_meta, expected_count,
    find_top_slugs, get_prequel_offset, select_series, strip_tags,
)
from si_hyx_parts.kuhi._media import build_ctx

from . import anikoto as _api


def _xtime(a: int) -> int:
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else (a << 1) & 0xFF


def _gmul(a: int, b: int) -> int:
    p = 0
    while b:
        if b & 1:
            p ^= a
        a = _api._xtime(a)
        b >>= 1
    return p & 0xFF


def _rot_word(w: int) -> int:
    return ((w << 8) & 0xFFFFFFFF) | ((w >> 24) & 0xFF)


def _sub_word(w: int) -> int:
    return (
        (_api._SBOX[(w >> 24) & 0xFF] << 24)
        | (_api._SBOX[(w >> 16) & 0xFF] << 16)
        | (_api._SBOX[(w >> 8) & 0xFF] << 8)
        | _api._SBOX[w & 0xFF]
    )


def _expand_key_256(key: bytes) -> list:
    words = [int.from_bytes(key[4 * i:4 * i + 4], "big") for i in range(8)]
    for i in range(8, 60):
        temp = words[i - 1]
        if i % 8 == 0:
            temp = (_api._sub_word(_api._rot_word(temp)) ^ (_api._RCON[i // 8] << 24)) & 0xFFFFFFFF
        elif i % 8 == 4:
            temp = _api._sub_word(temp)
        words.append((words[i - 8] ^ temp) & 0xFFFFFFFF)
    rounds = []
    for r in range(15):
        rounds.append(b"".join(words[4 * r + k].to_bytes(4, "big") for k in range(4)))
    return rounds


def _add_round_key(state: list, round_key: bytes) -> list:
    return [b ^ round_key[i] for i, b in enumerate(state)]


def _inv_shift_rows(state: list) -> list:
    out = [0] * 16
    for row in range(4):
        for col in range(4):
            out[row + 4 * col] = state[row + 4 * ((col - row) % 4)]
    return out


def _inv_mix_columns(state: list) -> list:
    out = [0] * 16
    for col in range(4):
        t0, t1, t2, t3 = state[4 * col], state[4 * col + 1], state[4 * col + 2], state[4 * col + 3]
        out[4 * col] = _api._M14[t0] ^ _api._M11[t1] ^ _api._M13[t2] ^ _api._M9[t3]
        out[4 * col + 1] = _api._M9[t0] ^ _api._M14[t1] ^ _api._M11[t2] ^ _api._M13[t3]
        out[4 * col + 2] = _api._M13[t0] ^ _api._M9[t1] ^ _api._M14[t2] ^ _api._M11[t3]
        out[4 * col + 3] = _api._M11[t0] ^ _api._M13[t1] ^ _api._M9[t2] ^ _api._M14[t3]
    return out


def _decrypt_block(block: bytes, round_keys: list) -> bytes:
    state = _api._add_round_key(list(block), round_keys[14])
    for rnd in range(13, 0, -1):
        state = _api._inv_shift_rows(state)
        state = [_api._INV_SBOX[b] for b in state]
        state = _api._add_round_key(state, round_keys[rnd])
        state = _api._inv_mix_columns(state)
    state = _api._inv_shift_rows(state)
    state = [_api._INV_SBOX[b] for b in state]
    state = _api._add_round_key(state, round_keys[0])
    return bytes(state)


def _aes256_cbc_decrypt(key: bytes, iv: bytes, data: bytes):
    if len(key) != 32 or len(iv) != 16 or not data or len(data) % 16:
        raise ValueError("bad AES-256-CBC input lengths")
    round_keys = _api._expand_key_256(bytes(key))
    out = bytearray()
    prev = bytes(iv)
    for i in range(0, len(data), 16):
        block = bytes(data[i:i + 16])
        dec = _api._decrypt_block(block, round_keys)
        out += bytes(a ^ b for a, b in zip(dec, prev))
        prev = block
    pad = out[-1]
    if 1 <= pad <= 16 and all(b == pad for b in out[-pad:]):
        del out[-pad:]
    return bytes(out)


def _decode_script_string(value: str) -> str:
    def _rep(m):
        uni, hx, esc = m.group(1), m.group(2), m.group(3)
        if uni:
            return chr(int(uni, 16))
        if hx:
            return chr(int(hx, 16))
        return {"b": "\b", "n": "\n", "f": "\f", "r": "\r",
                "t": "\t", "v": "\v", "0": "\0"}.get(esc, esc)
    return re.sub(r"\\u([\dA-Fa-f]{4})|\\x([\dA-Fa-f]{2})|\\([\\'\"bnfrtv0])", _rep, value)


def _script_strings(script: str) -> list:
    strings = []
    i, n, prev = 0, len(script), ""
    while i < n:
        ch = script[i]
        nxt = script[i + 1] if i + 1 < n else ""
        if ch == "/" and nxt == "/":
            j = script.find("\n", i + 2)
            if j < 0:
                break
            i = j
            continue
        if ch == "/" and nxt == "*":
            j = script.find("*/", i + 2)
            if j < 0:
                break
            i = j + 2
            continue
        if ch == "/" and re.match(r"[=(:,[!&|?{};]", prev):
            i += 1
            in_class = False
            while i < n:
                if script[i] == "\\":
                    i += 2
                    continue
                if script[i] == "[":
                    in_class = True
                if script[i] == "]":
                    in_class = False
                if script[i] == "/" and not in_class:
                    i += 1
                    while i < n and re.match(r"[a-z]", script[i], re.IGNORECASE):
                        i += 1
                    break
                i += 1
            continue
        if ch in ("'", '"'):
            quote_char = ch
            val = ""
            i += 1
            while i < n and script[i] != quote_char:
                if script[i] == "\\" and i + 1 < n:
                    val += script[i]
                    i += 1
                val += script[i]
                i += 1
            strings.append(_api._decode_script_string(val))
            i += 1
            continue
        if ch == "`":
            i += 1
            while i < n and script[i] != "`":
                i += 2 if script[i] == "\\" else 1
            i += 1
            continue
        if not ch.isspace():
            prev = ch
        i += 1
    seen, out = set(), []
    for s in strings:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _megaplay_routes(script: str):
    routes = sorted(
        [s for s in _api._script_strings(script)
         if re.match(r"^stream/getSources[\w/-]*$", s, re.IGNORECASE)],
        key=len,
    )
    legacy = routes[0] if routes else None
    modern = next((r for r in routes if r != legacy and legacy and r.startswith(legacy)), None)
    return legacy, modern


def _megaplay_decrypt(value: str, script: str):
    if not value:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        encrypted = base64.urlsafe_b64decode(padded)
    except ValueError:
        return None
    if not encrypted or len(encrypted) % 16:
        return None
    values = [s for s in _api._script_strings(script) if 0 < len(s.encode("utf-8")) <= 32]
    ivs = [s for s in values if len(s.encode("utf-8")) == 16]
    for key_value in values:
        key = key_value.encode("utf-8")[:32].ljust(32, b"\0")
        for iv_value in ivs:
            try:
                raw = _api._aes256_cbc_decrypt(key, iv_value.encode("utf-8"), bytes(encrypted))
                data = json.loads(raw.decode("utf-8"))
            except Exception:
                continue
            source = (data.get("file") or data.get("url")) if isinstance(data, dict) else None
            if isinstance(source, str) and source:
                return source
    return None


def _build_source_url(origin: str, path: str, file_id: str) -> str:
    base = origin.rstrip("/") + "/"
    url = urljoin(base, path.lstrip("/"))
    sep = "&" if "?" in url else "?"

    return url + sep + "id=" + quote(file_id, safe="") + "&id=" + quote(file_id, safe="")


def _map_track(track: dict, source: str) -> dict:
    label = track.get("label") or ""
    lang_key = label.lower().split(" ")[0] if label else ""
    default = track.get("default")
    return {
        "url": track.get("file"),
        "label": label or "English",
        "srclang": _api.LANG_MAP.get(lang_key, "en"),
        "default": default if default is not None else False,
        "source": source,
    }


async def _extract_megaplay_details(embed_url: str):
    try:
        page = urlparse(str(embed_url))
        origin = page.scheme + "://" + page.netloc
        page_href = str(embed_url)
        html = await fetch_text(page_href, {"Referer": origin + "/"})
        m = re.search(r"data-id=[\"']([^\"']+)[\"']", html, re.IGNORECASE)
        if not m:
            return None
        file_id = m.group(1)
        script_urls = []
        for sm in re.finditer(r"<script[^>]+src=[\"']([^\"']+)[\"']", html, re.IGNORECASE):
            src = decode_entities(sm.group(1))
            if src.startswith("//"):
                script_urls.append(page.scheme + ":" + src)
            elif re.match(r"^https?://", src, re.IGNORECASE):
                script_urls.append(src)
            else:
                script_urls.append(urljoin(origin + "/", src))

        async def _one(u):
            try:
                return await fetch_text(u, {"Referer": page_href})
            except Exception:
                return None

        scripts = await asyncio.gather(*[_one(u) for u in script_urls]) if script_urls else []
        script = next(
            (s for s in scripts
             if s and re.search(r"getSources", s, re.IGNORECASE) and re.search(r"AES-CBC", s)),
            None,
        )
        if not script:
            return None
        legacy, modern = _api._megaplay_routes(script)
        if not legacy and not modern:
            return None
        headers = {"Referer": page_href, "X-Requested-With": "XMLHttpRequest"}

        async def _js(url):
            if not url:
                return None
            try:
                return await fetch_json(url, headers)
            except Exception:
                return None

        modern_data, legacy_data = await asyncio.gather(
            _js(_api._build_source_url(origin, modern, file_id) if modern else None),
            _js(_api._build_source_url(origin, legacy, file_id) if legacy else None),
        )
        legacy_url = None
        if isinstance(legacy_data, dict):
            legacy_url = ((legacy_data.get("sources") or {}).get("file")
                          or _api._megaplay_decrypt(legacy_data.get("enc"), script))
        sources, seen_urls = [], set()
        modern_url = ((modern_data.get("sources") or {}).get("file")
                      if isinstance(modern_data, dict) else None)
        for url, variant in ((modern_url, "modern"), (legacy_url, "legacy")):
            if url and url not in seen_urls:
                seen_urls.add(url)
                sources.append({"url": url, "variant": variant})
        if not sources:
            return None
        metadata = modern_data if isinstance(modern_data, dict) else (
            legacy_data if isinstance(legacy_data, dict) else {})
        tracks = metadata.get("tracks") if isinstance(metadata.get("tracks"), list) else []
        return {
            "origin": origin,
            "sources": sources,
            "tracks": tracks,
            "intro": metadata.get("intro"),
            "outro": metadata.get("outro"),
        }
    except Exception:
        return None
