"""Find complete drawing bands between wide blank gutters before AI work."""
import numpy as np
from PIL import Image


def windows(picture, maximum):
    width, height = picture.size
    scale = min(1.0, 384 / width)
    preview = picture.convert("L").resize(
        (max(1, round(width * scale)), max(1, round(height * scale))), Image.Resampling.BOX)
    pixels = np.asarray(preview, dtype=np.float32)
    average, spread = pixels.mean(axis=1), pixels.std(axis=1)
    empty = (spread < 7) & ((average > 245) | (average < 10))
    changes = np.flatnonzero(np.diff(np.r_[False, empty, False].astype(np.int8)))
    gaps = [(int(a / scale), int(b / scale)) for a, b in zip(changes[::2], changes[1::2])
            if b - a >= max(3, round(width * scale * .0125))]
    options = []
    for first, last in zip(gaps, gaps[1:]):
        top, bottom = first[1], last[0]
        ratio = (bottom - top) / width
        if not .4 <= ratio <= 3.1:
            continue
        band = pixels[max(0, round(top * scale)):min(len(pixels), round(bottom * scale))]
        if band.size == 0 or float(band.std()) < 10:
            continue
        bounds = (0, max(0, top - round(width * .02)), width,
                  min(height, bottom + round(width * .02)))
        options.append((abs(ratio - 1.3), bounds))
    # A lone detected band is weak evidence; preserve the full source search.
    if len(options) < 2:
        return []
    return [box for _, box in sorted(options)[:maximum]]
