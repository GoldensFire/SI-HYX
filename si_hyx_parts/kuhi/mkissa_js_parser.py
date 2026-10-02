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


def _js_number(tok: str):
    tok = tok.strip()
    try:
        if tok[:2].lower() == "0x":
            return int(tok, 16)
        if "." in tok or "e" in tok.lower():
            return float(tok)
        return int(tok)
    except ValueError:
        raise ValueError("bad number: " + tok[:40])


def _js_parse_int(value) -> float:
    m = re.match(r"\s*[+-]?(?:0[xX][0-9a-fA-F]+|\d+)", str(value))
    if not m:
        return float("nan")
    tok = m.group(0).strip()
    neg = tok.startswith("-")
    tok = tok.lstrip("+-")
    try:
        num = int(tok, 16) if tok[:2].lower() == "0x" else int(tok)
    except ValueError:
        return float("nan")
    return -num if neg else num


def _tok_js(expr: str) -> list:
    toks, i, n = [], 0, len(expr)
    while i < n:
        ch = expr[i]
        if ch.isspace():
            i += 1
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and expr[i + 1].isdigit()):
            m = re.match(r"0[xX][0-9a-fA-F]+|\d+\.?\d*", expr[i:])
            toks.append(("num", m.group(0)))
            i += len(m.group(0))
            continue
        if ch in ("'", '"'):
            j = i + 1
            buf = []
            while j < n:
                c = expr[j]
                if c == "\\":
                    buf.append(expr[j:j + 2])
                    j += 2
                    continue
                if c == ch:
                    break
                buf.append(c)
                j += 1
            toks.append(("str", ch + "".join(buf) + ch))
            i = j + 1
            continue
        if ch.isalpha() or ch in ("_", "$"):
            m = re.match(r"[A-Za-z_$][\w$]*", expr[i:])
            name = m.group(0)
            i += len(name)
            while i < n and expr[i] == ".":
                m2 = re.match(r"\.[A-Za-z_$][\w$]*", expr[i:])
                if not m2:
                    break
                name += m2.group(0)
                i += len(m2.group(0))
            toks.append(("ident", name))
            continue
        if ch in "+-*/,(){}:." :
            toks.append(("op", ch))
            i += 1
            continue
        raise ValueError("bad char in expression: " + ch)
    return toks


class _JsParser:
    def __init__(self, toks):
        self.toks = toks
        self.pos = 0

    def peek(self):
        return self.toks[self.pos] if self.pos < len(self.toks) else (None, None)

    def next(self):
        t = self.peek()
        self.pos += 1
        return t

    def parse(self):
        node = self.parse_expr()
        if self.pos != len(self.toks):
            raise ValueError("trailing tokens")
        return node

    def parse_expr(self):
        node = self.parse_term()
        while self.peek() in (("op", "+"), ("op", "-")):
            op = self.next()[1]
            node = ("bin", op, node, self.parse_term())
        return node

    def parse_term(self):
        node = self.parse_factor()
        while self.peek() in (("op", "*"), ("op", "/")):
            op = self.next()[1]
            node = ("bin", op, node, self.parse_factor())
        return node

    def parse_factor(self):
        kind, val = self.peek()
        if (kind, val) in (("op", "-"), ("op", "+")):
            self.next()
            return ("un", val, self.parse_factor())
        node = self.parse_primary()
        while self.peek() == ("op", "."):
            self.next()
            k, v = self.next()
            if k != "ident" or "." in v:
                raise ValueError("bad member access")
            node = ("member", node, v)
        return node

    def parse_primary(self):
        kind, val = self.peek()
        if (kind, val) == ("op", "{"):
            self.next()
            pairs = []
            if self.peek() != ("op", "}"):
                while True:
                    k, v = self.next()
                    if k not in ("ident", "str", "num"):
                        raise ValueError("bad object key")
                    key = v[1:-1] if k == "str" else v
                    if self.next() != ("op", ":"):
                        raise ValueError("missing :")
                    pairs.append((key, self.parse_expr()))
                    if self.peek() == ("op", ","):
                        self.next()
                        continue
                    break
            if self.next() != ("op", "}"):
                raise ValueError("missing }")
            return ("obj", pairs)
        if (kind, val) == ("op", "("):
            self.next()
            node = self.parse_expr()
            if self.next() != ("op", ")"):
                raise ValueError("missing )")
            return node
        if kind == "num":
            self.next()
            return ("num", val)
        if kind == "str":
            self.next()
            return ("str", val)
        if kind == "ident":
            self.next()
            if self.peek() == ("op", "("):
                self.next()
                args = []
                if self.peek() != ("op", ")"):
                    args.append(self.parse_expr())
                    while self.peek() == ("op", ","):
                        self.next()
                        args.append(self.parse_expr())
                if self.next() != ("op", ")"):
                    raise ValueError("missing call )")
                return ("call", val, args)
            return ("var", val)
        raise ValueError("unexpected token")


def _js_eval(node, env):
    kind = node[0]
    if kind == "num":
        return _api._js_number(node[1])
    if kind == "str":
        return _api._unescape_js_string(node[1])
    if kind == "var":
        cur = env
        for part in node[1].split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                raise ValueError("unknown var: " + node[1])
        if callable(cur):
            raise ValueError("bare callable ref: " + node[1])
        return cur
    if kind == "obj":
        return {k: _api._js_eval(v, env) for k, v in node[1]}
    if kind == "member":
        obj = _api._js_eval(node[1], env)
        if isinstance(obj, dict) and node[2] in obj:
            return obj[node[2]]
        raise ValueError("bad member: " + node[2])
    if kind == "un":
        val = _api._js_eval(node[2], env)
        return -val if node[1] == "-" else val
    if kind == "bin":
        left = _api._js_eval(node[2], env)
        right = _api._js_eval(node[3], env)
        if node[1] == "+" and (isinstance(left, str) or isinstance(right, str)):
            return str(left) + str(right)
        return {"+": left + right, "-": left - right,
                "*": left * right, "/": left / right}[node[1]]
    if kind == "call":
        name, args = node[1], [_api._js_eval(a, env) for a in node[2]]
        if name == "parseInt":
            return _api._js_parse_int(args[0] if args else "")
        fns = env.get("__calls__", {})
        if name not in fns:
            raise ValueError("unknown call: " + name)
        return fns[name](*args)
    raise ValueError("bad node")


def _js_eval_str(expr: str, env: dict):
    return _api._js_eval(_api._JsParser(_api._tok_js(expr)).parse(), env)


def _scan_balanced(text: str, i: int) -> int:
    n = len(text)
    while i < n and text[i] not in "([{":
        i += 1
    stack = [text[i]]
    pairs = {")": "(", "]": "[", "}": "{"}
    i += 1
    in_str, quote, esc = False, "", False
    while i < n and stack:
        ch = text[i]
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
            stack.append(ch)
        elif ch in ")]}":
            if stack and stack[-1] == pairs[ch]:
                stack.pop()
            else:
                raise ValueError("unbalanced")
        i += 1
    return i


def _parse_js_array_literal(src: str, env: dict | None = None):
    src = src.strip()
    if not (src.startswith("[") and src.endswith("]")):
        raise ValueError("not an array")
    env = env if env is not None else {}
    return [_api._eval_js_value(p, env) for p in _api._split_top(src[1:-1]) if p.strip()]


def _eval_js_value(src: str, env: dict):
    src = src.strip()
    if src in ("!0", "true"):
        return True
    if src in ("!1", "false"):
        return False
    if src == "null":
        return None
    if src.startswith("["):
        return _api._parse_js_array_literal(src, env)
    if src.startswith("{"):
        if not src.endswith("}"):
            raise ValueError("bad object")
        out = {}
        for part in _api._split_top(src[1:-1]):
            if not part.strip():
                continue
            km = re.match(r"""\s*(?:"([^"]*)"|'([^']*)'|([A-Za-z_$][\w$]*))\s*:""", part)
            if not km:
                raise ValueError("bad object key")
            key = km.group(1) or km.group(2) or km.group(3)
            out[key] = _api._eval_js_value(part[km.end():], env)
        return out
    return _api._js_eval_str(src, env)
