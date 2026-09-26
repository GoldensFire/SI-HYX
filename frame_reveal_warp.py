# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Раскрытие кадра геометрией: волны, сдвиг полос и спираль."""
from __future__ import annotations

import math

import numpy as np
from PIL import Image

from frame_reveal_tone import _remaining


def _reflect(coords: np.ndarray, size: int) -> np.ndarray:
    """Координаты за краем отражаются внутрь — без чёрных клиньев."""
    if size <= 1:
        return np.zeros_like(coords)
    period = 2.0 * (size - 1)
    folded = np.mod(coords, period)
    return np.where(folded > size - 1, period - folded, folded)


def remap(pixels: np.ndarray, src_x: np.ndarray, src_y: np.ndarray) -> Image.Image:
    """Каждый пиксель берётся из (src_x, src_y) исходника, билинейно."""
    h, w = pixels.shape[:2]
    x = _reflect(src_x, w)
    y = _reflect(src_y, h)
    x0 = np.floor(x).astype(np.intp)
    y0 = np.floor(y).astype(np.intp)
    x1 = np.minimum(x0 + 1, w - 1)
    y1 = np.minimum(y0 + 1, h - 1)
    fx = (x - x0)[..., None]
    fy = (y - y0)[..., None]
    top = pixels[y0, x0] * (1 - fx) + pixels[y0, x1] * fx
    bottom = pixels[y1, x0] * (1 - fx) + pixels[y1, x1] * fx
    out = top * (1 - fy) + bottom * fy
    return Image.fromarray(np.clip(out + 0.5, 0, 255).astype(np.uint8), "RGB")


class _Warp:
    def __init__(self, image: Image.Image, strength: float, rng, anchor):
        self.pixels = np.asarray(image, dtype=np.float32)
        h, w = self.pixels.shape[:2]
        self.w, self.h = w, h
        self.grid_y, self.grid_x = np.mgrid[0:h, 0:w].astype(np.float32)


class WaveReveal(_Warp):
    """Две волны — вдоль и поперёк кадра; амплитуда сходит на нет."""

    def __init__(self, image, strength, rng, anchor):
        super().__init__(image, strength, rng, anchor)
        self.amplitude = self.h * (0.03 + 0.08 * strength)
        # Длина волны — от пятой до третьей части высоты: мельче рябь
        # превращается в шум, крупнее — в плавный изгиб, который легко читать.
        self.length_x = self.h * rng.uniform(0.2, 0.34)
        self.length_y = self.h * rng.uniform(0.2, 0.34)
        self.phase_x = rng.uniform(0, 2 * math.pi)
        self.phase_y = rng.uniform(0, 2 * math.pi)

    def render(self, progress: float) -> Image.Image:
        amp = self.amplitude * _remaining(progress, 1.2)
        dx = amp * np.sin(2 * math.pi * self.grid_y / self.length_x + self.phase_x)
        dy = amp * np.sin(2 * math.pi * self.grid_x / self.length_y + self.phase_y)
        return remap(self.pixels, self.grid_x + dx, self.grid_y + dy)


class SwirlReveal(_Warp):
    """Закрутка вокруг центра: сильнее у середины, ноль у самых углов."""

    def __init__(self, image, strength, rng, anchor):
        super().__init__(image, strength, rng, anchor)
        self.angle = math.pi * (1.5 + 5.0 * strength) * rng.choice((-1, 1))
        cx, cy = (self.w - 1) / 2, (self.h - 1) / 2
        self.dx = self.grid_x - cx
        self.dy = self.grid_y - cy
        radius = math.hypot(cx, cy) or 1.0
        self.falloff = np.clip(1.0 - np.hypot(self.dx, self.dy) / radius, 0, 1) ** 2
        self.center = (cx, cy)

    def render(self, progress: float) -> Image.Image:
        theta = self.angle * _remaining(progress, 1.4) * self.falloff
        cos, sin = np.cos(theta), np.sin(theta)
        cx, cy = self.center
        return remap(self.pixels, cx + self.dx * cos - self.dy * sin,
                     cy + self.dx * sin + self.dy * cos)


class StripesReveal:
    """Горизонтальные полосы разъехались влево и вправо и съезжаются обратно."""

    def __init__(self, image: Image.Image, strength: float, rng, anchor):
        self.image = image
        w, h = image.size
        count = max(2, min(h, 10 + round(14 * strength)))
        self.bounds = [i * h // count for i in range(count + 1)]
        low, high = 0.18 + 0.12 * strength, 0.35 + 0.3 * strength
        self.shifts = [rng.choice((-1, 1)) * rng.uniform(low, high) * w
                       for _ in range(count)]

    def render(self, progress: float) -> Image.Image:
        rest = _remaining(progress, 1.3)
        w, h = self.image.size
        out = Image.new("RGB", (w, h), "black")
        for (top, bottom), shift in zip(zip(self.bounds, self.bounds[1:]), self.shifts):
            if bottom > top:
                band = self.image.crop((0, top, w, bottom))
                out.paste(band, (round(shift * rest), top))
        return out

