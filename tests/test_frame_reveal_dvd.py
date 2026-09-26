# -*- coding: utf-8 -*-
"""«DVD-заставка»: плавное движение, след не закрывается, форма по файлу."""
import random

import numpy as np
from PIL import Image

from frame_reveal_dvd import DVD_FPS, DvdAnimation
from frame_reveal_dvd_media import FolderMedia, list_media


def _picture(size=(320, 180)):
    rng = np.random.default_rng(1)
    data = rng.integers(20, 255, (size[1], size[0], 3), dtype=np.uint8)
    return Image.fromarray(data, "RGB")


def test_rectangle_moves_every_frame_and_trail_stays_open():
    anim = DvdAnimation(_picture(), 0.55, random.Random(3))
    opened = (anim.frame().sum(axis=2) > 0)
    assert 0 < opened.mean() < 0.2            # старт — почти чёрный экран
    positions = set()
    for _ in range(DVD_FPS * 3):
        anim.step()
        positions.add((round(anim.x), round(anim.y)))
        now = anim.frame().sum(axis=2) > 0
        assert (now | opened).sum() == now.sum()   # открытое не закрылось
        opened = now
    # Движение каждым кадром, а не ступенями раз в пару секунд.
    assert len(positions) > DVD_FPS * 3 * 0.9
    assert opened.mean() > 0.3


def test_same_seed_same_path():
    one = DvdAnimation(_picture(), 0.55, random.Random(9))
    two = DvdAnimation(_picture(), 0.55, random.Random(9))
    for _ in range(40):
        one.step(), two.step()
    assert (one.x, one.y) == (two.x, two.y)


def test_rectangle_takes_the_shape_of_the_media(tmp_path):
    Image.new("RGB", (100, 300), "red").save(tmp_path / "tall.png")
    Image.new("RGB", (400, 100), "blue").save(tmp_path / "wide.webp", lossless=True)
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    files = list_media(str(tmp_path))
    assert len(files) == 2
    media = FolderMedia(files, random.Random(1))
    anim = DvdAnimation(_picture(), 0.55, random.Random(2), media)
    shapes = set()
    for _ in range(DVD_FPS * 8):
        shapes.add(round(anim.rw / anim.rh, 1))
        frame = anim.frame()
        x0, y0 = round(anim.x), round(anim.y)
        # Внутри прямоугольника — сам файл, а не кадр вопроса.
        assert tuple(frame[y0 + 2, x0 + 2]) in ((255, 0, 0), (0, 0, 255))
        anim.step()
    # Каждый отскок меняет файл, а с ним и форму прямоугольника.
    assert min(shapes) < 0.5 and max(shapes) > 3.5


def test_rectangle_keeps_its_size_and_flies_out_by_the_end():
    # Прямоугольник не растёт и кадр не дочищает: к последнему кадру
    # движения он целиком за краем, необлетённое осталось чёрным.
    for size, strength in (((320, 180), 1.0), ((180, 320), 0.1), ((400, 180), 0.55)):
        frames = 90
        anim = DvdAnimation(_picture(size), strength, random.Random(5), None,
                            DVD_FPS, frames)
        sizes = {(seg.w, seg.h) for seg in anim.path}
        assert len(sizes) == 1
        for _ in range(frames - 1):
            anim.step()
        x, y, w, h = anim.box
        e = 1e-6
        assert x >= size[0] - e or y >= size[1] - e or x + w <= e or y + h <= e
        assert anim.mask.min() == 0
        # Скорость спокойная и не зависит от того, сколько осталось чёрного.
        budget = 0.2 * size[0] * frames / DVD_FPS
        assert abs(anim.total - budget) < 0.15 * budget


def test_clip_is_cut_at_the_frame_edge_while_flying_out(tmp_path):
    Image.new("RGB", (200, 100), "red").save(tmp_path / "red.png")
    media = FolderMedia(list_media(str(tmp_path)), random.Random(1))
    frames = 60
    anim = DvdAnimation(_picture(), 0.55, random.Random(6), media, DVD_FPS, frames)
    seen_partial = False
    for _ in range(frames - 1):
        frame = anim.frame()
        x, y, w, h = anim.box
        if x < 0 or y < 0 or x + w > 320 or y + h > 180:
            seen_partial = seen_partial or (frame == (255, 0, 0)).all(axis=2).any()
        anim.step()
    assert seen_partial
    assert not (anim.frame() == (255, 0, 0)).all(axis=2).any()


def test_trail_edge_is_smooth_not_stairs():
    # Край следа сглажен: есть полупрозрачные пиксели, а не только 0 и 255.
    anim = DvdAnimation(_picture(), 0.55, random.Random(4))
    for _ in range(40):
        anim.step()
    soft = (anim.mask > 0) & (anim.mask < 255)
    assert soft.sum() > 50


def test_speed_is_calm_and_sixty_fps_is_the_same_motion():
    slow = DvdAnimation(_picture(), 0.55, random.Random(8), None, 30, 300)
    fast = DvdAnimation(_picture(), 0.55, random.Random(8), None, 60, 600)
    # Прежняя скорость была ~0,37 ширины кадра в секунду.
    assert slow.total / 10 / 320 < 0.3
    assert abs(slow.total - fast.total) < 1e-6
    assert abs(slow.ds - 2 * fast.ds) < 0.05 * slow.ds


def test_last_step_keeps_unrevealed_areas_black():
    # В конце не показывается полный кадр: необлетённое остаётся чёрным.
    from frame_reveal import RevealRenderer
    renderer = RevealRenderer(_picture(), "dvd", 55, seed=3)
    final = np.asarray(renderer.render(1.0))
    assert (final.sum(axis=2) == 0).any()
