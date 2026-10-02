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


def eval_episode_query_chunk(chunk: str):
    operation = (r"\bepisode\s*\(\s*showId\s*:\s*\$showId\s*translationType"
                 r"\s*:\s*\$translationType\s*episodeString\s*:\s*\$episodeString\s*\)")
    for match in re.finditer(operation, chunk or ""):
        statement = _api.declaration_statement_at(chunk, match.start())
        if not statement:
            continue
        candidate = next((e for e in statement["entries"]
                          if re.search(operation, e["expression"])), None)
        if not candidate:
            continue
        defs = {}
        resolving = set()

        def resolve(name: str, before: int) -> None:
            if name in defs or name in resolving:
                return
            entry = _api.template_declaration(chunk, name, before)
            if not entry:
                return
            resolving.add(name)
            for dep in _api.template_dependencies(entry["expression"]):
                resolve(dep, entry["start"])
            resolving.discard(name)
            defs[name] = entry["expression"]

        resolve(candidate["name"], candidate["start"] + 1)
        try:
            query = _api._resolve_def(candidate["name"], defs, set())
            if _api.valid_episode_query(query):
                return query
        except Exception:
            pass
    return None


def _extract_mask_array(text: str):
    found = None
    for m in re.finditer(r'''\[((?:\s*"[A-Za-z0-9+/=]{8,}"\s*,?)+)\s*\]''', text or ""):
        strings = [s[1:-1] for s in re.findall(r'''"[A-Za-z0-9+/=]{8,}"''', m.group(1))]
        if len(strings) >= 4:
            found = strings[:4]
    return found


def _extract_build_id(text: str):
    m = re.search(r'''\?"([0-9]+)"\s*:\s*""''', text or "")
    return m.group(1) if m else None


def eval_fragment_crypto_chunk(chunk: str):
    for match in re.finditer(r"\bsaltMul\s*:", chunk or ""):
        window = chunk[max(0, match.start() - 4000):match.start() + 4000]
        nums = {}
        ok = True
        for key in ("saltMul", "saltAdd", "fragMul", "fragAdd"):
            m = re.search(r"\b" + key + r"\s*:\s*(-?[0-9]+(?:\.[0-9]+)?)", window)
            if not m:
                ok = False
                break
            try:
                nums[key] = float(m.group(1))
            except ValueError:
                ok = False
                break
        if not ok:
            continue
        if any(v != v or v in (float("inf"), float("-inf")) for v in nums.values()):
            continue
        boot = re.search(r'''\bbootPrefix\s*:\s*"([^"]*)"''', window)
        join = re.search(r'''\bjoin\s*:\s*"([^"]*)"''', window)
        parts_m = re.search(r"\bparts\s*:\s*\[([^\]]*)\]", window)
        if not boot or not join or not parts_m:
            continue
        parts = re.findall(r'''"([^"]+)"''', parts_m.group(1))
        if not parts:
            continue
        mask = _api._extract_mask_array(chunk[:match.start()])
        if not mask:
            continue
        build_id = _api._extract_build_id(chunk[:match.start()]) or _api._extract_build_id(window)
        if not build_id:
            continue
        omit = bool(re.search(r"\bomitEmptyLane\s*:\s*(!0|true)", window))
        return {"scheme": "fragments", "buildId": str(build_id),
                "maskParts": [str(p) for p in mask],
                "saltMul": nums["saltMul"], "saltAdd": nums["saltAdd"],
                "fragMul": nums["fragMul"], "fragAdd": nums["fragAdd"],
                "bootPrefix": boot.group(1), "join": join.group(1),
                "parts": [str(p) for p in parts], "omitEmptyLane": omit}
    return None


def _eval_legacy_shape(chunk: str):
    m = re.search(r'''const\s+''' + _api.IDENT + r'''\s*=[^;]{0,220}?"([0-9]+)"\s*:\s*"",\s*'''
                  r'''(''' + _api.IDENT + r''')=\[((?:"[^"]*",?\s*)+)\]''', chunk or "", re.DOTALL)
    if not m:
        return None
    strings = re.findall(r'''"([^"]*)"''', m.group(3))
    return _api.normalize_crypto_config({"buildId": m.group(1), "maskParts": strings})


def eval_old_crypto_chunk(chunk: str):
    m = re.search(r'''const\s+''' + _api.IDENT + r'''\s*=[^;]{0,180}?"\d+":""''', chunk or "")
    if not m:
        return None
    return _api._eval_legacy_shape(chunk[m.start():m.start() + 20000])


def eval_modern_crypto_chunk(chunk: str):
    m = re.search(r'''const\s+''' + _api.IDENT + r'''\s*=[^;]{0,220}?"\d+":""''', chunk or "")
    if not m:
        return None
    return _api._eval_legacy_shape(chunk[m.start():m.start() + 20000])
