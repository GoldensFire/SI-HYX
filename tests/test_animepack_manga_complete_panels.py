# -*- coding: utf-8 -*-
"""Preserve faces, panel sides and dialogue protruding beyond panel borders."""
import base64
import io
from types import SimpleNamespace

from PIL import Image, ImageDraw

from test_animepack_manga_character_crop import Gemini, verdict
from test_animepack_pixiv_gemini import _Cache
from si_hyx_parts.animepack.manga_character_crop import _frame, crop
from si_hyx_parts.animepack.manga_margins import trim
from si_hyx_parts.animepack.manga_scene_review import check


def scene():
    picture = Image.new("RGB", (400, 1600), "white")
    draw = ImageDraw.Draw(picture)
    draw.rectangle((0, 280, 399, 700), fill=(70, 110, 130))
    draw.ellipse((30, 230, 230, 780), fill="white", outline="black", width=3)
    draw.text((65, 250), "FULL DIALOGUE", fill="black")
    draw.text((65, 740), "LAST LINE", fill="black")
    # Distinct markers represent content lost by the old horizontal crop
    # and a head extending above the proposed portrait rectangle.
    draw.rectangle((0, 300, 15, 330), fill="red")
    draw.rectangle((300, 285, 350, 320), fill="yellow")
    return picture


def test_narrow_portrait_is_expanded_to_all_panel_sides_faces_and_bubbles():
    picture = scene()
    frame = _frame(picture, [(0, 0, 400, 1600)],
                   verdict(tile_index=0, box=[210, 500, 410, 1000]))
    assert frame is not None and frame.width == 400 and frame.height >= 550
    colors = frame.getcolors(frame.width * frame.height)
    counts = {color: count for count, color in colors}
    assert counts[(255, 0, 0)] == 16 * 31
    assert counts[(255, 255, 0)] == 51 * 36
    dark_rows = [y for y in range(frame.height)
                 if min(frame.crop((30, y, 231, y + 1)).convert("L").getdata()) < 40]
    assert max(dark_rows) - min(dark_rows) >= 550


def test_a_bubble_crossing_a_black_panel_border_is_not_cut_at_the_border():
    picture = Image.new("RGB", (400, 600), "white")
    draw = ImageDraw.Draw(picture)
    draw.rectangle((0, 0, 399, 430), fill=(90, 120, 160))
    draw.line((0, 430, 399, 430), fill="black", width=3)
    draw.ellipse((20, 360, 230, 570), fill="white", outline="black", width=2)
    draw.text((50, 530), "DO NOT CUT", fill="black")
    result = trim(picture)
    assert result.width == 400 and result.height > 570


def test_oversize_complete_panel_is_rejected_instead_of_cutting_its_dialogue():
    picture = Image.new("RGB", (400, 2200), "white")
    draw = ImageDraw.Draw(picture)
    draw.rectangle((0, 200, 399, 1200), fill=(70, 110, 130))
    draw.ellipse((20, 100, 200, 300), fill="white", outline="black", width=3)
    assert _frame(picture, [(0, 0, 400, 2200)],
                  verdict(tile_index=0, box=[180, 0, 400, 1000])) is None


def test_review_compares_source_context_and_actual_crop():
    picture = scene()
    data = io.BytesIO()
    picture.save(data, "PNG")
    client = Gemini(verdict(tile_index=0, box=[210, 500, 410, 1000]))
    gen = SimpleNamespace(gemini_manga=client, db_cache=_Cache(),
                          stopped=lambda: False, _log_rare=lambda *args: None)
    cand = SimpleNamespace(anime={"kind": "manhwa"}, title_ru="Comic")
    assert crop(gen, cand, data.getvalue(), ".png") is not None
    parts = client.calls[-1][0]
    images = [p for p in parts if p["type"] == "image"]
    assert len(images) == 2
    sizes = []
    for part in images:
        with Image.open(io.BytesIO(base64.b64decode(part["data"]))) as opened:
            sizes.append(opened.size)
    assert sizes[0][1] > sizes[1][1]


def test_missing_dialogue_verdict_cannot_reuse_an_old_acceptance():
    response = verdict()
    response.pop("cut_dialogue")
    gen = SimpleNamespace(gemini_manga=Gemini(response), db_cache=_Cache())
    assert check(gen, scene(), "Comic")[0] is False


def test_reader_file_ending_through_a_bubble_is_rejected_even_if_gemini_accepts():
    picture = scene().crop((0, 0, 400, 750))
    assert _frame(picture, [(0, 0, 400, 750)],
                  verdict(tile_index=0, box=[300, 0, 1000, 1000])) is None


def test_reader_file_starting_through_a_face_needs_more_source_context():
    picture = scene().crop((0, 300, 400, 1000))
    assert _frame(picture, [(0, 0, 400, 700)],
                  verdict(tile_index=0, box=[0, 0, 650, 1000])) is None


def test_one_good_character_cannot_hide_another_characters_cut_face():
    response = verdict(characters=[
        dict(description="мужчина слева, глаза, нос и рот видны",
             face_complete=True, edge_cut=False),
        dict(description="девушка справа, нос и рот за краем",
             face_complete=False, edge_cut=True)])
    gen = SimpleNamespace(gemini_manga=Gemini(response), db_cache=_Cache())
    assert check(gen, scene(), "Comic")[0] is False


def test_old_review_without_individual_characters_is_rejected():
    response = verdict()
    response.pop("characters")
    gen = SimpleNamespace(gemini_manga=Gemini(response), db_cache=_Cache())
    assert check(gen, scene(), "Comic")[0] is False
