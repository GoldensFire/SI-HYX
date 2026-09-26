# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Раскрытие кадра яркостью: из темноты и из пересвета."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter


def _remaining(progress: float, power: float = 1.3) -> float:
    """Сколько эффекта осталось: 1 на старте, 0 на чистом кадре."""
    return (1.0 - max(0.0, min(1.0, float(progress)))) ** power


def _to_image(values: np.ndarray) -> Image.Image:
    return Image.fromarray(np.clip(values * 255.0 + 0.5, 0, 255).astype(np.uint8), "RGB")


class DarknessReveal:
    """Почти чёрный кадр, из которого возвращаются яркость, цвет и детали.

    Яркость множится в sRGB, а не в линейном свете: иначе «почти чёрный»
    кадр на экране оставался бы серым. Показатель степени сначала больше
    единицы — тени уходят в черноту раньше светлых мест, и первыми из
    темноты проступают самые яркие детали.
    """

    def __init__(self, image: Image.Image, strength: float, rng, anchor):
        self.image = image
        self.floor = 0.11 - 0.09 * strength       # яркость на старте: 6% при 55
        self.gamma = 1.0 + 1.6 * strength
        self.blur = image.height / 720 * (2 + 6 * strength)

    def render(self, progress: float) -> Image.Image:
        rest = _remaining(progress)
        frame = self.image
        radius = self.blur * rest
        if radius >= 0.3:
            frame = frame.filter(ImageFilter.GaussianBlur(radius))
        frame = ImageEnhance.Color(frame).enhance(1.0 - 0.85 * rest)
        values = np.asarray(frame, dtype=np.float32) / 255.0
        gain = self.floor ** rest                 # геометрически: ровные шаги на глаз
        values = gain * values ** (1.0 + (self.gamma - 1.0) * rest)
        return _to_image(values)


class OverexposureReveal:
    """Почти белый кадр: экспозиция падает, светлые детали возвращаются последними.

    Выдержка множится в линейном свете с отсечкой белого, поэтому пересвет
    съедает сначала светлые участки. Сверху кадр ещё подтянут к белому,
    чтобы даже чёрное на старте было светло-серым.
    """

    def __init__(self, image: Image.Image, strength: float, rng, anchor):
        self.linear = (np.asarray(image, dtype=np.float32) / 255.0) ** 2.2
        self.exposure = 4.0 + 20.0 * strength     # ×15 при 55
        self.lift = 0.27 - 0.22 * strength        # доля контраста на старте

    def render(self, progress: float) -> Image.Image:
        rest = _remaining(progress)
        exposed = np.minimum(1.0, self.linear * self.exposure ** rest) ** (1 / 2.2)
        contrast = self.lift ** rest
        return _to_image(1.0 - (1.0 - exposed) * contrast)
