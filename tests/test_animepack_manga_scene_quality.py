# -*- coding: utf-8 -*-
"""Short reader chunks, blank gutters and independent scene inspection."""
import io
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from test_animepack_manga_character_crop import Gemini, page, verdict
from test_animepack_pixiv_gemini import _Cache
from si_hyx_parts.animepack.manga_character_crop import crop
from si_hyx_parts.animepack.manga_margins import trim, has_large_gap
from si_hyx_parts.animepack.manga_page_context import download


def test_short_manhwa_chunk_is_scanned_and_its_blank_top_is_trimmed():
    client = Gemini(verdict(tile_index=0, box=[0, 0, 1000, 1000]))
    gen = SimpleNamespace(gemini_manga=client, db_cache=_Cache(),
                          stopped=lambda: False, _log_rare=lambda *args: None)
    cand = SimpleNamespace(anime={"kind": "manhwa"}, title_ru="Webtoon")
    data = page((400, 1100))
    result = crop(gen, cand, data, ".png")
    assert result is not None
    with Image.open(io.BytesIO(result[0])) as frame:
        assert frame.height < 440 and frame.width < 280
    assert len(client.calls) == 2


@pytest.mark.parametrize("problem", ["has_characters", "complete_character",
                                     "large_blank_area", "fragmented", "cut_dialogue"])
def test_selector_acceptance_cannot_bypass_review_of_cropped_pixels(problem):
    client = Gemini(verdict())
    original = client.generate_json

    def respond(parts, schema, temperature=0):
        result = original(parts, schema, temperature)
        if "tile_index" not in schema["properties"]:
            result = dict(result, **{problem: problem in
                                    ("large_blank_area", "fragmented", "cut_dialogue")})
        return result

    client.generate_json = respond
    gen = SimpleNamespace(gemini_manga=client, db_cache=_Cache(),
                          stopped=lambda: False, _log_rare=lambda *args: None)
    cand = SimpleNamespace(anime={}, title_ru="Comic")
    assert crop(gen, cand, page(), ".png") is None


@pytest.mark.parametrize("color", ["white", "black"])
def test_large_margins_are_removed_but_small_borders_are_kept(color):
    picture = Image.new("RGB", (400, 600), color)
    ImageDraw.Draw(picture).rectangle((10, 10, 389, 430), fill=(110, 70, 50))
    result = trim(picture)
    assert result.width == 400  # small side margins
    assert 430 < result.height < 450
    small = picture.crop((0, 0, 400, 441))
    assert trim(small).size == small.size


def test_disjoint_panels_with_a_large_empty_middle_are_rejected():
    picture = Image.new("RGB", (400, 600), "white")
    draw = ImageDraw.Draw(picture)
    draw.rectangle((0, 0, 399, 130), fill=(110, 70, 50))
    draw.rectangle((0, 430, 399, 599), fill=(110, 70, 50))
    assert has_large_gap(trim(picture))


def test_sparse_dialogue_survives_margin_trimming():
    picture = Image.new("RGB", (400, 600), "white")
    draw = ImageDraw.Draw(picture)
    draw.ellipse((160, 30, 240, 110), outline="black", width=1)
    draw.text((170, 65), "HI!", fill="black")
    draw.rectangle((0, 320, 399, 599), fill=(110, 70, 50))
    result = trim(picture)
    assert result.width == 400 and result.height >= 570


def test_dense_speech_bubbles_outside_the_colored_scene_are_preserved():
    picture = Image.new("RGB", (400, 600), "white")
    draw = ImageDraw.Draw(picture)
    draw.ellipse((25, -60, 375, 150), outline="black", width=12)
    draw.ellipse((70, 180, 330, 360), outline="black", width=3)
    draw.text((120, 240), "DIALOGUE WITHOUT PEOPLE", fill="black")
    draw.rectangle((0, 330, 399, 599), fill=(180, 130, 160))
    result = trim(picture)
    assert result.size == picture.size


@pytest.mark.parametrize("gutter,color", [(12, "white"), (2, "black")])
def test_margin_trimming_does_not_treat_a_panel_border_as_a_safe_cut(gutter, color):
    picture = Image.new("RGB", (400, 400), (160, 130, 180))
    draw = ImageDraw.Draw(picture)
    draw.rectangle((0, 80, 399, 80 + gutter - 1), fill=color)
    result = trim(picture)
    assert result.size == picture.size


@pytest.mark.parametrize("height,already_used", [(600, False), (600, True), (1600, True)])
def test_neighbor_metadata_and_pixels_survive_a_reader_chunk_seam(height, already_used):
    import threading
    payloads = {}
    for offset, color in ((-1, "red"), (0, "green"), (1, "blue")):
        output = io.BytesIO()
        Image.new("RGB", (400, height), color).save(output, "PNG")
        payloads[str(offset)] = output.getvalue()
    calls = []

    def read(url, info):
        calls.append((url, info))
        assert info.get("legacy") is True
        return payloads[url], ".png"

    gen = SimpleNamespace(stopped=lambda: False, _frames_lock=threading.Lock(),
                          _frames_used={"-1", "1"} if already_used else set(),
                          _log_rare=lambda *args: None)
    cand = SimpleNamespace(anime={"kind": "manhwa"}, title_ru="Webtoon",
                          _manga_page_client=SimpleNamespace(download_page=read),
                          _manga_page_info={"legacy": True, "neighbors": [
                              {"url": str(i), "offset": i, "legacy": True}
                              for i in (-1, 1)]})
    data, ext = download(gen, cand, "0")
    with Image.open(io.BytesIO(data)) as joined:
        assert joined.size == (400, height * 3)
        assert joined.getpixel((200, 200)) == (255, 0, 0)
        assert joined.getpixel((200, height + 200)) == (0, 128, 0)
        assert joined.getpixel((200, height * 2 + 200)) == (0, 0, 255)
    assert gen._frames_used == {"-1", "1"}
    assert set(cand._manga_context_urls) == {"-1", "0", "1"}
    assert ext == ".png" and len(calls) == 3
