"""Crop and tempo transformations, independent of audio filter implementation."""
from __future__ import annotations

import math
from .model import Line, Unit, validate


def transform(lines, *, crop_start=0.0, crop_end=None, tempo=1.0,
              offset=0.0, reverse=False):
    if reverse:
        return []
    if not math.isfinite(tempo) or tempo <= 0:
        raise ValueError("Темп должен быть положительным числом.")
    if not math.isfinite(crop_start) or crop_start < 0:
        raise ValueError("Неверное начало отрезка.")
    limit = float(crop_end) if crop_end is not None else float("inf")
    if limit <= crop_start or not math.isfinite(offset):
        raise ValueError("Неверные границы отрезка.")
    result = []
    for line in lines:
        start, end = line.start + offset, line.end + offset
        if end <= crop_start or start >= limit:
            continue
        units = []
        # Keep the complete phrase; syllables sung before the crop get \kf0.
        # This avoids losing the meaning of a phrase cut in the middle.
        for unit in line.units:
            a = min(limit, max(crop_start, unit.start + offset))
            b = min(limit, max(crop_start, unit.end + offset))
            units.append(Unit((a - crop_start) / tempo,
                              (b - crop_start) / tempo, unit.text))
        result.append(Line(max(0, (start - crop_start) / tempo),
                           (min(end, limit) - crop_start) / tempo,
                           units, dict(line.translations)))
    return validate(result) if result else []
