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


def _rot_word(w: int) -> int:
    return ((w << 8) | (w >> 24)) & 0xFFFFFFFF


def _sub_word(w: int) -> int:
    return ((_api._SBOX[(w >> 24) & 0xFF] << 24) | (_api._SBOX[(w >> 16) & 0xFF] << 16)
            | (_api._SBOX[(w >> 8) & 0xFF] << 8) | _api._SBOX[w & 0xFF])


def _key_expansion(key: bytes) -> list:
    nk = len(key) // 4
    nr = nk + 6
    words = [int.from_bytes(key[4 * i:4 * i + 4], "big") for i in range(nk)]
    for i in range(nk, 4 * (nr + 1)):
        temp = words[i - 1]
        if i % nk == 0:
            temp = (_api._sub_word(_api._rot_word(temp)) ^ (_api._RCON[i // nk] << 24)) & 0xFFFFFFFF
        elif nk > 6 and i % nk == 4:
            temp = _api._sub_word(temp)
        words.append((words[i - nk] ^ temp) & 0xFFFFFFFF)
    blob = b"".join(w.to_bytes(4, "big") for w in words)
    return [blob[16 * r:16 * r + 16] for r in range(nr + 1)]


def _add_round_key(state: list, rk: bytes) -> None:
    for i in range(16):
        state[i] ^= rk[i]


def _aes_encrypt_block(block: bytes, round_keys: list) -> bytes:
    s = list(block)
    _api._add_round_key(s, round_keys[0])
    for rnd in range(1, len(round_keys) - 1):
        s = [_api._SBOX[b] for b in s]
        for r in range(1, 4):
            row = [s[r + 4 * c] for c in range(4)]
            for c in range(4):
                s[r + 4 * c] = row[(c + r) % 4]
        for c in range(4):
            a0, a1, a2, a3 = s[c * 4], s[c * 4 + 1], s[c * 4 + 2], s[c * 4 + 3]
            s[c * 4] = _api._gf_mul(a0, 2) ^ _api._gf_mul(a1, 3) ^ a2 ^ a3
            s[c * 4 + 1] = a0 ^ _api._gf_mul(a1, 2) ^ _api._gf_mul(a2, 3) ^ a3
            s[c * 4 + 2] = a0 ^ a1 ^ _api._gf_mul(a2, 2) ^ _api._gf_mul(a3, 3)
            s[c * 4 + 3] = _api._gf_mul(a0, 3) ^ a1 ^ a2 ^ _api._gf_mul(a3, 2)
        _api._add_round_key(s, round_keys[rnd])
    s = [_api._SBOX[b] for b in s]
    for r in range(1, 4):
        row = [s[r + 4 * c] for c in range(4)]
        for c in range(4):
            s[r + 4 * c] = row[(c + r) % 4]
    _api._add_round_key(s, round_keys[-1])
    return bytes(s)


def _aes_decrypt_block(block: bytes, round_keys: list) -> bytes:
    s = list(block)
    _api._add_round_key(s, round_keys[-1])
    for rnd in range(len(round_keys) - 2, 0, -1):
        for r in range(1, 4):
            row = [s[r + 4 * c] for c in range(4)]
            for c in range(4):
                s[r + 4 * c] = row[(c - r) % 4]
        s = [_api._INV_SBOX[b] for b in s]
        _api._add_round_key(s, round_keys[rnd])
        for c in range(4):
            a0, a1, a2, a3 = s[c * 4], s[c * 4 + 1], s[c * 4 + 2], s[c * 4 + 3]
            s[c * 4] = _api._gf_mul(a0, 14) ^ _api._gf_mul(a1, 11) ^ _api._gf_mul(a2, 13) ^ _api._gf_mul(a3, 9)
            s[c * 4 + 1] = _api._gf_mul(a0, 9) ^ _api._gf_mul(a1, 14) ^ _api._gf_mul(a2, 11) ^ _api._gf_mul(a3, 13)
            s[c * 4 + 2] = _api._gf_mul(a0, 13) ^ _api._gf_mul(a1, 9) ^ _api._gf_mul(a2, 14) ^ _api._gf_mul(a3, 11)
            s[c * 4 + 3] = _api._gf_mul(a0, 11) ^ _api._gf_mul(a1, 13) ^ _api._gf_mul(a2, 9) ^ _api._gf_mul(a3, 14)
    for r in range(1, 4):
        row = [s[r + 4 * c] for c in range(4)]
        for c in range(4):
            s[r + 4 * c] = row[(c - r) % 4]
    s = [_api._INV_SBOX[b] for b in s]
    _api._add_round_key(s, round_keys[0])
    return bytes(s)


def _gf128_mul(x: int, y: int) -> int:
    z = 0
    v = x
    for i in range(128):
        if (y >> (127 - i)) & 1:
            z ^= v
        lsb = v & 1
        v >>= 1
        if lsb:
            v ^= 0xE1000000000000000000000000000000
    return z


def _ghash(h: bytes, aad: bytes, ct: bytes) -> bytes:
    h_int = int.from_bytes(h, "big")
    data = aad + b"\x00" * ((-len(aad)) % 16) + ct + b"\x00" * ((-len(ct)) % 16)
    data += (len(aad) * 8).to_bytes(8, "big") + (len(ct) * 8).to_bytes(8, "big")
    y = 0
    for i in range(0, len(data), 16):
        y = _api._gf128_mul(y ^ int.from_bytes(data[i:i + 16], "big"), h_int)
    return y.to_bytes(16, "big")


def _gctr(key: bytes, icb: int, data: bytes) -> bytes:
    round_keys = _api._key_expansion(key)
    out = bytearray()
    counter = icb
    for i in range(0, len(data), 16):
        keystream = _api._aes_encrypt_block(counter.to_bytes(16, "big"), round_keys)
        block = data[i:i + 16]
        out.extend(bytes(b ^ k for b, k in zip(block, keystream)))
        counter = ((counter >> 32) << 32) | (((counter & 0xFFFFFFFF) + 1) & 0xFFFFFFFF)
    return bytes(out)


def aes_gcm_encrypt(key: bytes, iv: bytes, plaintext: bytes, aad: bytes = b"") -> tuple:
    h = _api._aes_encrypt_block(b"\x00" * 16, _api._key_expansion(key))
    j0 = int.from_bytes(iv + b"\x00\x00\x00\x01", "big")
    inc = ((j0 >> 32) << 32) | (((j0 & 0xFFFFFFFF) + 1) & 0xFFFFFFFF)
    ct = _api._gctr(key, inc, plaintext)
    s = _api._ghash(h, aad, ct)
    tag = bytes(a ^ b for a, b in zip(
        _aes_encrypt_block(j0.to_bytes(16, "big"), _key_expansion(key)), s))
    return ct, tag


def aes_gcm_decrypt(key: bytes, iv: bytes, ct: bytes, tag: bytes, aad: bytes = b"") -> bytes:
    h = _api._aes_encrypt_block(b"\x00" * 16, _api._key_expansion(key))
    j0 = int.from_bytes(iv + b"\x00\x00\x00\x01", "big")
    s = _api._ghash(h, aad, ct)
    expect = bytes(a ^ b for a, b in zip(
        _aes_encrypt_block(j0.to_bytes(16, "big"), _key_expansion(key)), s))
    if not hmac.compare_digest(expect, tag):
        raise ValueError("AES-GCM tag mismatch")
    inc = ((j0 >> 32) << 32) | (((j0 & 0xFFFFFFFF) + 1) & 0xFFFFFFFF)
    return _api._gctr(key, inc, ct)


def aes_cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    round_keys = _api._key_expansion(key)
    out = bytearray()
    prev = iv
    for i in range(0, len(data), 16):
        dec = _api._aes_decrypt_block(data[i:i + 16], round_keys)
        out.extend(bytes(b ^ p for b, p in zip(dec, prev)))
        prev = data[i:i + 16]
    return bytes(out)
