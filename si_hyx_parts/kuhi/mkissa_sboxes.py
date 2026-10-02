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


def _gf_mul(a: int, b: int) -> int:
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        hi = a & 0x80
        a = (a << 1) & 0xFF
        if hi:
            a ^= 0x1B
        b >>= 1
    return p


def _gf_pow(a: int, e: int) -> int:
    r = 1
    while e:
        if e & 1:
            r = _api._gf_mul(r, a)
        a = _api._gf_mul(a, a)
        e >>= 1
    return r


def _build_sboxes():
    sbox = [0] * 256
    inv = [0] * 256
    for a in range(256):
        ia = 0 if a == 0 else _api._gf_pow(a, 254)
        y = 0
        for i in range(8):
            bit = (((ia >> i) & 1) ^ ((ia >> ((i + 4) % 8)) & 1)
                   ^ ((ia >> ((i + 5) % 8)) & 1) ^ ((ia >> ((i + 6) % 8)) & 1)
                   ^ ((ia >> ((i + 7) % 8)) & 1) ^ ((0x63 >> i) & 1))
            y |= bit << i
        sbox[a] = y
        inv[y] = a
    return sbox, inv
