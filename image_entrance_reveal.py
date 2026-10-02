# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Раскрытие маской, копиями и фрагментами."""
from __future__ import annotations

import math
import random
import numpy as np
from PIL import Image, ImageDraw

from image_entrance_motion import affine, fade


def pieces(image, effect, p, strength, seed):
    canvas = Image.new("RGB", image.size)
    rng = random.Random(seed)
    columns, rows = 8, 6
    for row in range(rows):
        for col in range(columns):
            x0, x1 = col * image.width // columns, (col + 1) * image.width // columns
            y0, y1 = row * image.height // rows, (row + 1) * image.height // rows
            tile = image.crop((x0, y0, x1, y1))
            delay, direction, distance = rng.random() * 0.4, rng.random() * math.tau, rng.uniform(0.5, 1.2)
            local = max(0.0, min(1.0, (p - delay) / (1 - delay)))
            if local <= 0:
                continue
            q = (1 - local) ** 2
            scale = max(0.02, 1 - q)
            if effect == "explosion":
                dx = math.cos(direction) * image.width * q * distance * strength
                dy = math.sin(direction) * image.height * q * distance * strength
            else:
                dx = dy = 0
            size = (max(1, round(tile.width * scale)), max(1, round(tile.height * scale)))
            tile = tile.resize(size, Image.Resampling.BICUBIC)
            canvas.paste(tile, (round((x0 + x1 - size[0]) / 2 + dx),
                                round((y0 + y1 - size[1]) / 2 + dy)))
    return canvas


def split(image, p):
    canvas = Image.new("RGB", image.size)
    mid = image.width // 2
    shift = round(image.width * (1 - p) ** 3 / 2)
    canvas.paste(image.crop((0, 0, mid, image.height)), (-shift, 0))
    canvas.paste(image.crop((mid, 0, image.width, image.height)), (mid + shift, 0))
    return canvas


def clone(image, p, strength):
    canvas = Image.new("RGB", image.size)
    q = (1 - p) ** 2
    for i in range(5):
        angle = i * math.tau / 5
        layer = affine(image, 1 - q * 0.75,
                       dx=math.cos(angle) * image.width * q * strength,
                       dy=math.sin(angle) * image.height * q * strength)
        canvas = Image.blend(canvas, layer, 0.3)
    return Image.blend(fade(canvas, min(1.0, p * 4)), image, p ** 3)


def star(image, p):
    mask = Image.new("L", image.size)
    radius = math.hypot(*image.size) * p ** 1.3 * 1.8
    vertices = []
    for i in range(10):
        angle = i * math.pi / 5 - math.pi / 2
        r = radius if i % 2 == 0 else radius * 0.45
        vertices.append((image.width / 2 + r * math.cos(angle),
                         image.height / 2 + r * math.sin(angle)))
    ImageDraw.Draw(mask).polygon(vertices, fill=255)
    return Image.composite(image, Image.new("RGB", image.size), mask)


def ripple(image, p, strength):
    yy, xx = np.indices((image.height, image.width), dtype=np.float32)
    dx, dy = xx - image.width / 2, yy - image.height / 2
    radius = np.hypot(dx, dy)
    reach = math.hypot(*image.size) / 2
    wave = np.sin(radius / max(1, image.width * 0.018) - p * 18)
    offset = wave * (1 - p) ** 2 * image.width * 0.025 * strength
    safe = np.maximum(1, radius)
    src_x = np.clip(np.rint(xx + dx / safe * offset), 0, image.width - 1).astype(int)
    src_y = np.clip(np.rint(yy + dy / safe * offset), 0, image.height - 1).astype(int)
    result = np.asarray(image)[src_y, src_x].copy()
    result[radius > reach * min(1.01, p * 1.2)] = 0
    return Image.fromarray(result)


def render_reveal(image, effect, p, strength, seed):
    if effect in ("mosaic", "explosion"):
        return pieces(image, effect, p, strength, seed)
    if effect == "split":
        return split(image, p)
    if effect == "clone":
        return clone(image, p, strength)
    if effect == "star":
        return star(image, p)
    return ripple(image, p, strength)
