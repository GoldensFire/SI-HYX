# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Раскрытие кадра перестановкой: растущая миниатюра и сборка пазла."""
from __future__ import annotations

import math

from PIL import Image

from frame_reveal_tone import _remaining


class ThumbnailReveal:
    """Весь кадр целиком, но крошечный, посреди чёрного экрана."""

    def __init__(self, image: Image.Image, strength: float, rng, anchor):
        self.image = image
        # Доля площади на старте: 1,3% при 55 — это примерно 140×80 из 1280×720.
        self.start = max(0.004, 0.035 - 0.04 * strength)

    def render(self, progress: float) -> Image.Image:
        p = max(0.0, min(1.0, float(progress)))
        side = math.sqrt(self.start + (1 - self.start) * p ** 1.65)
        w, h = self.image.size
        tw, th = max(1, round(w * side)), max(1, round(h * side))
        out = Image.new("RGB", (w, h), "black")
        small = self.image.resize((tw, th), Image.Resampling.LANCZOS)
        out.paste(small, ((w - tw) // 2, (h - th) // 2))
        return out


class PuzzleReveal:
    """Прямоугольные куски перемешаны; каждая ступень ставит на место новые.

    Порядок сборки задан один раз: случайный или от центра к краям. Куски,
    которые ещё не на месте, всегда стоят в чужих ячейках — сдвиг по кругу
    внутри неустановленных не оставляет ни одного случайно «угаданного».
    """

    def __init__(self, image: Image.Image, strength: float, rng, anchor,
                 from_center: bool = False):
        self.image = image
        w, h = image.size
        # Кусков втрое больше прежнего (просьба пользователя): 14×8 = 112 при
        # 55 на кадре 16:9 вместо прежних 8×4-5.
        cols = max(2, min(w, round(5 + 16 * strength)))      # 14 при 55
        rows = max(2, min(h, round(cols * h / max(1, w))))
        xs = [i * w // cols for i in range(cols + 1)]
        ys = [j * h // rows for j in range(rows + 1)]
        self.boxes = [(xs[i], ys[j], xs[i + 1], ys[j + 1])
                      for j in range(rows) for i in range(cols)]
        pieces = list(range(len(self.boxes)))
        rng.shuffle(pieces)
        if from_center:
            # Ключ — расстояние от центра в долях кадра; при равенстве решает
            # случайный порядок выше, поэтому кольцо собирается вразнобой.
            def distance(i):
                x0, y0, x1, y1 = self.boxes[i]
                return round(math.hypot((x0 + x1) / w - 1, (y0 + y1) / h - 1), 6)
            pieces.sort(key=distance)
        self.order = pieces
        self.cycle = list(range(len(self.boxes)))
        rng.shuffle(self.cycle)

    def render(self, progress: float) -> Image.Image:
        p = max(0.0, min(1.0, float(progress)))
        total = len(self.boxes)
        if p >= 1:
            placed = total
        else:
            # Хотя бы два куска чужие, иначе ступень уже была бы чистым кадром.
            placed = min(total - 2, round(total * (1 - _remaining(p, 1.3))))
        home = set(self.order[:placed])
        loose = [i for i in self.cycle if i not in home]
        out = self.image.copy()
        for k, piece in enumerate(loose):
            target = self.boxes[loose[(k + 1) % len(loose)]]
            source = self.boxes[piece]
            size = (target[2] - target[0], target[3] - target[1])
            chunk = self.image.crop(source)
            if chunk.size != size:
                chunk = chunk.resize(size, Image.Resampling.BILINEAR)
            out.paste(chunk, target[:2])
        return out
