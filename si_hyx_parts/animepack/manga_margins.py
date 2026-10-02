# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Remove large monochrome gutters, retaining small intentional margins."""
import math

from PIL import Image, ImageStat


def _blank(line):
    stats = ImageStat.Stat(line)
    histogram = line.histogram()
    pixels = line.width * line.height
    # Even a thin outline or a few letters are content. A white speech
    # bubble must survive trimming, including the part outside its panel.
    empty = max(sum(histogram[245:]), sum(histogram[:10])) >= pixels * .999
    return empty or (stats.stddev[0] < 2
                      and (stats.mean[0] >= 242 or stats.mean[0] <= 13))


def trim(picture, max_ratio=None):
    if min(picture.size) == 0:
        return picture
    preview = picture.convert("L")
    preview.thumbnail((320, 2048), Image.Resampling.BOX)
    width, height = preview.size
    rows = [_blank(preview.crop((0, y, width, y + 1))) for y in range(height)]
    cols = [_blank(preview.crop((x, 0, x + 1, height))) for x in range(width)]

    def edges(blank, size):
        first = next((i for i, b in enumerate(blank) if not b), 0)
        last = next((size - i for i, b in enumerate(reversed(blank)) if not b), size)
        # Keep narrow page borders; trim only visibly excessive blank space.
        pad = max(2, round(size * .015))
        return (max(0, first - pad) if first > size * .06 else 0,
                min(size, last + pad) if size - last > size * .06 else size)

    top, bottom = edges(rows, height)
    left, right = edges(cols, width)
    if max_ratio:
        needed = min(width, math.ceil((bottom - top) / max_ratio) + 1)
        if right - left < needed:
            left = max(0, min(width - needed, round((left + right - needed) / 2)))
            right = left + needed
    bounds = (round(left * picture.width / width), round(top * picture.height / height),
              round(right * picture.width / width), round(bottom * picture.height / height))
    return picture.crop(bounds)


def has_large_gap(picture):
    """Two unrelated fragments separated by a large white/black gutter."""
    preview = picture.convert("L")
    preview.thumbnail((256, 1024), Image.Resampling.BOX)
    run = 0
    for y in range(preview.height):
        run = run + 1 if _blank(preview.crop((0, y, preview.width, y + 1))) else 0
        if run > max(preview.height * .22, preview.width * .3):
            return True
    return False
