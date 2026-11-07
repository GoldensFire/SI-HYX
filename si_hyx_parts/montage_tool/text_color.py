# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Цвет текста под план: style.color "auto" в операциях text, words,
lyrics и columns. Public namespace: montage_tool.

Цвет — главный тон кадра (стиль rcn: красное слово на красном плане,
стально-синее на синем). Кадр — исходник клипа основной дорожки (или
заданный кусок) на времени текста, 96×54, без эффектов проекта. Тон —
пик гистограммы оттенков по насыщенным пикселям (вес — насыщенность ×
яркость). На тёмном или среднем кадре слово яркое: насыщенность тона, не
меньше 0,65, яркость под светлоту ~0,42 (замер эталона: #f52e33, #ed5806,
#3373a8, #d96f0d). На светлом кадре — тёмный того же тона, светлота ~0,14
(#731200 на светлом оранжевом). Кадр без выраженного тона — белый (на
светлом кадре — почти чёрный)."""
import colorsys
import subprocess

import numpy as np

import montage_tool as _api

AUTO = "auto"
_W, _H = 96, 54
BRIGHT_FRAME = 0.46          # средняя светлота кадра, выше — слово тёмное
BRIGHT_LUMA, DARK_LUMA = 0.42, 0.14
MIN_SAT, MAX_SAT = 0.65, 0.92
TONE_SHARE = 0.04            # доля веса насыщенных пикселей, ниже — тона нет
NEUTRAL_LIGHT, NEUTRAL_DARK = "#f4f4f4", "#141414"
_cache = {}


def frame_rgb(src, t):
    """Кадр файла src на секунде t: массив 54×96×3 (uint8) или None."""
    key = (_api.os.path.abspath(str(src)), round(float(t), 3))
    if key in _cache:
        return _cache[key]
    cmd = [_api.FFMPEG, "-v", "error", "-nostdin", "-ss", f"{max(0.0, float(t)):.3f}",
           "-i", key[0], "-map", "0:v:0", "-frames:v", "1",
           "-vf", f"scale={_W}:{_H}:flags=area,format=rgb24", "-f", "rawvideo", "-"]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=60,
                             creationflags=_api.CREATE_NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        out = b""
    img = np.frombuffer(out, np.uint8).reshape(_H, _W, 3) if len(out) == _W * _H * 3 else None
    _cache[key] = img
    return img


def _luma(rgb):
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _hex(rgb):
    return "#" + "".join(f"{int(round(max(0.0, min(1.0, c)) * 255)):02x}" for c in rgb)


def _tone(h, s, luma):
    """Цвет оттенка h с насыщенностью s и светлотой ~luma (яркость ≤ 1)."""
    full = colorsys.hsv_to_rgb(h, s, 1.0)
    v = min(1.0, luma / max(_luma(full), 1e-6))
    return _hex(colorsys.hsv_to_rgb(h, s, v))


def text_color(img):
    """Цвет слова для кадра img (H×W×3 uint8; None — белый)."""
    if img is None:
        return NEUTRAL_LIGHT
    px = img.reshape(-1, 3).astype(np.float64) / 255.0
    mx, mn = px.max(axis=1), px.min(axis=1)
    sat = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    lum = px @ np.array([0.2126, 0.7152, 0.0722])
    bright = float(lum.mean()) > BRIGHT_FRAME
    weight = sat * mx * (sat > 0.25)
    if weight.sum() < TONE_SHARE * len(px):
        return NEUTRAL_DARK if bright else NEUTRAL_LIGHT
    r, g, b = px[:, 0], px[:, 1], px[:, 2]
    hue = np.zeros(len(px))
    d = np.maximum(mx - mn, 1e-6)
    hue = np.where(mx == r, ((g - b) / d) % 6.0, hue)
    hue = np.where(mx == g, (b - r) / d + 2.0, hue)
    hue = np.where(mx == b, (r - g) / d + 4.0, hue)
    bins = (hue / 6.0 * 36).astype(int) % 36
    hist = np.bincount(bins, weights=weight, minlength=36)
    smooth = hist + 0.5 * (np.roll(hist, 1) + np.roll(hist, -1))
    peak = int(np.argmax(smooth))
    near = np.isin(bins, [(peak - 1) % 36, peak, (peak + 1) % 36]) & (weight > 0)
    # Оттенок пика — круговым средним по его корзинам, насыщенность — средним.
    ang = hue[near] / 6.0 * 2 * np.pi
    w = weight[near]
    h = (np.arctan2((np.sin(ang) * w).sum(), (np.cos(ang) * w).sum()) / (2 * np.pi)) % 1.0
    s_dom = float((sat[near] * w).sum() / w.sum())
    if bright:
        return _tone(h, 1.0, DARK_LUMA)
    return _tone(h, max(MIN_SAT, min(MAX_SAT, s_dom)), BRIGHT_LUMA)


def _source_time(c, t):
    """Секунда исходника клипа c на времени проекта t."""
    if c.frozen:
        return c.freeze_at
    if c.is_image:
        return 0.0
    k = (t - c.start) * c.play_speed
    return max(0.0, c.out_s - k) if c.reverse else c.in_s + k


def auto_text_color(p, t):
    """Цвет слова под кадр основной дорожки на времени t проекта."""
    fps = p.output_format()[2]
    c = p.clip_at(p.main_track, t + 0.5 / fps)
    if c is None or not c.has_video:
        return NEUTRAL_LIGHT
    return text_color(frame_rgb(c.src, _source_time(c, t + 0.5 / fps)))


def resolve_auto_colors(p, raw):
    """Тексты raw (словари parse_texts) с style.color "auto" — цвет под план
    на их начале (на месте, без копий словарей стиля других текстов)."""
    for r in raw:
        st = r.get("style")
        if isinstance(st, dict) and st.get("color") == AUTO:
            r["style"] = dict(st, color=auto_text_color(p, float(r["start"])))
    return raw
