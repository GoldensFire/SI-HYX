# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Раскрытие кадра чёрной маской: точки появляются, растут, пятна тают.

Каждый эффект один раз строит «поле очереди»: число на пиксель, чем меньше —
тем раньше пиксель откроется. Ступень открывает нужную долю площади по порогу
этого поля, поэтому открытое место не может закрыться на следующей ступени.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw


class _QueueMask:
    """Общая часть: порог по доле площади и наложение на чёрный."""

    def __init__(self, image: Image.Image, strength: float, rng):
        self.image = image
        self.start = max(0.015, 0.1 - 0.08 * strength)   # 5,6% площади при 55
        self.np_rng = np.random.default_rng(rng.getrandbits(64))
        self.field = None
        self.sorted = None

    def _set_field(self, field: np.ndarray) -> None:
        self.field = field
        # Порог ищем по прореженной копии: точности в долю процента хватает,
        # а сортировать миллион значений на каждую ступень незачем.
        step = max(1, field.size // 200_000)
        self.sorted = np.sort(field.ravel()[::step])

    def visible_share(self, progress: float) -> float:
        p = max(0.0, min(1.0, float(progress)))
        return self.start + (1 - self.start) * p ** 1.45

    def render(self, progress: float) -> Image.Image:
        share = self.visible_share(progress)
        index = min(len(self.sorted) - 1, int(share * len(self.sorted)))
        mask = (self.field <= self.sorted[index]).astype(np.uint8) * 255
        black = Image.new("RGB", self.image.size, "black")
        return Image.composite(self.image, black, Image.fromarray(mask, "L"))


class HolesReveal(_QueueMask):
    """Круглые отверстия появляются одно за другим в случайных местах."""

    def __init__(self, image, strength, rng, anchor):
        super().__init__(image, strength, rng)
        w, h = image.size
        r_min = max(1.5, h * (0.05 - 0.02 * strength))
        r_max = r_min * 2.2
        # Центры берём из ещё не покрытых клеток грубой сетки: отверстия
        # расходятся по всему кадру, и к концу не остаётся забытых углов.
        cell = max(1.0, r_min * 0.9)
        gx, gy = np.meshgrid(np.arange(cell / 2, w, cell), np.arange(cell / 2, h, cell))
        gx, gy = gx.ravel(), gy.ravel()
        open_cells = np.ones(gx.size, dtype=bool)
        circles = []
        while open_cells.any():
            pick = self.np_rng.choice(np.flatnonzero(open_cells))
            x = gx[pick] + self.np_rng.uniform(-cell / 2, cell / 2)
            y = gy[pick] + self.np_rng.uniform(-cell / 2, cell / 2)
            r = self.np_rng.uniform(r_min, r_max)
            circles.append((x, y, r))
            open_cells &= np.hypot(gx - x, gy - y) > r
        ranks = Image.new("I", (w, h), len(circles))
        draw = ImageDraw.Draw(ranks)
        # С конца к началу: пиксель достаётся самому раннему кругу.
        for rank in range(len(circles) - 1, -1, -1):
            x, y, r = circles[rank]
            draw.ellipse((x - r, y - r, x + r, y + r), fill=rank)
        self._set_field(np.asarray(ranks, dtype=np.int32))


class SpotsReveal(_QueueMask):
    """Маленькие круглые окошки растут, сливаются и открывают весь кадр."""

    def __init__(self, image, strength, rng, anchor):
        super().__init__(image, strength, rng)
        w, h = image.size
        count = round(10 + 16 * (1 - strength))          # 17 при 55
        centers = self._spread_points(count, w, h)
        weights = self.np_rng.uniform(0.75, 1.3, len(centers))
        ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
        field = np.full((h, w), np.inf, dtype=np.float32)
        for (cx, cy), weight in zip(centers, weights):
            np.minimum(field, np.hypot(xs - cx, ys - cy) / weight, out=field)
        self._set_field(field)

    def _spread_points(self, count: int, w: int, h: int) -> list[tuple[float, float]]:
        """Лучший из нескольких кандидатов — самый далёкий от уже выбранных."""
        points = []
        for _ in range(count):
            cand = self.np_rng.uniform((0, 0), (w, h), size=(12, 2))
            if points:
                chosen = np.array(points)
                gaps = np.min(np.hypot(cand[:, None, 0] - chosen[None, :, 0],
                                       cand[:, None, 1] - chosen[None, :, 1]), axis=1)
                cand = cand[[int(np.argmax(gaps))]]
            points.append((float(cand[0, 0]), float(cand[0, 1])))
        return points


class BlotsReveal(_QueueMask):
    """Чёрные кляксы неправильной формы сжимаются, дробятся и исчезают."""

    def __init__(self, image, strength, rng, anchor):
        super().__init__(image, strength, rng)
        w, h = image.size
        field = np.zeros((h, w), dtype=np.float32)
        # Сумма октав шума: крупные формы задают кляксы, мелкие — рваный край.
        base = 4 + 3 * (1 - strength)
        for octave in range(4):
            cols = max(2, round(base * 2 ** octave))
            rows = max(2, round(cols * h / max(1, w)))
            grid = self.np_rng.random((rows, cols)).astype(np.float32)
            layer = Image.fromarray(grid, "F").resize((w, h), Image.Resampling.BICUBIC)
            field += np.asarray(layer, dtype=np.float32) * 0.5 ** octave
        self._set_field(field)
