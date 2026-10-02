# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Decode Comix image transport (byte stream and 5x5 tiles).

Wire format reference: keiyoushi/extensions-source Comix Descrambler.kt.
Unknown formats are rejected, so a scrambled scene cannot enter a pack.
"""
import io
from PIL import Image


def _xorshift(state):
    state ^= (state << 13) & 0xFFFFFFFF
    state ^= state >> 17
    return (state ^ (state << 5)) & 0xFFFFFFFF


def _xor(data, seed, length, *, shift=False, high=False):
    out = bytearray(data)
    state = seed
    for index in range(min(len(out), length)):
        state = (_xorshift(state) if shift else
                 (state * 1000005 + 1234567891) & 0xFFFFFFFF)
        out[index] ^= (state >> 24) if high or not shift else (state & 255)
    return bytes(out)


def _is_image(data):
    return (data.startswith((b"\xff\xd8", b"\x89PNG")) or
            (data.startswith(b"RIFF") and data[8:12] == b"WEBP"))


def tile_order(seed, algo):
    order = list(range(25))
    state = seed | 1 if algo == "3" else seed
    for index in range(24, 0, -1):
        state = (_xorshift(state) if algo == "3" else
                 (state * 1664525 + 1013904223) & 0xFFFFFFFF)
        other = state % (index + 1)
        order[index], order[other] = order[other], order[index]
    inverse = [0] * 25
    for index, value in enumerate(order):
        inverse[value] = index
    return inverse


def decode_image(data, headers):
    meta = {str(key).lower(): str(value) for key, value in headers.items()}
    seed = int(meta.get("x-enc-seed", "0")) & 0xFFFFFFFF
    length = int(meta.get("x-enc-len", "0"))
    if seed and length:
        algo = meta.get("x-enc-algo", "1")
        if algo not in ("1", "2"):
            raise ValueError("Неизвестный формат байтов Comix.to")
        if algo == "2":
            candidates = [
                _xor(data, seed | 1, length, shift=True),
                _xor(data, seed, length, shift=True),
                _xor(data, seed | 1, length, shift=True, high=True),
                _xor(data, seed, length)]
            data = next((value for value in candidates if _is_image(value)), b"")
        else:
            data = _xor(data, seed, length)
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        output = image.copy()
        grid = meta.get("x-scramble-grid", "")
        seed = int(meta.get("x-scramble-seed", "0")) & 0xFFFFFFFF
        if grid:
            algo = meta.get("x-scramble-algo", "1")
            if grid != "5x5" or algo not in ("1", "2", "3") or not seed:
                raise ValueError("Неизвестный формат плиток Comix.to")
            raw_hash = meta.get("x-scramble-hash", "").strip()
            hashes = {"": 0, "03632": 58414, "02900": 117532}
            if raw_hash not in hashes:
                raise ValueError("Неизвестный ключ плиток Comix.to")
            order = tile_order(seed ^ hashes[raw_hash], algo)
            width, height = image.width // 5, image.height // 5
            for target, source in enumerate(order):
                left, top = source % 5 * width, source // 5 * height
                tile = image.crop((left, top, left + width, top + height))
                output.paste(tile, (target % 5 * width, target // 5 * height))
        stream = io.BytesIO()
        output.save(stream, "PNG")
        return stream.getvalue()
