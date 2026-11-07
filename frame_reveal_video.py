# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Эффекты раскрытия кадра (frame_reveal) поверх видео — для «Монтажа».

Генератор паков раскрывает одну картинку по ступеням. Здесь те же эффекты
идут по кадрам клипа: клип делится на N равных окон, как у пикселизации
кнопки «Пикселизация», в каждом окне эффект держит свою ступень, последнее
окно — чистый кадр. Геометрия (плитки, волны, пазл, точка детали) задаётся
по первому кадру и дальше не меняется — меняется только содержимое.
DVD-заставка движется каждым кадром, а не ступенями, как и в паке.

Ни Qt, ни ffmpeg здесь нет: кадр приходит и уходит массивом RGB.
"""
from __future__ import annotations

import random

import numpy as np
from PIL import Image

from frame_reveal import ANIMATED_EFFECTS, EFFECT_LABELS, RevealRenderer

# Сила эффектов — та же, что по умолчанию у генератора паков.
DEFAULT_STRENGTH = 55


class VideoReveal:
    """Применяет эффект к кадрам клипа по номеру кадра.

    total — сколько кадров в клипе (по нему режутся окна ступеней), fps —
    частота клипа (по ней DVD-заставка держит спокойную скорость).
    still — все кадры одинаковы (картинка → видео): ступень считается один
    раз и повторяется.
    dvd_media — источники картинок/видео для прямоугольника DVD-заставки
    (папка с картинками и видео, см. frame_reveal_dvd_media); пусто — прямоугольник
    лишь окно в кадр. ffmpeg/ffprobe нужны только видеофайлам из источников.
    """

    def __init__(self, effect: str, steps: int, total: int, fps: float = 30.0,
                 strength: int = DEFAULT_STRENGTH, seed: int | None = None,
                 still: bool = False, dvd_media: str = "",
                 ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe"):
        if effect not in EFFECT_LABELS or effect == "pixelize":
            raise ValueError(f"Неизвестный эффект для видео: {effect}")
        self.effect = effect
        self.steps = max(1, int(steps))
        self.total = max(1, int(total))
        self.fps = float(fps) if fps and fps > 0 else 30.0
        self.strength = max(10, min(100, int(strength)))
        self.seed = random.getrandbits(64) if seed is None else int(seed)
        self.still = bool(still)
        self.renderer = None
        self.anim = None
        self.media = None
        self.dvd_media = str(dvd_media or "")
        self.ffmpeg, self.ffprobe = ffmpeg, ffprobe
        self._cache = {}
        # DVD летит до начала последнего окна; дальше след застывает, и
        # необлетённое остаётся чёрным — как в паке.
        last = self.total // self.steps if self.steps > 1 else 0
        self.moving = max(2, self.total - last)

    def progress(self, index: int) -> float:
        """Доля раскрытия для кадра: ступень окна / (N − 1)."""
        if self.steps <= 1:
            return 0.0
        stage = min(self.steps - 1, max(0, int(index)) * self.steps // self.total)
        return stage / (self.steps - 1)

    def apply(self, index: int, pixels: np.ndarray) -> np.ndarray:
        """Кадр index (H×W×3 uint8 RGB) с эффектом."""
        if self.effect in ANIMATED_EFFECTS:
            return self._dvd(index, pixels)
        p = self.progress(index)
        if p >= 1:
            return pixels
        if self.still and p in self._cache:
            return self._cache[p]
        image = Image.fromarray(pixels, "RGB")
        if self.renderer is None:
            self.renderer = RevealRenderer(image, self.effect, self.strength, self.seed)
        else:
            self.renderer.set_frame(image)
        out = np.asarray(self.renderer.render(p))
        if self.still:
            self._cache[p] = out
        return out

    def _dvd(self, index: int, pixels: np.ndarray) -> np.ndarray:
        if self.anim is None:
            from frame_reveal_dvd import DvdAnimation
            from frame_reveal_dvd_media import FolderMedia, list_media
            files = list_media(self.dvd_media)
            if files:
                # Своё зерно у жребия файлов: путь заставки от него не зависит.
                self.media = FolderMedia(files, random.Random(self.seed ^ 0x5EED),
                                         self.ffmpeg, self.ffprobe, self.fps)
            self.anim = DvdAnimation(Image.fromarray(pixels, "RGB"),
                                     self.strength / 100.0,
                                     random.Random(self.seed), self.media,
                                     self.fps, self.moving)
        moving = index < self.moving
        out = self.anim.reveal(pixels, moving)
        if moving:
            self.anim.step()
        return out

    def close(self) -> None:
        if self.anim is not None:
            self.anim.close()
        if self.media is not None:
            self.media.close()
