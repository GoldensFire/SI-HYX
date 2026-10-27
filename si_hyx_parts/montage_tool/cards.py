# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Фон карточки (титр части, концовка) для op card: card_background.
Public namespace: montage_tool.

spec — ключи CARD_BACKGROUND (все необязательны):
  colors     [c0, c1] — градиент от c0 к c1 (#RRGGBB);
  angle      направление градиента, ° (0 — слева направо, 90 — сверху вниз);
  radial     true — от центра (c1) к краям (c0);
  dots       0…1 — точки табло (растр) цвета c1, ярче там, где фон светлее;
  dot_period шаг точек, px при высоте 1080;
  streaks    0…1 — горизонтальные штрихи цвета c1 (полосы развёртки);
  vignette   0…1 — затемнение краёв;  noise — 0…1, зерно;  seed — узор.
PNG — в folder под хэшем spec и размера кадра: та же карточка — тот же
файл (повторный edit его не перерисовывает)."""
import hashlib
import json
import math
import os
import re

import numpy as np

import montage_tool as _api

CARD_BACKGROUND = {"colors": ["#000000", "#5a0008"], "angle": 160.0, "radial": False,
                   "dots": 0.0, "dot_period": 14.0, "streaks": 0.0, "vignette": 0.35,
                   "noise": 0.03, "seed": 7}
_COLOR_RX = re.compile(r"#[0-9A-Fa-f]{6}")
_UNIT = ("dots", "streaks", "vignette", "noise")


def _rgb(c):
    if not isinstance(c, str) or not _COLOR_RX.fullmatch(c):
        raise ValueError(f"цвет фона — #RRGGBB, не {c!r}")
    return np.array([int(c[i:i + 2], 16) for i in (1, 3, 5)], np.float32)


def _spec(spec):
    bg = dict(CARD_BACKGROUND)
    if spec is not None and not isinstance(spec, dict):
        raise ValueError("background — объект")
    bg.update(spec or {})
    bad = sorted(set(bg) - set(CARD_BACKGROUND))
    if bad:
        raise ValueError(f"background: неизвестные ключи {bad} "
                         f"(есть: {', '.join(CARD_BACKGROUND)})")
    if not isinstance(bg["colors"], list) or len(bg["colors"]) != 2:
        raise ValueError("background.colors — два цвета #RRGGBB")
    for c in bg["colors"]:
        _rgb(c)
    for k in _UNIT:
        bg[k] = min(1.0, max(0.0, float(bg[k])))
    bg["angle"] = float(bg["angle"]) % 360.0
    bg["dot_period"] = min(200.0, max(4.0, float(bg["dot_period"])))
    bg["radial"] = bool(bg["radial"])
    bg["seed"] = int(bg["seed"])
    return bg


def render_background(bg, w, h):
    """Кадр фона [h, w, 3] uint8 по готовому spec (_spec)."""
    c0, c1 = _rgb(bg["colors"][0]), _rgb(bg["colors"][1])
    u = (np.arange(w, dtype=np.float32) + 0.5) / w
    v = (np.arange(h, dtype=np.float32) + 0.5) / h
    uu, vv = np.meshgrid(u, v)
    if bg["radial"]:
        t = 1.0 - np.clip(np.hypot(uu - 0.5, vv - 0.5) / math.sqrt(0.5), 0.0, 1.0)
    else:
        a = math.radians(bg["angle"])
        ca, sa = math.cos(a), math.sin(a)
        p = (uu - 0.5) * ca + (vv - 0.5) * sa
        t = np.clip(p / (0.5 * (abs(ca) + abs(sa))) * 0.5 + 0.5, 0.0, 1.0)
    img = c0 * (1.0 - t[..., None]) + c1 * t[..., None]
    lit = np.clip(c1 * 2.2 + 24.0, 0.0, 255.0)
    if bg["dots"] > 0:
        per = bg["dot_period"] * h / 1080.0
        xx, yy = uu * w, vv * h
        d = np.hypot(np.mod(xx, per) - per / 2.0, np.mod(yy, per) - per / 2.0)
        m = np.clip(0.3 * per - d + 0.5, 0.0, 1.0) * bg["dots"] * t ** 1.5
        img = img * (1.0 - m[..., None]) + lit * m[..., None]
    rng = np.random.default_rng(bg["seed"])
    if bg["streaks"] > 0:
        for _k in range(int(8 + 28 * bg["streaks"])):
            y0 = int(rng.uniform(0.0, h))
            th = max(1, int(round(rng.uniform(1.0, 3.5) * h / 1080.0)))
            x0 = int(rng.uniform(-0.2, 0.8) * w)
            ln = max(8, int(rng.uniform(0.15, 0.6) * w))
            k = rng.uniform(0.3, 1.0) * bg["streaks"]
            xs = np.arange(max(0, x0), min(w, x0 + ln))
            if not len(xs) or y0 >= h:
                continue
            prof = (np.sin(np.pi * (xs - x0) / ln) * k).astype(np.float32)[None, :, None]
            rows = slice(y0, min(h, y0 + th))
            img[rows, xs[0]:xs[-1] + 1] = img[rows, xs[0]:xs[-1] + 1] * (1.0 - prof) + lit * prof
    if bg["vignette"] > 0:
        r = np.clip(np.hypot(uu - 0.5, vv - 0.5) / math.sqrt(0.5), 0.0, 1.0)
        img *= (1.0 - bg["vignette"] * r ** 2)[..., None]
    if bg["noise"] > 0:
        img += rng.normal(0.0, bg["noise"] * 128.0, (h, w, 1)).astype(np.float32)
    return np.clip(img, 0.0, 255.0).astype(np.uint8)


def card_background(spec, w, h, folder):
    """PNG фона карточки w×h в folder (имя — хэш spec и размера) → путь."""
    from PIL import Image
    bg = _spec(spec)
    key = json.dumps({"bg": bg, "w": int(w), "h": int(h)}, sort_keys=True)
    path = os.path.join(folder, f"card_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]}.png")
    if os.path.isfile(path):
        return path
    os.makedirs(folder, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp.png"
    Image.fromarray(render_background(bg, int(w), int(h))).save(tmp)
    os.replace(tmp, path)
    return path


def cards_dir(project_path):
    """Папка карточек проекта: рядом с ним, <имя проекта>_cards."""
    path = _api.os.path.abspath(str(project_path))
    return os.path.join(os.path.dirname(path), os.path.splitext(os.path.basename(path))[0] + "_cards")
