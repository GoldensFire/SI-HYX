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


def _extract_ssr_obj(html: str) -> str:
    m = re.search(r'\{type:"data",data:(\{)', html)
    if not m:
        raise RuntimeError("SSR data block not found")
    start = m.start(1)
    depth = 0
    for i in range(start, len(html)):
        if html[i] == "{":
            depth += 1
        elif html[i] == "}":
            depth -= 1
            if depth == 0:
                return html[start:i + 1]
    raise RuntimeError("SSR brace matching failed")


def _parse_js_literal(source: str):
    idx = 0
    n = len(source)

    def _ws():
        nonlocal idx
        while idx < n and source[idx] in (" ", "\t", "\n", "\r", "\f", "\v"):
            idx += 1

    def _dq():
        nonlocal idx
        out = ""
        idx += 1
        while idx < n and source[idx] != '"':
            if source[idx] == "\\":
                idx += 1
                out += {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}.get(
                    source[idx], source[idx])
                idx += 1
            else:
                out += source[idx]
                idx += 1
        idx += 1
        return out

    def _sq():
        nonlocal idx
        out = ""
        idx += 1
        while idx < n and source[idx] != "'":
            if source[idx] == "\\":
                idx += 1
                if source[idx] == "'":
                    out += "'"
                else:
                    out += {"n": "\n", "t": "\t", "r": "\r", "\\": "\\"}.get(
                        source[idx], source[idx])
                idx += 1
            else:
                out += source[idx]
                idx += 1
        idx += 1
        return out

    def _key():
        nonlocal idx
        _ws()
        if idx < n and source[idx] == '"':
            return _dq()
        if idx < n and source[idx] == "'":
            return _sq()
        m = re.match(r"[a-zA-Z_$][a-zA-Z0-9_$]*", source[idx:])
        if not m:
            raise RuntimeError(f"Bad key at pos {idx}: {source[idx:idx + 20]}")
        idx += len(m.group(0))
        return m.group(0)

    def _obj():
        nonlocal idx
        out = {}
        idx += 1
        _ws()
        while idx < n and source[idx] != "}":
            if source[idx] == ",":
                idx += 1
                _ws()
                continue
            prop = _key()
            _ws()
            idx += 1
            out[prop] = _val()
            _ws()
        idx += 1
        return out

    def _arr():
        nonlocal idx
        out = []
        idx += 1
        _ws()
        while idx < n and source[idx] != "]":
            if source[idx] == ",":
                idx += 1
                _ws()
                continue
            out.append(_val())
            _ws()
        idx += 1
        return out

    def _val():
        nonlocal idx
        _ws()
        if idx >= n:
            raise RuntimeError("unexpected end of JS literal")
        ch = source[idx]
        if ch == "{":
            return _obj()
        if ch == "[":
            return _arr()
        if ch == '"':
            return _dq()
        if ch == "'":
            return _sq()
        for lit, val in (("true", True), ("false", False), ("null", None),
                         ("undefined", None), ("!0", True), ("!1", False)):
            if source.startswith(lit, idx):
                idx += len(lit)
                return val
        m = re.match(r"-?[\d.]+([eE][+-]?\d+)?", source[idx:])
        if m:
            idx += len(m.group(0))
            try:
                return float(m.group(0))
            except ValueError:
                raise RuntimeError(f"bad number at pos {idx}")
        raise RuntimeError(f"JS parse error at pos {idx}: ...{source[idx:idx + 20]}")

    return _val()


def _read_leb(buf, pos: int):
    value, shift = 0, 0
    while True:
        byte = buf[pos]
        pos += 1
        value |= (byte & 127) << shift
        shift += 7
        if not byte & 128:
            return value, pos


def _parse_wasm_decrypt(raw: bytes):
    data = bytes(raw)
    pos = 8
    while pos < len(data):
        section = data[pos]
        pos += 1
        size, pos = _api._read_leb(data, pos)
        if section == 10:
            pos += 1
            body_size, pos = _api._read_leb(data, pos)
            pos += body_size
            break
        pos += size
    func_size, pos = _api._read_leb(data, pos)
    body = data[pos:pos + func_size]
    xor_end = bytes([32, 2, 32, 5, 106, 45, 0, 0, 115, 33, 6])
    found = body.find(xor_end)
    if found < 0:
        raise RuntimeError("WASM: transform start not found")
    t_start = found + len(xor_end)
    t_end, step = -1, 36
    i = t_start
    while i < len(body) - 4:
        if body[i] == 32 and body[i + 1] == 5 and body[i + 2] == 65:
            val, nxt = _api._read_leb(body, i + 3)
            if nxt < len(body) and body[nxt] == 108:
                t_end, step = i, val
                break
        i += 1
    if t_end < 0:
        raise RuntimeError("WASM: keystream not found")
    code = body[t_start:t_end]

    def _transform(byte: int) -> int:
        local = byte & 255
        stack = []
        p = 0
        while p < len(code):
            op = code[p]
            p += 1
            if op == 32:
                li, p = _api._read_leb(code, p)
                stack.append(local if li == 6 else 0)
            elif op == 33:
                li, p = _api._read_leb(code, p)
                val = stack.pop()
                if li == 6:
                    local = val & 255
            elif op == 65:
                val, p = _api._read_leb(code, p)
                stack.append(val)
            elif op in (106, 107, 113, 114, 115, 116, 118):
                right = stack.pop()
                left = stack.pop()
                if op == 106:
                    stack.append((left + right) & 255)
                elif op == 107:
                    stack.append((left - right + 256) & 255)
                elif op == 113:
                    stack.append((left & right) & 255)
                elif op == 114:
                    stack.append((left | right) & 255)
                elif op == 115:
                    stack.append(left ^ (right & 255))
                elif op == 116:
                    stack.append((left << (right & 7)) & 255)
                elif op == 118:
                    stack.append((left >> (right & 7)) & 255)
        return local

    return step, _transform


def _run_decrypt(wasm_bytes: bytes, fragment: bytes, key_fragment: bytes,
                 token: bytes, seed_number: int) -> bytes:
    step, transform = _api._parse_wasm_decrypt(wasm_bytes)
    out = bytearray(len(fragment))
    for i in range(len(fragment)):
        value = (fragment[i] ^ key_fragment[i] ^ token[i]) & 255
        out[i] = (transform(value) ^ ((i * step + seed_number) & 255)) & 255
    return bytes(out)
