# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Путь «DVD-заставки»: отскоки по чёрному экрану и вылет за край.

Обычный отскок под постоянным углом ходит по одной и той же петле и в углы
почти не попадает. Здесь путь строится заранее: прямоугольник всё так же
летит по прямой и отскакивает от краёв, но на каждом отскоке выбирает
направление, которое откроет больше ещё чёрного.

Размер прямоугольника постоянен, скорость спокойная, а длина пути задана
временем ролика. Когда остатка пути хватает на вылет, прямоугольник улетает
за край кадра и к концу времени скрывается целиком; необлетённые места
остаются чёрными (просьба пользователя — не расти и не дочищать кадр).
Форма меняется лишь под новый клип из папки — плавно, за первые пиксели
нового отрезка, прижатая к стенке, от которой отскочил.

Покрытие считается по сетке целых клеток: клетка открыта, когда её целиком
накрыл прямоугольник в одном из положений на отрезке.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

import numpy as np

# Строк сетки покрытия; клетка — целое число пикселей.
GRID_ROWS = 48
# Потолок отскоков: на практике путь закрывается за десяток-другой.
MAX_SEGMENTS = 200
# Углы (от горизонтали) для обычного отскока, как у логотипа DVD.
_ANGLES = (22, 30, 38, 45, 52, 60, 68)
# Сколько случайных чёрных клеток пробовать как цель на каждом отскоке.
_AIMED = 10
# Длина плавной смены размера после отскока, доля меньшей стороны кадра.
_MORPH = 0.25
_EPS = 1e-6


@dataclass
class Segment:
    """Отрезок пути левого верхнего угла прямоугольника размера w×h.

    Первые morph пикселей пути размер плавно идёт от прежнего pw×ph к w×h;
    ax/ay — к чему он прижат: 0 — к левому (верхнему) краю, 1 — к правому
    (нижнему), 0,5 — растёт от середины.
    """
    x0: float
    y0: float
    x1: float
    y1: float
    w: int
    h: int
    clip: object = None
    pw: int = 0
    ph: int = 0
    ax: float = 0.5
    ay: float = 0.5
    morph: float = 0.0

    @property
    def length(self) -> float:
        return math.hypot(self.x1 - self.x0, self.y1 - self.y0)

    def rect(self, s: float, width: int, height: int):
        """(x, y, w, h) прямоугольника через s пикселей пути от начала."""
        t = s / self.length if self.length > _EPS else 1.0
        x = self.x0 + (self.x1 - self.x0) * t
        y = self.y0 + (self.y1 - self.y0) * t
        if self.morph <= _EPS or s >= self.morph:
            return x, y, float(self.w), float(self.h)
        k = max(0.0, s) / self.morph
        w = (self.pw or self.w) + (self.w - (self.pw or self.w)) * k
        h = (self.ph or self.h) + (self.h - (self.ph or self.h)) * k
        x = min(max(0.0, x + (self.w - w) * self.ax), width - w)
        y = min(max(0.0, y + (self.h - h) * self.ay), height - h)
        return x, y, w, h


class Coverage:
    """Сетка клеток кадра: какие уже целиком побывали под прямоугольником."""

    def __init__(self, width: int, height: int):
        self.width, self.height = width, height
        self.cell = max(2, round(height / GRID_ROWS))
        cols = math.ceil(width / self.cell)
        rows = math.ceil(height / self.cell)
        xs = np.arange(cols) * self.cell
        ys = np.arange(rows) * self.cell
        self.cx0, self.cx1 = xs.astype(float), np.minimum(width, xs + self.cell).astype(float)
        self.cy0, self.cy1 = ys.astype(float), np.minimum(height, ys + self.cell).astype(float)
        self.done = np.zeros((rows, cols), dtype=bool)

    def swept(self, seg: Segment, s0: float = 0.0) -> np.ndarray:
        """Клетки, которые прямоугольник w×h накрывает целиком на [s0, конец]."""
        t0 = s0 / seg.length if seg.length > _EPS else 0.0
        ax = seg.x0 + (seg.x1 - seg.x0) * t0
        ay = seg.y0 + (seg.y1 - seg.y0) * t0
        tx = _interval(ax, seg.x1, self.cx1 - seg.w, self.cx0)
        ty = _interval(ay, seg.y1, self.cy1 - seg.h, self.cy0)
        lo = np.maximum(tx[0][None, :], ty[0][:, None])
        hi = np.minimum(tx[1][None, :], ty[1][:, None])
        return lo <= hi + _EPS

    def gain(self, seg: Segment) -> int:
        return int((self.swept(seg) & ~self.done).sum())

    def mark(self, seg: Segment) -> None:
        """Отмечает пройденное; смену размера — по точкам, с запасом."""
        if seg.morph <= _EPS:
            self.done |= self.swept(seg)
            return
        self.done |= self.swept(seg, seg.morph)
        samples = max(2, math.ceil(seg.morph / (self.cell / 2)))
        for i in range(samples + 1):
            x, y, w, h = seg.rect(seg.morph * i / samples, self.width, self.height)
            c0 = np.searchsorted(self.cx0, x - _EPS)            # cx0 >= x
            c1 = np.searchsorted(self.cx1, x + w + _EPS, "right")  # cx1 <= x+w
            r0 = np.searchsorted(self.cy0, y - _EPS)
            r1 = np.searchsorted(self.cy1, y + h + _EPS, "right")
            if c1 > c0 and r1 > r0:
                self.done[r0:r1, c0:c1] = True

    def complete(self) -> bool:
        return bool(self.done.all())

    def dark_centres(self) -> np.ndarray:
        """Центры ещё чёрных клеток, массив (N, 2) — x, y."""
        rows, cols = np.nonzero(~self.done)
        return np.stack(((self.cx0[cols] + self.cx1[cols]) / 2,
                         (self.cy0[rows] + self.cy1[rows]) / 2), axis=1)


def _interval(a: float, b: float, lo: np.ndarray, hi: np.ndarray):
    """Доли t∈[0,1], при которых a+(b-a)t лежит в [lo, hi] (поклеточно)."""
    d = b - a
    if abs(d) < _EPS:
        inside = (lo <= a + _EPS) & (a <= hi + _EPS)
        return (np.where(inside, 0.0, 2.0), np.where(inside, 1.0, -1.0))
    t0, t1 = (lo - a) / d, (hi - a) / d
    return (np.maximum(np.minimum(t0, t1), 0.0),
            np.minimum(np.maximum(t0, t1), 1.0))


def _exit(x: float, y: float, dx: float, dy: float, xmax: float, ymax: float):
    """Точка, где луч из (x, y) упирается в край поля [0,xmax]×[0,ymax]."""
    t = math.inf
    if dx > _EPS:
        t = min(t, (xmax - x) / dx)
    elif dx < -_EPS:
        t = min(t, -x / dx)
    if dy > _EPS:
        t = min(t, (ymax - y) / dy)
    elif dy < -_EPS:
        t = min(t, -y / dy)
    if not math.isfinite(t) or t <= _EPS:
        return None
    return (min(max(0.0, x + dx * t), xmax), min(max(0.0, y + dy * t), ymax))


def _segment(x, y, direction, rw, rh, width, height, clip=None):
    end = _exit(x, y, direction[0], direction[1],
                float(width - rw), float(height - rh))
    if end is None:
        return None
    return Segment(x, y, end[0], end[1], rw, rh, clip)


def _anchor(pos: float, size: int, limit: int) -> float:
    """К какому краю прижат прямоугольник вдоль оси: 0, 1 или 0,5."""
    if pos <= _EPS:
        return 0.0
    if pos >= limit - size - _EPS:
        return 1.0
    return 0.5


def plan_timed(width: int, height: int, size, seed: int, budget: float,
               clip_at=None) -> list[Segment]:
    """Путь длиной около budget пикселей, который кончается вылетом за край.

    size(clip) → (w, h) прямоугольника; clip_at(i) → клип i-го отрезка или
    None (остаётся прежний). Размер не растёт (просьба пользователя): форма
    меняется лишь под новый клип. Пока до конца далеко, прямоугольник
    отскакивает туда, где больше чёрного; когда оставшегося пути хватает на
    вылет, он улетает за край кадра и к концу времени скрывается целиком.
    Что не успел облететь, так и остаётся чёрным.
    """
    rng = random.Random(seed)
    cover = Coverage(width, height)
    clip = clip_at(0) if clip_at else None
    rw, rh = size(clip)
    x = rng.uniform(0, width - rw)
    y = rng.uniform(0, height - rh)
    angle = math.radians(rng.uniform(30, 60))
    direction = (math.cos(angle) * rng.choice((-1, 1)),
                 math.sin(angle) * rng.choice((-1, 1)))
    path: list[Segment] = []
    travelled = 0.0
    seg = _segment(x, y, direction, rw, rh, width, height, clip)
    while True:
        out = _exit_segment(cover, seg, budget - travelled)
        if out is not None or len(path) >= MAX_SEGMENTS - 1:
            path.append(out or _exit_segment(cover, seg, 0.0))
            return path
        cover.mark(seg)
        path.append(seg)
        travelled += seg.length
        if clip_at is not None:
            clip = clip_at(len(path)) or clip
        nw, nh = size(clip)
        seg = _bounce(cover, seg, nw, nh, clip, rng)


def _exit_length(x, y, d, rw, rh, width, height) -> float:
    """Сколько пролететь по d, чтобы прямоугольник целиком ушёл за край."""
    t = math.inf
    if d[0] > _EPS:
        t = min(t, (width - x) / d[0])
    elif d[0] < -_EPS:
        t = min(t, (x + rw) / -d[0])
    if d[1] > _EPS:
        t = min(t, (height - y) / d[1])
    elif d[1] < -_EPS:
        t = min(t, (y + rh) / -d[1])
    return t


def _exit_segment(cover: Coverage, seg: Segment, remaining: float):
    """Вылет из начала seg, если оставшегося пути на него хватает, иначе None.

    Направление выбирается так, чтобы длина вылета была ближе всего к
    remaining (из почти равных — открывающее больше чёрного); прежнее
    направление тоже в списке — тогда прямоугольник пролетает сквозь стенку.
    """
    width, height = cover.width, cover.height
    x, y, rw, rh = seg.x0, seg.y0, seg.w, seg.h
    own = seg.length
    own_dir = ((seg.x1 - x) / own, (seg.y1 - y) / own) if own > _EPS else None
    dirs = [(math.cos(math.radians(a)), math.sin(math.radians(a)))
            for a in range(0, 360, 2)]
    if own_dir is not None:
        dirs.append(own_dir)
    options = [(_exit_length(x, y, d, rw, rh, width, height), d) for d in dirs]
    options = [(t, d) for t, d in options if math.isfinite(t)]
    if remaining > max(t for t, _ in options):
        return None
    miss = min(abs(t - remaining) for t, _ in options)
    tol = miss + 0.03 * max(remaining, min(width, height))
    best, best_gain = None, -1
    for t, d in options:
        if abs(t - remaining) > tol:
            continue
        # Без плавной смены формы: она прижимает прямоугольник к кадру.
        out = Segment(x, y, x + d[0] * t, y + d[1] * t, rw, rh, seg.clip)
        gained = cover.gain(out)
        if gained > best_gain:
            best, best_gain = out, gained
    return best


def _bounce(cover: Coverage, prev: Segment, nw: int, nh: int, clip, rng):
    """Следующий отрезок после отскока: новая форма прижата к той же стенке."""
    width, height = cover.width, cover.height
    ax = _anchor(prev.x1, prev.w, width)
    ay = _anchor(prev.y1, prev.h, height)
    x = prev.x1 + (prev.w - nw) * ax
    y = prev.y1 + (prev.h - nh) * ay
    x = min(max(0.0, x), float(width - nw))
    y = min(max(0.0, y), float(height - nh))
    direction = _best_direction(cover, x, y, nw, nh, rng)
    if direction is None:
        # Всё открыто (долгий ролик): обычный зеркальный отскок.
        dx, dy = prev.x1 - prev.x0, prev.y1 - prev.y0
        norm = math.hypot(dx, dy) or 1.0
        dx, dy = dx / norm, dy / norm
        if x <= _EPS or x >= width - nw - _EPS:
            dx = -dx
        if y <= _EPS or y >= height - nh - _EPS:
            dy = -dy
        direction = (dx, dy)
    seg = _segment(x, y, direction, nw, nh, width, height, clip)
    if seg is None:
        seg = _segment(x, y, (-direction[0], -direction[1]), nw, nh,
                       width, height, clip)
    if seg is not None and (nw, nh) != (prev.w, prev.h):
        seg.pw, seg.ph, seg.ax, seg.ay = prev.w, prev.h, ax, ay
        seg.morph = min(_MORPH * min(width, height), 0.6 * seg.length)
    return seg


def _best_direction(cover: Coverage, x, y, rw, rh, rng):
    """Направление после отскока, открывающее больше всего на единицу пути."""
    width, height = cover.width, cover.height
    candidates = []
    jitter = rng.uniform(-4, 4)
    for base in _ANGLES:
        a = math.radians(base + jitter)
        for sx in (-1, 1):
            for sy in (-1, 1):
                candidates.append((math.cos(a) * sx, math.sin(a) * sy))
    dark = cover.dark_centres()
    if len(dark):
        near = np.argmin(np.hypot(dark[:, 0] - x - rw / 2, dark[:, 1] - y - rh / 2))
        picks = {int(near)}
        for _ in range(min(_AIMED, len(dark))):
            picks.add(rng.randrange(len(dark)))
        for i in sorted(picks):
            tx = min(max(0.0, dark[i, 0] - rw / 2), float(width - rw))
            ty = min(max(0.0, dark[i, 1] - rh / 2), float(height - rh))
            dx, dy = tx - x, ty - y
            norm = math.hypot(dx, dy)
            if norm > _EPS:
                candidates.append((dx / norm, dy / norm))
    # Короткие перелёты из угла в угол выглядят суетой: длина пути учитывается
    # с «накладными» на каждый отскок.
    overhead = 0.25 * min(width, height)
    best, best_score = None, -1.0
    for d in candidates:
        seg = _segment(x, y, d, rw, rh, width, height)
        if seg is None:
            continue
        gained = cover.gain(seg)
        if not gained:
            continue
        slope = abs(math.sin(2 * math.atan2(abs(d[1]), abs(d[0]))))
        score = gained / (seg.length + overhead) * (0.8 + 0.2 * slope)
        if score > best_score:
            best, best_score = d, score
    return best


def path_length(path: list[Segment]) -> float:
    return sum(seg.length for seg in path)
