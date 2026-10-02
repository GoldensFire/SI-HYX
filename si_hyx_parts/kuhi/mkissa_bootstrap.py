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


def build_mask_seed(build_id: str) -> bytes:
    name = str(build_id or "")
    out = bytearray(32)
    for i in range(32):
        code = ord(name[i % len(name)]) if name else 0
        out[i] = (code ^ ((i * 17 + 31) & 255)) & 255
    return bytes(out)


def build_mask(config: dict) -> bytes:
    build_id = str(config.get("buildId") or "")
    mask_parts = config.get("maskParts") or []
    if config.get("scheme") == "fragments":
        salt_mul = config.get("saltMul", 0)
        salt_add = config.get("saltAdd", 0)
        frag_mul = config.get("fragMul", 0)
        frag_add = config.get("fragAdd", 0)
        salt = bytearray(32)
        for i in range(32):
            code = ord(build_id[i % len(build_id)]) if build_id else 0
            salt[i] = (code ^ (int(i * salt_mul + salt_add) & 255)) & 255
        out = bytearray(32)
        for i in range(min(4, len(mask_parts))):
            part = base64.b64decode(str(mask_parts[i]))
            offset = i * 8
            for j in range(8):
                out[offset + j] = (part[j] ^ salt[offset + j]
                                   ^ (int(i * frag_mul + j * frag_add) & 255)) & 255
        return bytes(out)
    seed = _api.build_mask_seed(build_id)
    out = bytearray(32)
    for i in range(min(4, len(mask_parts))):
        part = base64.b64decode(str(mask_parts[i]))
        offset = i * 8
        for j in range(8):
            out[offset + j] = ((part[j] ^ seed[offset + j])
                               ^ ((i * 41 + j * 7) & 255)) & 255
    return bytes(out)


def current_epochs(now_ms=None) -> list:
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    epoch = now // _api.BOOT_EPOCH_MS
    prev = epoch - 1 if (now - epoch * _api.BOOT_EPOCH_MS < _api.BOOT_GRACE_MS and epoch > 0) else epoch
    return list(dict.fromkeys([prev, epoch]))


def make_boot_token(config: dict, epoch, lane: str = _api.CONTENT_LANE) -> str:
    mask = _api.build_mask(config)
    prefix = config.get("bootPrefix") or "aa-boot:"
    bid = str(config.get("buildId"))
    boot_key = _api.hmac_bytes(mask, f"{prefix}{bid}")
    if config.get("scheme") != "fragments":
        return _api.hmac_bytes(boot_key, f"{bid}:{_api.KEY_GROUP}:{_api.REFERER_HOST}:{epoch}:{lane}").hex()
    fields = {"buildId": bid, "group": _api.KEY_GROUP,
              "host": _api.REFERER_HOST, "epoch": str(epoch), "lane": str(lane or "")}
    parts = list(config.get("parts") or [])
    if config.get("omitEmptyLane") and not fields["lane"]:
        parts = [p for p in parts if p != "lane"]
    joiner = str(config.get("join", ""))
    return _api.hmac_bytes(boot_key, joiner.join(fields.get(p, "") for p in parts)).hex()


def is_unknown_build_id(raw: str) -> bool:
    try:
        if json.loads(raw or "").get("error") == "unknown_build_id":
            return True
    except Exception:
        pass
    return bool(re.search(r"unknown_build_id", raw or "", re.IGNORECASE))


async def fetch_bootstrap(lane: str = _api.CONTENT_LANE, force: bool = False) -> dict:
    global _crypto_config, _episode_query_cache
    last_error = None
    for refresh in range(2):
        config = await _api.discover_crypto_config(force or refresh > 0)
        retry_fresh = False
        for epoch in _api.current_epochs():
            res = await _api._api_request(
                "GET",
                f"{_api.API}/client-crypto/v1/bootstrap?buildId={quote(str(config['buildId']), safe="'")}"
                f"&k={quote(str(lane), safe="'")}",
                {"Referer": f"{_api.REFERER}/", "Origin": _api.REFERER,
                 "x-build-id": config["buildId"],
                 "x-aa-boot": _api.make_boot_token(config, epoch, lane)})
            raw = res.text
            if res.status_code != 200:
                last_error = RuntimeError(f"Bootstrap {res.status_code}: {raw[:180]}")
                if _api.is_unknown_build_id(raw):
                    _api._crypto_config = None
                    _api._episode_query_cache = None
                    retry_fresh = True
                    break
                continue
            try:
                data = json.loads(raw)
            except Exception:
                last_error = RuntimeError("Bootstrap invalid JSON")
                continue
            if not data.get("partB"):
                last_error = RuntimeError("Bootstrap missing partB")
                continue
            return {**data, **config, "lane": lane, "buildId": config["buildId"]}
        if not retry_fresh:
            break
    raise last_error or RuntimeError("MKissa bootstrap failed")


def derive_lane_key(part_b: str, config: dict) -> bytes:
    encrypted = base64.b64decode(part_b)
    mask = _api.build_mask(config)
    key = bytearray(32)
    for i in range(32):
        key[i] = encrypted[i] ^ mask[i % len(mask)]
    return bytes(key)


async def get_lane_key(lane: str = _api.CONTENT_LANE, force: bool = False) -> dict:
    boot = await _api.fetch_bootstrap(lane, force)
    return {"key": _api.derive_lane_key(boot["partB"], boot),
            "epoch": boot.get("epoch"), "buildId": boot.get("buildId")}
