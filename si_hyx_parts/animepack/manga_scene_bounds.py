# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Expand a proposed scene to empty gutters on the original full-width strip."""
from PIL import Image

from .manga_margins import _blank


def expand(picture, bounds, max_ratio):
    """Never cut a panel sideways or stop through a face or speech bubble.

    A thin panel border is not a separator: dialogue can extend beyond it.
    If no safe gutter fits near the proposed scene, leave it for rejection
    instead of imposing a fixed-height crop through the drawing.
    """
    width, height = picture.size
    _, top, _, bottom = bounds
    reach = round(width * max_ratio)
    first, last = max(0, top - reach), min(height, bottom + reach)
    preview = picture.crop((0, first, width, last)).convert("L")
    if width > 768:
        preview = preview.resize((768, preview.height), Image.Resampling.BOX)
    minimum = max(4, round(width * .0125))
    gaps, start = [], None
    for y in range(preview.height + 1):
        empty = y < preview.height and _blank(
            preview.crop((0, y, preview.width, y + 1)))
        if empty and start is None:
            start = y
        if not empty and start is not None:
            if y - start >= minimum:
                gaps.append((first + start, first + y))
            start = None
    above = [gap for gap in gaps if gap[0] <= top]
    below = [gap for gap in gaps if gap[1] >= bottom]
    pad = max(2, round(width * .015))
    if above:
        top = max(0, min(top, above[-1][1]) - pad)
    elif first == 0 and _blank(preview.crop((0, 0, preview.width, 1))):
        top = 0
    else:
        return None
    if below:
        bottom = min(height, max(bottom, below[0][0]) + pad)
    elif last == height and _blank(preview.crop(
            (0, preview.height - 1, preview.width, preview.height))):
        bottom = height
    else:
        return None
    # A gap earlier in the proposed box does not make the source edge safe.
    # Readers often end a file through a face or the middle of a speech bubble.
    if ((top == 0 and not _blank(preview.crop((0, 0, preview.width, 1))))
            or (bottom == height and not _blank(preview.crop(
                (0, preview.height - 1, preview.width, preview.height))))):
        return None
    return 0, top, width, bottom
