# -*- coding: utf-8 -*-
"""Новые эффекты раскрытия: каждая ступень узнаваемее, финал — исходник."""
import math

import pytest
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

from frame_reveal import ANIMATED_EFFECTS, EFFECT_LABELS, LEGACY_EFFECTS, RevealRenderer

NEW = [k for k in EFFECT_LABELS if k not in LEGACY_EFFECTS]


@pytest.fixture
def picture():
    image = Image.new("RGB", (320, 180), "#3872ba")
    draw = ImageDraw.Draw(image)
    for x in range(0, 320, 12):
        draw.rectangle((x, 0, x + 5, 179), fill=(x * 3 // 4, 180, 255 - x * 3 // 4))
    draw.ellipse((100, 24, 220, 164), fill="#f4c897", outline="#282133", width=4)
    draw.rectangle((130, 70, 142, 86), fill="#101010")
    draw.rectangle((178, 70, 190, 86), fill="#101010")
    return image


def error(original, frame):
    return sum(ImageStat.Stat(ImageChops.difference(original, frame)).mean)


def shape_error(original, frame):
    """Разница крупных форм. Попиксельная «рябит» у волн и спирали: сдвиг
    на полпериода полосатого фона даёт больше расхождения, чем сдвиг целиком."""
    blur = ImageFilter.GaussianBlur(6)
    return error(original.filter(blur), frame.filter(blur))


def stages(image, effect, **kw):
    renderer = RevealRenderer(image, effect, **kw)
    return [renderer.render(i / 5) for i in range(6)]


@pytest.mark.parametrize("effect", NEW)
def test_new_effect_is_repeatable_and_ends_clean(picture, effect):
    frames = stages(picture, effect, seed=11)
    assert all(im.size == picture.size and im.mode == "RGB" for im in frames)
    assert error(picture, frames[0]) > 20
    # DVD-заставка полный кадр в конце не показывает (необлетённое чёрное).
    assert (frames[-1].tobytes() == picture.tobytes()) != (effect in ANIMATED_EFFECTS)
    assert [im.tobytes() for im in stages(picture, effect, seed=11)] == \
        [im.tobytes() for im in frames]


@pytest.mark.parametrize("effect", [k for k in NEW if not k.startswith("puzzle")])
@pytest.mark.parametrize("seed", [1, 7])
def test_every_step_is_closer_to_original(picture, effect, seed):
    errors = [shape_error(picture, im) for im in stages(picture, effect, seed=seed)]
    assert all(a > b for a, b in zip(errors, errors[1:])), errors


@pytest.mark.parametrize("effect", [k for k in NEW if not k.startswith("puzzle")])
def test_more_strength_hides_more(picture, effect):
    light = RevealRenderer(picture, effect, strength=10, seed=3).render(0)
    hard = RevealRenderer(picture, effect, strength=100, seed=3).render(0)
    assert shape_error(picture, hard) > shape_error(picture, light)


def _pieces_home(renderer, picture, progress):
    frame = renderer.render(progress)
    return {i for i, box in enumerate(renderer.external.boxes)
            if frame.crop(box).tobytes() == picture.crop(box).tobytes()}


@pytest.mark.parametrize("effect", ["puzzle", "puzzle_center"])
def test_puzzle_places_more_pieces_each_step(effect):
    # Шум без повторов: ни один кусок не совпадает с чужой ячейкой.
    picture = Image.effect_noise((320, 180), 80).convert("RGB")
    renderer = RevealRenderer(picture, effect, seed=5)
    total = len(renderer.external.boxes)
    homes = [_pieces_home(renderer, picture, i / 5) for i in range(6)]
    assert homes[0] == set()
    assert all(a < b for a, b in zip(homes, homes[1:]))
    assert len(homes[-2]) <= total - 2 and len(homes[-1]) == total


def test_puzzle_from_center_starts_in_the_middle():
    picture = Image.effect_noise((320, 180), 80).convert("RGB")
    renderer = RevealRenderer(picture, "puzzle_center", seed=5)
    first = _pieces_home(renderer, picture, 0.2)
    later = _pieces_home(renderer, picture, 0.6) - first

    def distance(i):
        x0, y0, x1, y1 = renderer.external.boxes[i]
        return math.hypot((x0 + x1) / 320 - 1, (y0 + y1) / 180 - 1)

    assert max(map(distance, first)) <= min(map(distance, later)) + 1e-9


def test_thumbnail_keeps_whole_frame_small_on_black():
    picture = Image.new("RGB", (640, 360), "white")
    frame = RevealRenderer(picture, "thumbnail", seed=1).render(0)
    box = frame.convert("L").point(lambda v: 255 if v > 128 else 0).getbbox()
    assert box is not None
    width, height = box[2] - box[0], box[3] - box[1]
    assert width / height == pytest.approx(640 / 360, rel=0.1)
    assert abs((box[0] + box[2]) / 2 - 320) <= 1
    assert width * height / (640 * 360) < 0.03


def test_dark_and_overexposed_start_near_black_and_white(picture):
    dark = RevealRenderer(picture, "dark", seed=1).render(0)
    light = RevealRenderer(picture, "overexposed", seed=1).render(0)
    assert ImageStat.Stat(dark.convert("L")).mean[0] < 20
    assert ImageStat.Stat(light.convert("L")).mean[0] > 220
