# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Движение, масштаб, вращение и размытие при появлении картинки."""
from __future__ import annotations

import math
from PIL import Image, ImageFilter


def affine(image, sx=1.0, sy=None, angle=0.0, dx=0.0, dy=0.0):
    """Обратное преобразование сохраняет размер холста даже при большом зуме."""
    sy = sx if sy is None else sy
    sx, sy = max(0.015, sx), max(0.015, sy)
    rad = math.radians(angle)
    cosine, sine = math.cos(rad), math.sin(rad)
    a, b, d, e = cosine / sx, sine / sx, -sine / sy, cosine / sy
    cx, cy = image.width / 2, image.height / 2
    matrix = (a, b, cx - a * (cx + dx) - b * (cy + dy),
              d, e, cy - d * (cx + dx) - e * (cy + dy))
    return image.transform(image.size, Image.Transform.AFFINE, matrix,
                           Image.Resampling.BICUBIC)


def fade(image, opacity):
    return Image.blend(Image.new("RGB", image.size), image,
                       max(0.0, min(1.0, opacity)))


def flash(image, p, strength, multiple=False):
    peaks = (0.0, 0.32, 0.62) if multiple else (0.0,)
    width = 0.075 if multiple else 0.16
    light = max(math.exp(-((p - at) / width) ** 2) for at in peaks)
    return Image.blend(image, Image.new("RGB", image.size, "white"),
                       min(1.0, light * (0.6 + 0.4 * strength) * (1 - p)))


def bounce(p):
    n, d = 7.5625, 2.75
    if p < 1 / d:
        return n * p * p
    if p < 2 / d:
        return n * (p - 1.5 / d) ** 2 + 0.75
    if p < 2.5 / d:
        return n * (p - 2.25 / d) ** 2 + 0.9375
    return n * (p - 2.625 / d) ** 2 + 0.984375


def spring(p):
    return 1 + 2.70158 * (p - 1) ** 3 + 1.70158 * (p - 1) ** 2


def radial_blur(image, amount):
    blurred = image
    for i in range(1, 7):
        layer = affine(image, 1 + amount * i / 6)
        blurred = Image.blend(blurred, layer, 1 / (i + 1))
    return blurred


def render_motion(image, effect, p, strength):
    q = 1 - p
    ease = 1 - q ** 3
    w, h = image.size
    scale, angle, dx, dy = 1.0, 0.0, 0.0, 0.0
    sx, sy = None, None
    opacity = min(1.0, p * 5)
    blur = 0.0
    if effect == "crash_zoom":
        scale = 0.08 + 0.92 * spring(p)
        angle = math.sin(p * math.pi) * q * 8 * strength
    elif effect in ("spin", "flash_spin"):
        angle = -360 * q ** 2 * (0.5 + 0.5 * strength)
        scale = 0.15 + 0.85 * ease
    elif effect == "spiral":
        angle = -540 * q ** 2 * strength
        dx = math.cos(p * 4 * math.pi) * q ** 2 * w * 0.7
        dy = math.sin(p * 4 * math.pi) * q ** 2 * h * 0.7
        scale = 0.1 + 0.9 * ease
    elif effect == "bounce":
        dy = -h * (1 - bounce(p))
    elif effect == "fly":
        dx, dy = -w * q ** 3, h * q ** 3
        angle, scale = 25 * q * strength, 0.15 + 0.85 * ease
    elif effect == "whip":
        dx = -w * q ** 4
        blur = q ** 3 * 18 * strength * w / 720
    elif effect in ("shake", "shake_zoom"):
        dx = math.sin(p * 14 * math.pi) * q ** 2 * w * 0.12 * strength
        dy = math.cos(p * 18 * math.pi) * q ** 2 * h * 0.09 * strength
        angle = math.sin(p * 12 * math.pi) * q ** 2 * 8 * strength
        if effect == "shake_zoom":
            scale = 0.15 + 0.85 * ease
    elif effect == "stretch":
        wave = math.cos(p * 3 * math.pi) * q ** 2
        sx, sy = 1 + wave * strength, max(0.03, 1 - wave * 0.97)
    elif effect == "expand":
        sx, sy = 0.02 + 0.98 * ease, 0.75 + 0.25 * ease
    elif effect == "pop":
        scale = max(0.02, spring(p))
    elif effect == "flip":
        sx, sy = max(0.02, abs(math.cos(q * 1.5 * math.pi))), 0.5 + 0.5 * ease
        if math.cos(q * 1.5 * math.pi) < 0:
            image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    elif effect == "rotate_zoom":
        scale, angle = 0.05 + 0.95 * ease, -120 * q ** 2 * strength
    elif effect == "blur_sharp":
        blur = q ** 2 * 32 * strength * w / 720
    elif effect == "radial_zoom":
        scale = 0.1 + 0.9 * ease
    elif effect == "dramatic_slide":
        dy = h * (1 - spring(p))
        angle = -18 * q ** 2 * strength
    elif effect == "multiple_zoom":
        # Три отдельные волны приближения с уменьшающейся амплитудой.
        scale = 0.1 + 0.9 * ease + math.sin(p * 6 * math.pi) * q * 0.25 * strength
    result = affine(image, sx or scale, sy, angle, dx, dy)
    if effect == "whip":
        for offset in (0.025, 0.05, 0.1):
            result = Image.blend(result, affine(image, dx=dx - w * offset * q), 0.2 * q)
    if effect == "radial_zoom":
        result = radial_blur(result, q ** 2 * strength)
    if blur > 0.01:
        result = result.filter(ImageFilter.GaussianBlur(blur))
    result = fade(result, opacity)
    if effect in ("flash", "flash_spin"):
        result = flash(result, p, strength, effect == "flash_spin")
    return result
