# -*- coding: utf-8 -*-
"""Визуальные инварианты: раскрытое не исчезает, финал равен исходнику."""
import random

import pytest
from PIL import Image, ImageChops, ImageDraw, ImageStat

from frame_reveal import (ANIMATED_EFFECTS, EFFECT_LABELS, RevealRenderer, choose_effect,
                          clean_effects, stage_frame_counts)


@pytest.fixture
def picture():
    image = Image.new("RGB", (160, 90), "#3872ba")
    draw = ImageDraw.Draw(image)
    for x in range(0, 160, 10):
        draw.rectangle((x, 0, x + 5, 89), fill=(x, 180, 255 - x))
    draw.ellipse((48, 12, 116, 82), fill="#f4c897", outline="#282133", width=3)
    draw.rectangle((65, 36, 70, 43), fill="black")
    draw.rectangle((95, 36, 100, 43), fill="black")
    return image


@pytest.mark.parametrize("effect", [k for k in EFFECT_LABELS if k != "pixelize"])
def test_stages_are_repeatable_and_finish_with_original(picture, effect):
    renderer = RevealRenderer(picture, effect, seed=42)
    stages = [renderer.render(i / 5) for i in range(6)]
    assert all(im.size == picture.size and im.mode == "RGB" for im in stages)
    assert stages[0].tobytes() != picture.tobytes()
    # DVD-заставка полный кадр в конце не показывает (необлетённое чёрное).
    assert (stages[-1].tobytes() == picture.tobytes()) != (effect in ANIMATED_EFFECTS)
    assert renderer.render(0).tobytes() == stages[0].tobytes()
    again = RevealRenderer(picture, effect, seed=42)
    assert [again.render(i / 5).tobytes() for i in range(6)] == [im.tobytes() for im in stages]


@pytest.mark.parametrize("effect", ["tiles", "window"])
@pytest.mark.parametrize("seed", [1, 2, 10])
def test_revealed_pixels_never_get_hidden_again(picture, effect, seed):
    renderer = RevealRenderer(picture, effect, seed=seed)
    original = list(picture.get_flattened_data())
    previous = set()
    for step in range(6):
        frame = list(renderer.render(step / 5).get_flattened_data())
        visible = {i for i, (a, b) in enumerate(zip(original, frame)) if a == b}
        assert previous < visible
        previous = visible
    assert len(previous) == picture.width * picture.height


@pytest.mark.parametrize("effect", ["zoom"])
def test_visual_error_decreases_as_frame_clears(picture, effect):
    renderer = RevealRenderer(picture, effect)
    errors = [sum(ImageStat.Stat(ImageChops.difference(
        picture, renderer.render(i / 5))).mean) for i in range(6)]
    assert errors == sorted(errors, reverse=True)
    assert errors[0] > 0 and errors[-1] == 0


@pytest.mark.parametrize("effect", ["tiles", "window", "zoom"])
def test_more_strength_hides_more(picture, effect):
    light = RevealRenderer(picture, effect, strength=10, seed=3).render(0)
    hard = RevealRenderer(picture, effect, strength=100, seed=3).render(0)
    error = lambda im: sum(ImageStat.Stat(ImageChops.difference(picture, im)).mean)
    assert error(hard) > error(light)


def test_random_draw_is_limited_to_selection_and_reproducible():
    def draw(seed):
        rng = random.Random(seed)
        return [choose_effect("random", ["tiles", "window", "zoom"], rng) for _ in range(50)]
    assert set(draw(42)) == {"tiles", "window", "zoom"}
    assert draw(42) == draw(42)
    assert draw(42) != draw(43)
    assert choose_effect("zoom", [], random.Random()) == "zoom"
    with pytest.raises(ValueError, match="хотя бы один"):
        choose_effect("random", [], random.Random())


def test_invalid_selection_is_not_silently_used():
    assert clean_effects(["tiles", {}, "tiles", "missing", "noise", "zoom"]) == ["tiles", "zoom"]
    assert clean_effects("tiles") == []
    with pytest.raises(ValueError, match="неизвестный"):
        choose_effect("missing", [], random.Random())


@pytest.mark.parametrize("seconds,fps,steps", [(12, 10, 6), (7, 7, 6), (2, 1, 20), (2, 1, 1)])
def test_stage_timing_is_exact_even_at_low_fps(seconds, fps, steps):
    counts = stage_frame_counts(seconds, fps, steps)
    assert sum(counts) == seconds * fps
    assert len(counts) >= 2
    assert min(counts) >= 1
    assert max(counts) - min(counts) <= 1
    if seconds == 12:
        assert counts == [20] * 6


def test_window_starts_at_details_not_empty_background():
    image = Image.new("RGB", (160, 90), "#777777")
    draw = ImageDraw.Draw(image)
    for x in range(90, 130, 4):
        draw.line((x, 20, x, 70), fill="black", width=2)
    renderer = RevealRenderer(image, "window", strength=100)
    assert renderer.anchor[0] == 0.7
    center = (round(renderer.anchor[0] * image.width), round(renderer.anchor[1] * image.height))
    assert renderer.render(0).getpixel(center) == image.getpixel(center)


def test_window_has_small_start_and_pure_black_cover():
    from frame_reveal import window_area
    picture = Image.new("RGB", (1280, 720), "white")
    renderer = RevealRenderer(picture, "window")
    for i in range(6):
        frame = renderer.render(i / 5)
        colors = dict((color, count) for count, color in frame.getcolors())
        assert set(colors) <= {(0, 0, 0), (255, 255, 255)}
        visible = colors[(255, 255, 255)] / (picture.width * picture.height)
        assert visible == pytest.approx(window_area(55, i / 5), abs=0.002)
        if i == 0:
            assert 0.07 < visible < 0.08
        if i == 1:
            assert visible < 0.15


def test_zoom_starts_close_and_pulls_back(picture):
    """«Отдаление»: сперва огромная деталь, дальше кадр целиком.

    Просьба пользователя: «в начале мега приближенный кадр, и каждый раз оно
    отдаляется»."""
    renderer = RevealRenderer(picture, "zoom", strength=55, seed=7)
    stages = [renderer.render(i / 5) for i in range(6)]
    # Ни одной чёрной рамки: кадр не прячется, а увеличивается.
    assert all(im.size == picture.size for im in stages)
    errors = [sum(ImageStat.Stat(ImageChops.difference(picture, im)).mean)
              for im in stages]
    assert errors[0] > 0 and errors[-1] == 0
    assert errors == sorted(errors, reverse=True)
    # Чем сильнее эффект, тем ближе первый кадр — то есть дальше от исходника.
    hard = RevealRenderer(picture, "zoom", strength=100, seed=7).render(0)
    light = RevealRenderer(picture, "zoom", strength=10, seed=7).render(0)
    error = lambda im: sum(ImageStat.Stat(ImageChops.difference(picture, im)).mean)
    assert error(hard) > error(light)


def test_closed_tiles_are_small_dark_and_reveal_slowly_at_first():
    picture = Image.new("RGB", (1600, 900), "white")
    renderer = RevealRenderer(picture, "tiles", strength=55, seed=3)
    assert len(set(renderer.mask.get_flattened_data())) >= 140
    frames = [renderer.render(i / 5) for i in range(6)]
    totals = picture.width * picture.height
    covered = [sum(1 for pixel in frame.get_flattened_data()
                   if pixel == (8, 10, 15)) / totals for frame in frames]
    assert covered[0] > 0.75
    assert covered[0] - covered[1] < covered[3] - covered[4]
