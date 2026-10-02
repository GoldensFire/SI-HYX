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


def _xtime(a: int) -> int:
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else (a << 1) & 0xFF


def _gmul(a: int, b: int) -> int:
    p = 0
    while b:
        if b & 1:
            p ^= a
        a = _api._xtime(a)
        b >>= 1
    return p & 0xFF


def _rot_word(w: int) -> int:
    return ((w << 8) & 0xFFFFFFFF) | ((w >> 24) & 0xFF)


def _sub_word(w: int) -> int:
    return (
        (_api._SBOX[(w >> 24) & 0xFF] << 24)
        | (_api._SBOX[(w >> 16) & 0xFF] << 16)
        | (_api._SBOX[(w >> 8) & 0xFF] << 8)
        | _api._SBOX[w & 0xFF]
    )


def _expand_key_256(key: bytes) -> list:
    words = [int.from_bytes(key[4 * i:4 * i + 4], "big") for i in range(8)]
    for i in range(8, 60):
        temp = words[i - 1]
        if i % 8 == 0:
            temp = (_api._sub_word(_api._rot_word(temp)) ^ (_api._RCON[i // 8] << 24)) & 0xFFFFFFFF
        elif i % 8 == 4:
            temp = _api._sub_word(temp)
        words.append((words[i - 8] ^ temp) & 0xFFFFFFFF)
    rounds = []
    for r in range(15):
        rounds.append(b"".join(words[4 * r + k].to_bytes(4, "big") for k in range(4)))
    return rounds


def _add_round_key(state: list, round_key: bytes) -> list:
    return [b ^ round_key[i] for i, b in enumerate(state)]


def _inv_shift_rows(state: list) -> list:
    out = [0] * 16
    for row in range(4):
        for col in range(4):
            out[row + 4 * col] = state[row + 4 * ((col - row) % 4)]
    return out


def _inv_mix_columns(state: list) -> list:
    out = [0] * 16
    for col in range(4):
        t0, t1, t2, t3 = state[4 * col], state[4 * col + 1], state[4 * col + 2], state[4 * col + 3]
        out[4 * col] = _api._M14[t0] ^ _api._M11[t1] ^ _api._M13[t2] ^ _api._M9[t3]
        out[4 * col + 1] = _api._M9[t0] ^ _api._M14[t1] ^ _api._M11[t2] ^ _api._M13[t3]
        out[4 * col + 2] = _api._M13[t0] ^ _api._M9[t1] ^ _api._M14[t2] ^ _api._M11[t3]
        out[4 * col + 3] = _api._M11[t0] ^ _api._M13[t1] ^ _api._M9[t2] ^ _api._M14[t3]
    return out


def _decrypt_block(block: bytes, round_keys: list) -> bytes:
    state = _api._add_round_key(list(block), round_keys[14])
    for rnd in range(13, 0, -1):
        state = _api._inv_shift_rows(state)
        state = [_api._INV_SBOX[b] for b in state]
        state = _api._add_round_key(state, round_keys[rnd])
        state = _api._inv_mix_columns(state)
    state = _api._inv_shift_rows(state)
    state = [_api._INV_SBOX[b] for b in state]
    state = _api._add_round_key(state, round_keys[0])
    return bytes(state)


def _aes256_cbc_decrypt(key: bytes, iv: bytes, data: bytes):
    if len(key) != 32 or len(iv) != 16 or not data or len(data) % 16:
        raise ValueError("bad AES-256-CBC input lengths")
    round_keys = _api._expand_key_256(bytes(key))
    out = bytearray()
    prev = bytes(iv)
    for i in range(0, len(data), 16):
        block = bytes(data[i:i + 16])
        dec = _api._decrypt_block(block, round_keys)
        out += bytes(a ^ b for a, b in zip(dec, prev))
        prev = block
    pad = out[-1]
    if 1 <= pad <= 16 and all(b == pad for b in out[-pad:]):
        del out[-pad:]
    return bytes(out)


def _sha256_hex(value) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(bytes(value)).hexdigest()


def _b64_to_bytes(value) -> bytes:
    if not value:
        return b""
    if not isinstance(value, str):
        raise RuntimeError("expected base64 string")
    try:
        return base64.b64decode(value + "=" * (-len(value) % 4))
    except ValueError as e:
        raise RuntimeError(f"bad base64 payload: {e}")


def _derive_fields(seed: str) -> dict:
    first = seed
    for i in range(3):
        first = _api._sha256_hex(first + str(i))
    second = first
    for i in range(3):
        second = _api._sha256_hex(second + str(i))
    return {
        "keyField": "kf_" + first[8:16],
        "ivField": "ivf_" + first[16:24],
        "containerName": "cd_" + first[24:32],
        "arrayName": "ad_" + first[32:40],
        "objectName": "od_" + first[40:48],
        "tokenField": first[48:64] + "_" + first[56:64],
        "keyFrag2Field": second[0:16] + "_" + second[16:24],
    }
