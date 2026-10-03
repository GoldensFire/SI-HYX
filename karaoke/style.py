"""Legible static typography and a fresh, bright sweep colour per song."""
from pathlib import Path
import random

from PIL import ImageFont

FONT_DIR = Path(__file__).resolve().parent / "fonts"
FONT_FILE = FONT_DIR / "Nunito-Black.ttf"
FONT_NAME = "Karaoke Rounded"
COLOURS = {
    "cyan": "25E7FF", "blue": "579FFF", "purple": "BE83FF",
    "pink": "FF73C8", "red": "FF626B", "orange": "FFAD46",
    "yellow": "FFE64D", "lime": "B6F542", "green": "51EB85",
}


def choose_colour(rng=None):
    return (rng or random.SystemRandom()).choice(tuple(COLOURS.values()))


def ass_colour(rgb):
    if rgb not in COLOURS.values():
        raise ValueError("Недопустимый цвет karaoke-подсветки.")
    return "&H00" + rgb[4:6] + rgb[2:4] + rgb[:2]


def font_size(height):
    return max(28, round(height / 11.25))


def fitted_size(text, width, size):
    font = ImageFont.truetype(str(FONT_FILE), size)
    measured = font.getlength(text)
    return min(size, max(1, int(size * (width - 96) / max(1, measured))))
