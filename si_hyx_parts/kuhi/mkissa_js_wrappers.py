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


def _parse_map_literal(body: str) -> dict:
    out = {}
    for part in _api._split_top(body):
        m = re.match(r"\s*([A-Za-z_$][\w$]*)\s*:\s*(.+?)\s*$", part, re.DOTALL)
        if not m:
            continue
        try:
            out[m.group(1)] = _api._js_eval_str(m.group(2), {})
        except Exception:
            continue
    return out


def _rotate_live_table(chunk, tbl_name, ua_name, ua_off, header, check_src, target_src):
    tm = re.search(r"function\s+" + re.escape(tbl_name) + r"\(\)\s*\{\s*const\s+e\s*=\s*\[", chunk)
    if not tm:
        return None
    arr_end = _api._scan_balanced(chunk, tm.end() - 1)
    table = _api._parse_js_array_literal(chunk[tm.end() - 1:arr_end])
    if not table or not all(isinstance(s, str) for s in table):
        return None
    live = list(table)

    def _ua(idx):
        i = int(idx) - ua_off
        if i < 0 or i >= len(live):
            raise IndexError("table miss")
        return live[i]

    maps: dict = {}
    for mm in re.finditer(r"(?:^|[,;{\s]|(?:const|let|var)\s+)([a-zA-Z])\s*=\s*\{([^}]*)\}", header):
        parsed = _api._parse_map_literal(mm.group(2))
        if parsed:
            maps[mm.group(1)] = parsed
    inner: dict = {}
    for im in re.finditer(
            r"function\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)\s*\{\s*return\s+" + re.escape(ua_name) + r"\(([^;]+?)\)",
            header):
        fname, pnames, body = im.group(1), im.group(2), im.group(3)
        if fname == ua_name:
            continue
        params = tuple(p.strip() for p in pnames.split(",") if p.strip())

        def _fn(*args, _b=body, _p=params):
            local = dict(zip(_p, args))
            local.update(maps)
            local["__calls__"] = {ua_name: _ua}
            return _ua(_api._js_eval_str(_b, local))

        inner[fname] = _fn
    try:
        target = _api._js_eval_str(target_src, {})
        check_node = _api._JsParser(_api._tok_js(check_src)).parse()
    except Exception:
        return None

    def _run_check():
        env = dict(inner)
        env["__calls__"] = dict(inner)
        env.update(maps)
        return _api._js_eval(check_node, env)

    for _ in range(30000):
        try:
            if _run_check() == target:
                break
        except Exception:
            pass
        live.append(live.pop(0))
    else:
        return None
    return {"live": live, "ua": _ua, "maps": maps}


def _emulate_wrappers(chunk):
    _nm = r"[A-Za-z_$][\w$]*"
    ua_pat = (r"function\s+(" + _nm + r")\s*\(\s*e\s*,\s*t\s*\)\s*\{\s*return\s+e\s*=\s*e\s*-\s*(\d+)"
                r"\s*,\s*(" + _nm + r")\(\)\[e\]")
    iife_end = re.compile(
        r"===t\)break;(a|n)\.push\(\1\.shift\(\)\)\}catch\{\1\.push\(\1\.shift\(\)\)\}\}\)\("
        r"(" + _nm + r")\s*,\s*([^;]{1,400})\);"
    )
    blocks = []
    for fm in re.finditer(r"for\(;;\)try\{if\(", chunk or ""):
        p = fm.end()
        q = chunk.find("===t)break;", p)
        if q == -1 or q - p < 10 or q - p > 4000:
            continue
        check_src = chunk[p:q]
        if "for(;;)" in check_src:
            continue
        em = iife_end.match(chunk, q)
        if not em:
            continue
        arrvar, tbl, target_src = em.group(1), em.group(2), em.group(3)
        anchor = chunk.rfind(arrvar + "=e();", 0, fm.start())
        if anchor == -1:
            anchor = chunk.rfind(arrvar + " = e();", 0, fm.start())
        if anchor == -1:
            continue
        iife_start = chunk.rfind("(function(", 0, anchor)
        header = chunk[iife_start:fm.start()] if iife_start != -1 else ""
        if (arrvar + "=e();") not in header and (arrvar + " = e();") not in header:
            continue
        blocks.append({"table": tbl, "check": check_src,
                       "target": target_src, "header": header})
    direct: dict = {}
    for um in re.finditer(ua_pat, chunk or ""):
        direct.setdefault(um.group(1), (int(um.group(2)), um.group(3)))
    runtimes: dict = {}
    maps_variants: list = [{}]
    for tbl in {b["table"] for b in blocks} | {t for _, t in direct.values()}:
        specs = [b for b in blocks if b["table"] == tbl]
        uas = [(n, o) for n, (o, t) in direct.items() if t == tbl]
        if not specs:
            for (n, o) in uas:
                tm = re.search(r"function\s+" + re.escape(tbl) + r"\(\)\s*\{\s*const\s+e\s*=\s*\[", chunk)
                if not tm:
                    continue
                try:
                    arr_end = _api._scan_balanced(chunk, tm.end() - 1)
                    table = _api._parse_js_array_literal(chunk[tm.end() - 1:arr_end])
                except Exception:
                    continue
                if not table:
                    continue
                live = list(table)

                def _ua(idx, _live=live, _off=o):
                    i = int(idx) - _off
                    if i < 0 or i >= len(_live):
                        raise IndexError("table miss")
                    return _live[i]

                runtimes[n] = _ua
            continue
        done = False
        for spec in specs:
            for (n, o) in uas:
                try:
                    rt = _api._rotate_live_table(chunk, tbl, n, o, spec["header"], spec["check"], spec["target"])
                except Exception:
                    continue
                if not rt:
                    continue
                runtimes[n] = rt["ua"]
                if rt["maps"]:
                    maps_variants.append(rt["maps"])
                done = True
                break
            if done:
                break
    wrappers: dict = dict(runtimes)
    pending = {}
    _nm2 = r"[A-Za-z_$][\w$]*"
    for wm in re.finditer(
            r"function\s+(" + _nm2 + r")\s*\(([^)]*)\)\s*\{\s*return\s+(" + _nm2 + r")\(([^;]+?)\)",
            chunk or ""):
        fname, pnames, acc, body = wm.group(1), wm.group(2), wm.group(3), wm.group(4)
        if fname in wrappers:
            continue
        params = tuple(p.strip() for p in pnames.split(",") if p.strip())
        if not params:
            continue
        pending[fname] = (params, acc, body)

    for _ in range(12):
        progressed = False
        for wname, (params, acc, body) in list(pending.items()):
            if acc not in wrappers:
                continue

            def _mk(_b=body, _p=params, _a=acc):
                def _f(*args):
                    local = dict(zip(_p, args))
                    calls = dict(wrappers)
                    local["__calls__"] = calls
                    return calls[_a](_api._js_eval_str(_b, local))
                return _f

            wrappers[wname] = _mk()
            del pending[wname]
            progressed = True
        if not progressed:
            break
    return wrappers, maps_variants
