# -*- coding: utf-8 -*-
"""Original-page character selection, crop geometry and service failures."""
import base64
import io
from types import SimpleNamespace

from PIL import Image, ImageDraw
import pytest

import animepack as ap
from si_hyx_parts.animepack.manga_character_crop import crop, _windows, _frame
from test_animepack_manga_sakuga import generator, make_anime  # noqa: F401
from test_animepack_pixiv_gemini import _Cache


def page(size=(400, 2400), drawing=True):
    picture = Image.new("RGB", size, "white")
    if drawing:
        ImageDraw.Draw(picture).rectangle((100, size[1] - 620, 300, size[1] - 230),
                                          fill=(20, 80, 30))
    out = io.BytesIO()
    picture.save(out, "PNG")
    return out.getvalue()


def verdict(**over):
    result = dict(accept=True, has_title_text=False, has_characters=True,
                  tile_index=5, box=[330, 0, 780, 1000], reason="сцена с героем",
                  complete_character=True, large_blank_area=False, fragmented=False,
                  cut_dialogue=False,
                  characters=[dict(description="герой в зелёной одежде",
                                   face_complete=True, edge_cut=False)],
                  character_description="герой в зелёной одежде")
    result.update(over)
    return result


class Gemini:
    model = "crop-test"

    def __init__(self, response):
        self.response, self.calls = response, []

    def generate_json(self, parts, schema, temperature=0):
        self.calls.append((parts, schema))
        return self.response


def test_scans_the_whole_original_strip_and_crops_the_selected_scene():
    client = Gemini(verdict())
    gen = SimpleNamespace(gemini_manga=client, db_cache=_Cache(),
                          stopped=lambda: False, _log_rare=lambda *args: None)
    cand = SimpleNamespace(anime={"name": "Comic"}, title_ru="Comic")
    data = page()
    result = crop(gen, cand, data, ".png")
    assert result is not None
    with Image.open(io.BytesIO(result[0])) as picture:
        assert 245 <= picture.width < 280 and 390 <= picture.height < 440
        assert picture.getpixel((picture.width // 2, 100)) == (20, 80, 30)
    images = [p for p in client.calls[0][0] if p["type"] == "image"]
    assert len(images) == len(_windows(400, 2400)) == 6
    with Image.open(io.BytesIO(base64.b64decode(images[-1]["data"]))) as last:
        assert last.height == 960 and last.getpixel((200, 400))[0] < 50
    assert crop(gen, cand, data, ".png") == result
    assert len(client.calls) == 2  # original strip, then actual cropped pixels


@pytest.mark.parametrize("over", [
    {"has_characters": False}, {"has_title_text": True}, {"tile_index": 99},
    {"box": [-1, 0, 900, 1000]}, {"box": [900, 0, 100, 1000]},
    {"box": [100, 0, 101, 1]}, {"box": [True, 0, 900, 1000]},
])
def test_rejects_unusable_or_invalid_character_regions(over):
    picture = Image.open(io.BytesIO(page()))
    assert _frame(picture, _windows(*picture.size), verdict(**over)) is None


def test_a_blank_white_region_is_rejected_despite_gemini_acceptance():
    picture = Image.open(io.BytesIO(page(drawing=False)))
    assert _frame(picture, _windows(*picture.size), verdict()) is None


@pytest.mark.parametrize("height", [2400, 20000, 100000])
def test_tiles_cover_every_row_without_gaps(height):
    windows = _windows(400, height)
    assert len(windows) <= 32
    assert windows[0][1] == 0 and windows[-1][3] == height
    assert all(first[3] >= second[1] for first, second in zip(windows, windows[1:]))


def test_a_book_sized_scene_crossing_any_tile_boundary_fits_another_tile():
    windows = _windows(400, 12000)
    for top in range(0, 12000 - 640):
        assert any(w[1] <= top and top + 640 <= w[3] for w in windows)


def test_media_uses_gemini_scene_and_keeps_its_chapter_link(generator):
    gen = generator
    gen.s.manga_character_crop = True
    gen.s.manga_gemini_check = True
    gen.gemini_manga = Gemini(verdict())
    gen._get_bytes = lambda *args, **kwargs: page()
    cand = ap.SongCandidate({}, make_anime(malId=656), kind=ap.MANGA_KIND,
                            media="manga")
    assert gen._fetch_media(cand)
    assert len(gen.gemini_manga.calls) == 2
    assert cand.source_link.endswith("/ch-42")
    with Image.open(gen.folder + "/Images/" + cand.frame_name) as picture:
        assert 245 <= picture.width < 280 and 390 <= picture.height < 440


def test_unavailable_scene_scanner_does_not_generate_a_random_crop(generator):
    gen = generator
    gen.s.manga_character_crop = True
    gen.gemini_manga = None
    gen._get_bytes = lambda *args, **kwargs: page()
    cand = ap.SongCandidate({}, make_anime(malId=656), kind=ap.MANGA_KIND,
                            media="manga")
    assert not gen._fetch_media(cand)
    assert not cand.has_frame and ap.MANGA_KIND in gen._dead_kinds


@pytest.mark.parametrize("height", [600, 720, 1000, 1200])
def test_character_crop_preserves_ordinary_pages_without_a_gemini_call(height):
    data = page(size=(400, height))
    gen = SimpleNamespace(gemini_manga=None)
    cand = SimpleNamespace(anime={})
    assert crop(gen, cand, data, ".png") == (data, ".png")


def test_ordinary_page_is_kept_when_scene_scanner_is_unavailable(generator):
    gen = generator
    gen.s.manga_character_crop = True
    gen.s.manga_gemini_check = False
    gen.gemini_manga = None
    data = page(size=(400, 720))
    gen._get_bytes = lambda *args, **kwargs: data
    cand = ap.SongCandidate({}, make_anime(malId=656), kind=ap.MANGA_KIND,
                            media="manga")
    assert gen._fetch_media(cand)
    assert ap.MANGA_KIND not in gen._dead_kinds
    with open(gen.folder + "/Images/" + cand.frame_name, "rb") as saved:
        assert saved.read() == data


def test_page_download_failure_is_not_a_scene_scanner_failure(generator):
    gen = generator
    gen.s.manga_character_crop = True
    gen.gemini_manga = None

    def fail(*args, **kwargs):
        raise ap.AnimePackError("connection interrupted")

    gen._get_bytes = fail
    cand = ap.SongCandidate({}, make_anime(malId=656), kind=ap.MANGA_KIND,
                            media="manga")
    assert not gen._fetch_media(cand)
    assert not cand.has_frame and ap.MANGA_KIND not in gen._dead_kinds
