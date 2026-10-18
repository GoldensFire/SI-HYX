"""Legible static typography and a fresh, bright sweep colour per song."""
from pathlib import Path
import random

FONT_DIR = Path(__file__).resolve().parent / "fonts"
FONT_FILE = FONT_DIR / "Nunito-Black.ttf"
FONT_NAME = "Karaoke Rounded"
COLOURS = {
    "cyan": "25E7FF", "blue": "579FFF", "purple": "BE83FF",
    "pink": "FF73C8", "red": "FF626B", "orange": "FFAD46",
    "yellow": "FFE64D", "lime": "B6F542", "green": "51EB85",
}
# Текст без подсветки (перевод, ещё не спетые слоги) — почти белый, с тёмной
# обводкой и полупрозрачной тенью. Тот же вид у программных субтитров вкладки
# «Монтаж» (edit_tab_base.prog_sub_force_style), поэтому значения здесь одни.
# OUTLINE и SHADOW заданы для кегля BASE_SIZE = font_size(720): у субтитров
# Монтажа кегль меньше, и они берутся пропорционально.
TEXT_COLOUR = "FFF8F8"
OUTLINE_COLOUR = "161010"
SHADOW_ALPHA = 0x70          # прозрачность тени в ASS: 00 — сплошная, FF — нет
OUTLINE = 5
SHADOW = 1.5
BASE_SIZE = 64


def choose_colour(rng=None):
    return (rng or random.SystemRandom()).choice(tuple(COLOURS.values()))


def ass_rgb(rgb, alpha=0):
    """«RRGGBB» → цвет ASS «&HAABBGGRR»."""
    return f"&H{alpha:02X}" + rgb[4:6] + rgb[2:4] + rgb[:2]


def ass_colour(rgb):
    if rgb not in COLOURS.values():
        raise ValueError("Недопустимый цвет karaoke-подсветки.")
    return ass_rgb(rgb)


def font_size(height):
    return max(28, round(height / 11.25))


def fitted_size(text, width, size):
    # PIL — только здесь: стиль импортирует и вкладка «Монтаж» ради цветов.
    from PIL import ImageFont
    font = ImageFont.truetype(str(FONT_FILE), size)
    measured = font.getlength(text)
    return min(size, max(1, int(size * (width - 96) / max(1, measured))))
