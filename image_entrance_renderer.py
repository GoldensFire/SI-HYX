# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Общий покадровый рендер для предпросмотра и настоящего медиа в паке."""
from image_entrance import EFFECT_LABELS
from image_entrance_motion import render_motion
from image_entrance_reveal import render_reveal

REVEALS = ("split", "clone", "mosaic", "star", "ripple", "explosion")


def render(image, effect, progress, strength=70, seed=0):
    if effect not in EFFECT_LABELS:
        raise ValueError("Неизвестный эффект появления: " + str(effect))
    image = image.convert("RGB")
    p = max(0.0, min(1.0, float(progress)))
    if p >= 1:
        return image.copy()
    amount = max(10, min(100, int(strength))) / 100
    if effect in REVEALS:
        return render_reveal(image, effect, p, amount, seed)
    return render_motion(image, effect, p, amount)
