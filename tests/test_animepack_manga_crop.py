# -*- coding: utf-8 -*-
"""Длинная лента вебтуна режется до книжного разворота (манхва, маньхуа)."""
import io
import random

import pytest

import animepack  # noqa: F401 — публичный модуль грузит свои части
from si_hyx_parts.animepack.manga_crop import (EDGE_SKIP, PAGE_MAX_RATIO,
                                              fit_page)

Image = pytest.importorskip("PIL.Image")


def _page(width, height, fmt="JPEG"):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 180, 160)).save(buf, format=fmt)
    return buf.getvalue()


def _size(data):
    with Image.open(io.BytesIO(data)) as im:
        return im.size


def test_webtoon_strip_is_cut_to_book_proportions():
    cut = fit_page(_page(800, 12000), ".jpg", rng=random.Random(7))
    assert cut is not None
    data, ext = cut
    width, height = _size(data)
    assert ext == ".jpg"
    assert width == 800
    assert height == round(800 * PAGE_MAX_RATIO)


def test_ordinary_manga_spread_is_left_alone():
    """Разворот книги и так книжный — трогать его незачем."""
    assert fit_page(_page(1114, 1600), ".jpg") is None


@pytest.mark.parametrize("height", [1440, 2000, 2400])
def test_tall_book_pages_are_not_confused_with_webtoon_strips(height):
    assert fit_page(_page(800, height), ".jpg") is None


def test_cut_window_keeps_away_from_the_edges():
    """Шапка переводчиков сверху и «продолжение следует» снизу не берутся."""
    height = 10000
    keep = round(800 * PAGE_MAX_RATIO)
    edge = int(height * EDGE_SKIP)
    tops = set()
    for seed in range(30):
        strip = Image.new("RGB", (800, height), (0, 0, 0))
        # Каждую сотую строку красим по-своему, чтобы понять, откуда вырезали.
        for y in range(0, height, 100):
            for x in range(0, 800, 200):
                strip.putpixel((x, y), (y // 100 % 256, 0, 0))
        buf = io.BytesIO()
        strip.save(buf, format="PNG")
        cut = fit_page(buf.getvalue(), ".png", rng=random.Random(seed))
        assert cut is not None
        data, ext = cut
        assert ext == ".png"
        assert _size(data) == (800, keep)
        tops.add(data[:64])
    # Окно и правда случайное: у тридцати попыток не одна и та же вырезка.
    assert len(tops) > 1
    assert edge > 0


def test_broken_bytes_do_not_break_the_question():
    assert fit_page(b"not a picture at all", ".jpg") is None
