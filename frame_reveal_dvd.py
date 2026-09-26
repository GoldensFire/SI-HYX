# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Раскрытие «DVD-заставкой»: прямоугольник летает по чёрному экрану.

Кадр целиком чёрный. Прямоугольник появляется в случайном месте и летит по
прямой, отскакивая от краёв, как логотип на заставке DVD-плеера; всё, над чем
он пролетел, остаётся открытым (просьба пользователя). Движение идёт КАЖДЫМ
кадром ролика (30 или 60 к/с), а не ступенями, как у остальных эффектов.

Путь строится заранее (frame_reveal_dvd_path): размер прямоугольника
постоянен, скорость спокойная, а к концу заданного времени он вылетает за
край кадра; необлетённые места так и остаются чёрными.
След рисуется со сглаживанием: край — ровная наклонная линия, а не лесенка
из прямоугольников, поставленных в целые пиксели.

Прямоугольник может быть и сам заполнен: картинкой или беззвучным видео из
папки пользователя (см. frame_reveal_dvd_media). Тогда при каждом отскоке
содержимое меняется на случайное другое, а форма прямоугольника — на форму
нового файла.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw

from frame_reveal_dvd_path import plan_timed

DVD_FPS = 30
DVD_FPS_CHOICES = (30, 60)
# Длина «эталонного» ролика для ступенчатого показа (RevealRenderer): у
# превью в таблице и в тестах времени нет, есть только доля прогресса.
_PREVIEW_SECONDS = 10
# Спокойная скорость, доля ширины кадра в секунду (прежняя была ~0,37 —
# «слишком быстро»). Длина пути = скорость × время движения.
CALM_SPEED = 0.2
# Сглаживание следа: точек на пиксель по каждой оси.
_SUPERSAMPLE = 4


def dvd_fps(value) -> int:
    """Кадров/с заставки из настроек: только 30 или 60."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return DVD_FPS
    return value if value in DVD_FPS_CHOICES else DVD_FPS


class DvdAnimation:
    """Покадровая анимация. Случайность фиксирована зерном вопроса.

    media — источник содержимого прямоугольника (или None — тогда он лишь
    окно в кадр): объект с методом ``next_clip()`` → клип или None и у клипа
    ``aspect``, ``frame(width, height)`` → numpy RGB и ``close()``.
    frames — сколько кадров длится движение: к последнему прямоугольник
    целиком за краем кадра.
    """

    def __init__(self, image: Image.Image, strength: float, rng, media=None,
                 fps: int = DVD_FPS, frames: int | None = None):
        self.image = np.asarray(image.convert("RGB"), dtype=np.uint8)
        self.h, self.w = self.image.shape[:2]
        self.canvas = np.zeros_like(self.image)
        self.mask = np.zeros((self.h, self.w), dtype=np.uint8)
        self.media = media
        self._clips: list = []
        # Сила 10…100 % → площадь прямоугольника 11,6 … 4 % кадра: чем
        # сильнее, тем меньше окошко и тем дольше кадр прячется.
        s = max(0.1, min(1.0, float(strength)))
        self.area = (0.125 - 0.085 * s) * self.w * self.h
        frames = max(2, int(frames or _PREVIEW_SECONDS * fps))
        budget = CALM_SPEED * self.w * frames / max(1, fps)
        self.path = plan_timed(self.w, self.h, self._size,
                               rng.getrandbits(64), budget,
                               self._clip_at if media is not None else None)
        self.starts = np.cumsum([0.0] + [seg.length for seg in self.path])
        self.total = float(self.starts[-1])
        self.ds = self.total / (frames - 1)
        self.index, self.s, self.local = 0, 0.0, 0.0
        first = self.path[0]
        self.box = first.rect(0.0, self.w, self.h)
        self.clip = first.clip
        self._sweep(self.box, self.box)

    # ── размеры и содержимое ──────────────────────────────────────────
    def _size(self, clip) -> tuple[int, int]:
        """Размер прямоугольника по форме клипа."""
        aspect = getattr(clip, "aspect", None) or self.w / max(1, self.h)
        aspect = max(0.2, min(5.0, float(aspect)))
        rw, rh = math.sqrt(self.area * aspect), math.sqrt(self.area / aspect)
        fit = min(1.0, 0.6 * self.w / rw, 0.6 * self.h / rh)
        return max(8, round(rw * fit)), max(8, round(rh * fit))

    def _clip_at(self, i: int):
        """Клип i-го отрезка: жребий тянется один раз и запоминается."""
        while len(self._clips) <= i:
            self._clips.append(self.media.next_clip())
        return self._clips[i]

    @property
    def x(self) -> float:
        return self.box[0]

    @property
    def y(self) -> float:
        return self.box[1]

    @property
    def rw(self) -> int:
        return max(1, round(self.box[2]))

    @property
    def rh(self) -> int:
        return max(1, round(self.box[3]))

    # ── движение ──────────────────────────────────────────────────────
    def step(self) -> None:
        """Сдвиг на один кадр ролика."""
        self.seek_length(self.s + self.ds)

    def seek(self, progress: float) -> None:
        """Сразу к доле пути (только вперёд): для ступенчатого превью."""
        self.seek_length(max(0.0, min(1.0, float(progress))) * self.total)

    def seek_length(self, target: float) -> None:
        target = min(max(target, self.s), self.total)
        while True:
            seg = self.path[self.index]
            if target < self.starts[self.index + 1] or self.index == len(self.path) - 1:
                self._travel(seg, min(seg.length, target - self.starts[self.index]))
                break
            self._travel(seg, seg.length)
            self.index += 1
            nxt = self.path[self.index]
            self.local = 0.0
            self.box = nxt.rect(0.0, self.w, self.h)
            if nxt.clip is not self.clip:
                if self.clip is not None:
                    self.clip.close()
                self.clip = nxt.clip
        self.s = target

    def _travel(self, seg, local: float) -> None:
        """Проезд по отрезку до local; смена размера — отдельным куском,
        чтобы между соседними кадрами путь оставался прямым."""
        if self.local < seg.morph < local:
            self._move(seg, seg.morph)
        self._move(seg, local)

    def _move(self, seg, local: float) -> None:
        box = seg.rect(local, self.w, self.h)
        self._sweep(self.box, box)
        self.box, self.local = box, local

    def _sweep(self, a, b) -> None:
        """Открывает след прямоугольника от a до b со сглаженным краем."""
        corners = [(x + dx, y + dy) for x, y, w, h in (a, b)
                   for dx in (0, w) for dy in (0, h)]
        hull = _hull(corners)
        x0 = max(0, math.floor(min(p[0] for p in hull)))
        y0 = max(0, math.floor(min(p[1] for p in hull)))
        x1 = min(self.w, math.ceil(max(p[0] for p in hull)))
        y1 = min(self.h, math.ceil(max(p[1] for p in hull)))
        if x1 <= x0 or y1 <= y0:
            return
        ss = _SUPERSAMPLE
        layer = Image.new("L", ((x1 - x0) * ss, (y1 - y0) * ss), 0)
        # −0,5: точки выборки — центры подпикселей, а не их углы.
        ImageDraw.Draw(layer).polygon(
            [((px - x0) * ss - 0.5, (py - y0) * ss - 0.5) for px, py in hull],
            fill=255)
        cover = np.asarray(layer.reduce(ss))
        patch = self.mask[y0:y1, x0:x1]
        np.maximum(patch, cover, out=patch)
        source = self.image[y0:y1, x0:x1].astype(np.uint16)
        self.canvas[y0:y1, x0:x1] = (source * patch[..., None] + 127) // 255

    def frame(self) -> np.ndarray:
        """Текущий кадр ролика: открытый след и прямоугольник поверх."""
        out = self.canvas.copy()
        if self.clip is not None:
            rw, rh = self.rw, self.rh
            x0, y0 = round(self.x), round(self.y)
            # На вылете прямоугольник частично (или целиком) за краем кадра.
            cx0, cy0 = max(0, x0), max(0, y0)
            cx1, cy1 = min(self.w, x0 + rw), min(self.h, y0 + rh)
            if cx1 <= cx0 or cy1 <= cy0:
                return out
            seg = self.path[self.index]
            # Клип декодируется в итоговом размере отрезка; пока форма
            # плавно меняется, кадр лишь масштабируется.
            picture = self.clip.frame(seg.w, seg.h)
            if picture is not None and picture.shape[:2] != (rh, rw):
                picture = np.asarray(Image.fromarray(picture).resize(
                    (rw, rh), Image.Resampling.BILINEAR))
            if picture is not None:
                out[cy0:cy1, cx0:cx1] = picture[cy0 - y0:cy1 - y0,
                                                cx0 - x0:cx1 - x0]
        return out

    def close(self) -> None:
        """Гасит все клипы (процессы ffmpeg видео, кеши картинок)."""
        for clip in {id(c): c for c in self._clips if c is not None}.values():
            clip.close()


def _hull(points):
    """Выпуклая оболочка (монотонная цепь Эндрю), обход против часовой."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


class DvdReveal:
    """Ступенчатый показ для RevealRenderer: состояние анимации на доле пути."""

    def __init__(self, image, strength, rng, anchor):
        self.image = image
        self.strength = strength
        self.seed = rng.getrandbits(64)
        self.anim = None

    def render(self, progress: float) -> Image.Image:
        import random
        progress = max(0.0, min(1.0, float(progress)))
        # Путь строится один раз; назад анимация не ходит — тогда заново.
        if self.anim is None or progress * self.anim.total < self.anim.s:
            self.anim = DvdAnimation(self.image, self.strength,
                                     random.Random(self.seed))
        self.anim.seek(progress)
        return Image.fromarray(self.anim.frame(), "RGB")
