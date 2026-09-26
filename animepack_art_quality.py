# -*- coding: utf-8 -*-
"""Reject obvious unfinished white lower panels without cropping the artwork."""
import io

from PIL import Image
from cloudflare_art_api import CloudflareArtError


def validate_art_composition(data):
    with Image.open(io.BytesIO(data)) as image:
        image = image.convert("RGB").resize((128, 128))
        # Require an almost entirely white lower fifth, but actual artwork above.
        def white_fraction(box):
            pixels = list(image.crop(box).getdata())
            return sum(min(pixel) >= 245 for pixel in pixels) / len(pixels)

        if (white_fraction((0, 103, 128, 128)) > 0.985
                and white_fraction((0, 0, 128, 90)) < 0.8):
            raise CloudflareArtError(
                "ИИ-арт содержит большую пустую белую область снизу; тайтл пропущен.")
