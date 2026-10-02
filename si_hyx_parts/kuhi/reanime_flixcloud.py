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


async def _extract_flixcloud(embed_html: str, referer: str | None = None) -> dict:
    data = _api._parse_js_literal(_api._extract_ssr_obj(embed_html))
    if not isinstance(data, dict):
        raise RuntimeError("SSR data is not an object")
    seed = data.get("obfuscation_seed")
    if not seed:
        raise RuntimeError("obfuscation_seed missing")
    fields = _api._derive_fields(seed)
    crypto_data = data.get("obfuscated_crypto_data")
    if not isinstance(crypto_data, dict):
        raise RuntimeError("obfuscated_crypto_data missing")
    container = crypto_data.get(fields["containerName"])
    if not isinstance(container, dict):
        raise RuntimeError("crypto container missing: " + fields["containerName"])
    array = container.get(fields["arrayName"])
    if not isinstance(array, list) or not array or not isinstance(array[0], dict):
        raise RuntimeError("crypto array missing: " + fields["arrayName"])
    obj = array[0].get(fields["objectName"])
    if not isinstance(obj, dict):
        raise RuntimeError("crypto object missing: " + fields["objectName"])
    fragment = _api._b64_to_bytes(obj.get(fields["keyField"]))
    iv = _api._b64_to_bytes(obj.get(fields["ivField"]))
    key_fragment = _api._b64_to_bytes(data.get(fields["keyFrag2Field"]))
    if not key_fragment:
        raise RuntimeError("key fragment missing: " + fields["keyFrag2Field"])
    token = data.get(fields["tokenField"])
    if not token:
        raise RuntimeError("token missing: " + fields["tokenField"])
    token_data = await fetch_json(
        _api.FLIX + "/api/m3u8/" + token, {"Referer": referer or (_api.BASE + "/")})
    if not isinstance(token_data, dict):
        raise RuntimeError("token API did not return an object")
    video_key = _api._sha256_hex(token + "vid")[:10]
    token_key = _api._sha256_hex(token + "key")[:10]
    video_bytes = _api._b64_to_bytes(token_data.get(video_key))
    token_bytes = _api._b64_to_bytes(token_data.get(token_key))
    if not video_bytes or not token_bytes:
        raise RuntimeError("token fields missing")
    try:
        seed_number = int(seed[:8], 16)
    except ValueError:
        raise RuntimeError("bad obfuscation_seed")
    wasm_payload = _api._b64_to_bytes(data.get("w_payload") or "")
    if not wasm_payload:
        raise RuntimeError("w_payload missing from embed data")
    wasm_out = _api._run_decrypt(wasm_payload, fragment, key_fragment, token_bytes, seed_number)
    material = hashlib.pbkdf2_hmac("sha256", wasm_out, seed.encode("utf-8"), 1000, 32)
    derived = bytes(b ^ (ord(seed[i % len(seed)]) & 255) for i, b in enumerate(material))
    aes_key = hashlib.sha256(derived).digest()
    plain = _api._aes256_cbc_decrypt(aes_key, bytes(iv), bytes(video_bytes))
    url = plain.decode("utf-8", "errors").strip().rstrip("\0")
    if not url.startswith("http"):
        raise RuntimeError(f"Unexpected decrypted value: {url[:60]}")
    return {
        "url": url,
        "subtitles": data.get("subtitles") or [],
        "thumbnails_vtt": data.get("thumbnails_vtt"),
        "video_title": data.get("video_title"),
        "intro_chapter": data.get("intro_chapter"),
        "outro_chapter": data.get("outro_chapter"),
        "video_id": data.get("video_id"),
    }


def _num_or_none(value):
    if isinstance(value, bool):
        return None
    return value if isinstance(value, (int, float)) else None
