# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Distinguish a colored scene from white captions and speech-only gutters."""
from PIL import Image


def trim_fragments(picture):
    """Drop short neighboring-panel scraps across a solid horizontal gutter."""
    preview = picture.convert("L")
    preview.thumbnail((320, 2048), Image.Resampling.BOX)
    width, height = preview.size
    gaps, start, black_boundary = [], None, False
    for y in range(height + 1):
        blank = False
        dark = False
        if y < height:
            histogram = preview.crop((0, y, width, y + 1)).histogram()
            dark = sum(histogram[:64]) >= width * .97
            blank = sum(histogram[245:]) >= width * .985 or dark
        if blank and start is None:
            start = y
        black_boundary = black_boundary or dark
        if not blank and start is not None:
            if ((black_boundary or y - start >= max(3, round(width * .015)))
                    and start > height * .06 and y < height * .94):
                gaps.append((start, y))
            start = None
            black_boundary = False
    if not gaps:
        return picture
    spans = []
    top = 0
    for first, last in gaps:
        spans.append((top, first))
        top = last
    spans.append((top, height))
    first, last = max(spans, key=lambda span: span[1] - span[0])
    # Preserve multiple substantial panels. Only strip small attached scraps.
    if last - first < height * .5 or first > height * .25 or height - last > height * .25:
        return picture
    return picture.crop((0, round(first * picture.height / height), picture.width,
                         round(last * picture.height / height)))


def trim_captions(picture):
    preview = picture.convert("RGB")
    preview.thumbnail((256, 1024), Image.Resampling.BOX)
    width, height = preview.size
    if min(width, height) == 0:
        return picture
    pixels = list(preview.getdata())
    colored = [sum(max(p) - min(p) >= 12 for p in pixels[y * width:(y + 1) * width])
               >= width * .08 for y in range(height)]
    bands = []
    first = last = None
    gap = max(2, round(width * .08))
    for y, drawing in enumerate(colored):
        if not drawing:
            continue
        if last is not None and y - last > gap:
            bands.append((first, last + 1))
            first = None
        if first is None:
            first = y
        last = y
    if first is not None:
        bands.append((first, last + 1))
    if not bands:
        return picture  # monochrome pages use the usual margin detector
    first, last = max(bands, key=lambda span: span[1] - span[0])
    if last - first < height * .15:
        return picture

    def white(start, end):
        region = pixels[start * width:end * width]
        return bool(region) and sum(min(p) >= 242 for p in region) >= len(region) * .8

    pad = max(2, round(width * .03))
    top = max(0, first - pad) if first > height * .12 and white(0, first) else 0
    bottom = (min(height, last + pad)
              if height - last > height * .12 and white(last, height) else height)
    return picture.crop((0, round(top * picture.height / height), picture.width,
                         round(bottom * picture.height / height)))
