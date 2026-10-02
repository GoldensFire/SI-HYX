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


def _emulated_fragment_config(chunk: str):
    try:
        wrappers, maps_variants = _api._emulate_wrappers(chunk)
    except Exception:
        return None
    if not wrappers:
        return None

    def _stmt_at(pos):
        cstart = chunk.rfind("const ", 0, pos)
        if cstart == -1:
            cstart = chunk.rfind("let ", 0, pos)
        if cstart == -1:
            cstart = chunk.rfind("var ", 0, pos)
        if cstart == -1:
            return None
        semi, depth = cstart, 0
        in_str, quote, esc = False, "", False
        n = len(chunk)
        while semi < n:
            ch = chunk[semi]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == quote:
                    in_str = False
            elif ch in ("'", '"'):
                in_str, quote = True, ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif ch == ";" and depth == 0:
                break
            semi += 1
        decls = []
        for part in _api._split_top(chunk[cstart + 6:semi]):
            dm = re.match(r"\s*([A-Za-z_$][\w$]*)\s*=\s*([\s\S]+)$", part)
            if dm:
                decls.append((dm.group(1), dm.group(2).strip()))
        return decls

    statements = []
    for sm in re.finditer(r"\bsaltMul\s*:", chunk):
        decls = _stmt_at(sm.start())
        if not decls:
            continue
        cfg_idx = next((i for i, (_, e) in enumerate(decls)
                        if e.startswith("{") and "saltMul" in e and "fragMul" in e), None)
        if cfg_idx is None or cfg_idx < 1:
            continue
        mask_idx = next((i for i in range(cfg_idx - 1, -1, -1)
                         if decls[i][1].startswith("[")), None)
        if mask_idx is None:
            continue
        statements.append((decls[mask_idx][1], decls[cfg_idx][1]))
    for maps in maps_variants:
        calls = dict(wrappers)

        def _venv(_m=maps, _c=calls):
            env = dict(_m)
            env["__calls__"] = dict(_c)
            return env

        for mask_src, cfg_src in statements:
            try:
                mv = _api._eval_js_value(mask_src, _venv())
                cv = _api._eval_js_value(cfg_src, _venv())
            except Exception:
                continue
            if (isinstance(mv, list) and len(mv) >= 4
                    and isinstance(cv, dict)
                    and all(isinstance(cv.get(k), (int, float))
                            for k in ("saltMul", "saltAdd", "fragMul", "fragAdd"))
                    and isinstance(cv.get("parts"), list) and cv["parts"]
                    and isinstance(cv.get("bootPrefix"), str)
                    and isinstance(cv.get("join"), str)):
                try:
                    for p in mv[:4]:
                        if len(base64.b64decode(str(p))) < 8:
                            raise ValueError("short mask")
                except Exception:
                    continue
            else:
                continue
            build_id = None
            bm = re.search(r'\?"(\d+)":""', chunk)
            if bm:
                build_id = bm.group(1)
            if not build_id:
                names: list = []
                for m3 in re.finditer(r"buildId\s*:\s*\w+\s*=\s*([A-Za-z_$][\w$]*)", chunk):
                    names.append(m3.group(1))
                for m3 in re.finditer(r"buildId\s*:\s*([A-Za-z_$][\w$]*)\|\|", chunk):
                    names.append(m3.group(1))
                names += ["sd", "Fr"]
                seen = set()
                for var in names:
                    if var in seen:
                        continue
                    seen.add(var)
                    m4 = re.search(r"(?<![\w$])" + re.escape(var) + r"\s*=\s*([A-Za-z_$][\w$]*\([^()]*\))", chunk)
                    if not m4:
                        continue
                    try:
                        bid = _api._js_eval_str(m4.group(1), _venv())
                        if bid:
                            build_id = str(bid)
                            break
                    except Exception:
                        continue
            if not build_id:
                continue
            return {
                "scheme": "fragments",
                "buildId": build_id,
                "maskParts": [str(p) for p in mv[:4]],
                "saltMul": cv["saltMul"],
                "saltAdd": cv["saltAdd"],
                "fragMul": cv["fragMul"],
                "fragAdd": cv["fragAdd"],
                "bootPrefix": cv["bootPrefix"],
                "join": cv["join"],
                "parts": [str(p) for p in cv["parts"]],
                "omitEmptyLane": bool(cv.get("omitEmptyLane")),
            }
    return None


def eval_crypto_chunk(chunk: str):
    try:
        config = _api._emulated_fragment_config(chunk)
        if config:
            return config
    except Exception as e:
        print(f"[mkissa] emulated discovery failed: {str(e)[:150]}")
    try:
        config = _api.eval_fragment_crypto_chunk(chunk)
        if config:
            return config
    except Exception:
        pass
    try:
        found = _api.eval_modern_crypto_chunk(chunk)
        if found:
            return found
    except Exception:
        pass
    try:
        return _api.eval_old_crypto_chunk(chunk)
    except Exception:
        return None
