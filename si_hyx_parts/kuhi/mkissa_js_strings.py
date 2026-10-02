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


def find_balanced_block(text: str, start: int) -> int:
    depth = 0
    seen = False
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
            seen = True
        elif ch == "}":
            depth -= 1
            if seen and depth == 0:
                return i + 1
    return -1


def normalize_crypto_config(out):
    if not out or not out.get("buildId"):
        return None
    parts = out.get("maskParts")
    if not isinstance(parts, list) or len(parts) < 4:
        return None
    return {"scheme": "legacy", "buildId": str(out["buildId"]),
            "maskParts": [str(p) for p in parts[:4]]}


def find_statement_end(text: str, start: int) -> int:
    parens = brackets = braces = 0
    quote_ch = ""
    i = start
    while i < len(text):
        ch = text[i]
        if quote_ch:
            if ch == "\\":
                i += 1
            elif ch == quote_ch:
                quote_ch = ""
        elif ch == '"' or ch == "'" or ch == chr(96):
            quote_ch = ch
        elif ch == "(":
            parens += 1
        elif ch == ")":
            parens -= 1
        elif ch == "[":
            brackets += 1
        elif ch == "]":
            brackets -= 1
        elif ch == "{":
            braces += 1
        elif ch == "}":
            braces -= 1
        elif ch == ";" and not parens and not brackets and not braces:
            return i
        i += 1
    return -1


def _split_top(text: str, sep: str = ",") -> list:
    out = []
    start = 0
    parens = brackets = braces = 0
    quote_ch = ""
    i = 0
    while i < len(text):
        ch = text[i]
        if quote_ch:
            if ch == "\\":
                i += 1
            elif ch == quote_ch:
                quote_ch = ""
        elif ch == '"' or ch == "'" or ch == chr(96):
            quote_ch = ch
        elif ch == "(":
            parens += 1
        elif ch == ")":
            parens -= 1
        elif ch == "[":
            brackets += 1
        elif ch == "]":
            brackets -= 1
        elif ch == "{":
            braces += 1
        elif ch == "}":
            braces -= 1
        elif ch == sep and not parens and not brackets and not braces:
            out.append(text[start:i])
            start = i + 1
        i += 1
    out.append(text[start:])
    return out


def split_top_level(text: str) -> list:
    return _api._split_top(text or "", ",")


def declaration_statement_at(text: str, index: int):
    start = max(text.rfind("const ", 0, index), text.rfind("let ", 0, index),
                text.rfind("var ", 0, index))
    if start < 0:
        return None
    end = _api.find_statement_end(text, start)
    if end < 0 or index > end:
        return None
    keyword = re.match(r"(?:const|let|var)\s+", text[start:])
    if not keyword:
        return None
    entries = []
    for value in _api.split_top_level(text[start + len(keyword.group(0)):end]):
        entry = re.match(r"^\s*(" + _api.IDENT + r")\s*=\s*([\s\S]+)$", value)
        if entry:
            entries.append({"name": entry.group(1), "expression": entry.group(2),
                            "start": start, "end": end})
    return {"start": start, "end": end, "entries": entries}


def template_dependencies(expression: str) -> list:
    return [m.group(1) for m in
            re.finditer(r"\$\{\s*(" + _api.IDENT + r")\b[^}]*\}", expression or "")]


def template_declaration(chunk: str, name: str, before=None):
    if before is None:
        before = len(chunk)
    pattern = re.compile(r"(?<![A-Za-z0-9_$])" + re.escape(name) + r"\s*=")
    fallback = None
    for match in pattern.finditer(chunk or ""):
        statement = _api.declaration_statement_at(chunk, match.start())
        if not statement:
            continue
        entry = next((e for e in statement["entries"] if e["name"] == name), None)
        if not entry:
            continue
        if fallback is None:
            fallback = entry
        if entry["start"] < before:
            fallback = entry
    return fallback


def valid_episode_query(query) -> bool:
    if not isinstance(query, str):
        return False
    if re.search("[\ud800-\udfff]", query):
        return False
    if "${" in query:
        return False
    if not re.search(r"\bquery\b", query):
        return False
    if not re.search(r"\bepisode\s*\(\s*showId\s*:\s*\$showId\s+translationType"
                     r"\s*:\s*\$translationType\s+episodeString\s*:\s*\$episodeString"
                     r"\s*\)", query):
        return False
    return True


def _unescape_js_string(token: str) -> str:
    if len(token) >= 2 and token[0] == "'" and token[-1] == "'":
        try:
            return json.loads(token)
        except Exception:
            pass
    body = token[1:-1] if len(token) >= 2 else token
    body = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), body)
    body = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), body)
    simple = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
    return re.sub(r"\\(.)", lambda m: simple.get(m.group(1), m.group(1)), body)


def _resolve_def(name: str, defs: dict, stack: set) -> str:
    if name in stack:
        raise ValueError("cyclic template ref: " + name)
    if name not in defs:
        raise ValueError("unknown template ref: " + name)
    stack.add(name)
    try:
        expr = (defs[name] or "").strip()
        m = (re.fullmatch(r"\(\s*\)\s*=>\s*([\s\S]+)", expr)
             or re.fullmatch(r"\(" + _api.IDENT + r"\s*\)\s*=>\s*([\s\S]+)", expr))
        if m:
            return _api._eval_str_expr(m.group(1), defs, stack)
        m = (re.fullmatch(r"\([^)]*\)\s*=>\s*\{\s*return\s+([\s\S]+?);?\s*\}", expr)
             or re.fullmatch(r"function\s*\([^)]*\)\s*\{\s*return\s+([\s\S]+?);?\s*\}", expr))
        if m:
            return _api._eval_str_expr(m.group(1), defs, stack)
        return _api._eval_str_expr(expr, defs, stack)
    finally:
        stack.discard(name)


def _eval_str_expr(expr: str, defs: dict, stack: set) -> str:
    e = (expr or "").strip()
    m = re.fullmatch(r"(" + _api.IDENT + r")\s*\(\s*\)", e)
    if m:
        return _api._resolve_def(m.group(1), defs, stack)
    if re.fullmatch(_api.IDENT, e):
        return _api._resolve_def(e, defs, stack)
    if len(e) >= 2 and e[0] in ('"', "'", chr(96)) and e[-1] == e[0]:
        if e[0] == chr(96):
            def _rep(mm):
                inner = (mm.group(1) or "").strip()
                im = (re.fullmatch(r"(" + _api.IDENT + r")\s*\(\s*\)", inner)
                      or re.fullmatch(_api.IDENT, inner))
                if not im:
                    raise ValueError("complex template expression")
                return _api._resolve_def(im.group(1), defs, stack)
            return re.sub(r"\$\{([^{}]*)\}", _rep, e[1:-1])
        return _api._unescape_js_string(e)
    parts = _api._split_top(e, "+")
    if len(parts) > 1:
        return "".join(_api._eval_str_expr(p, defs, stack) for p in parts)
    raise ValueError("cannot evaluate expression: " + e[:80])
