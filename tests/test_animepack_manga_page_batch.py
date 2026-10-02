# -*- coding: utf-8 -*-
"""Several source pages and alternative crops cost at most two AI requests."""
import io
import threading
from types import SimpleNamespace

from PIL import Image
import pytest

import animepack as ap
from test_animepack_manga_character_crop import verdict
from test_animepack_manga_complete_panels import scene
from test_animepack_manga_sakuga import generator, make_anime  # noqa: F401
from test_animepack_pixiv_gemini import _Cache
from si_hyx_parts.animepack.manga_character_crop import _windows
from si_hyx_parts.animepack.manga_scene_batch import crop_pages, MAX_TILES
from si_hyx_parts.animepack.manga_scene_review import check_many
from si_hyx_parts.animepack.manga_page_context import download


def data():
    out = io.BytesIO()
    scene().save(out, "PNG")
    return out.getvalue()


def proposal(index=0, **over):
    return verdict(page_index=index, tile_index=0, box=[300, 0, 700, 1000], **over)


class Gemini:
    model = "batch-test"

    def __init__(self, proposals, bad=(), malformed=False):
        self.proposals, self.bad, self.malformed = proposals, set(bad), malformed
        self.calls = []

    def generate_json(self, parts, schema, temperature=0):
        self.calls.append((parts, schema))
        if "candidates" in schema["properties"]:
            return dict(accept=True, has_title_text=False, reason="выбраны сцены",
                        candidates=self.proposals)
        ids = [int(p["text"].split("=")[-1]) for p in parts
               if p.get("text", "").startswith("Вырезка scene_id=")]
        rows = [verdict(scene_id=i, panel_count=1, cut_dialogue=i in self.bad) for i in ids]
        if self.malformed:
            rows = rows[:-1]
        return dict(accept=True, has_title_text=False, reason="проверено", scenes=rows)


def gen(client):
    return SimpleNamespace(gemini_manga=client, db_cache=_Cache(),
                           stopped=lambda: False, _log_rare=lambda *args: None,
                           log=lambda *args: None)


def pages(count=4):
    return [dict(data=data(), ext=".png", titles=["Comic"]) for _ in range(count)]


def cand():
    return SimpleNamespace(anime={"kind": "manhwa"}, title_ru="Comic")


def test_four_pages_are_sent_together_and_second_alternative_is_selected():
    client = Gemini([proposal(0), proposal(3)], bad={0})
    result = crop_pages(gen(client), cand(), pages())
    assert result is not None and result[0] == 3
    assert len(client.calls) == 2
    labels = [p.get("text", "") for p in client.calls[0][0]]
    assert all(any(f"page_index={i}," in text for text in labels) for i in range(4))
    assert sum(p["type"] == "image" for p in client.calls[0][0]) <= MAX_TILES
    reviews = [p for p in client.calls[1][0]
               if p.get("text", "").startswith("Вырезка scene_id=")]
    assert len(reviews) == 2
    with Image.open(io.BytesIO(result[1][0])) as picture:
        assert picture.width == 400 and picture.height >= 550


def test_invalid_first_coordinates_use_next_proposal_without_an_extra_call():
    bad = proposal(0)
    bad["box"] = [300, 0, 301, 1]
    client = Gemini([bad, proposal(2)])
    result = crop_pages(gen(client), cand(), pages())
    assert result[0] == 2 and len(client.calls) == 2
    assert sum(p.get("text", "").startswith("Вырезка scene_id=")
               for p in client.calls[1][0]) == 1


def test_all_bad_coordinates_cost_one_call_and_do_not_trigger_single_page_retries():
    client = Gemini([proposal(99), dict(proposal(0), box=[0, 0, 1, 1])])
    assert crop_pages(gen(client), cand(), pages()) is None
    assert len(client.calls) == 1


def test_all_rejected_crops_cost_two_calls_and_never_bypass_review():
    client = Gemini([proposal(0), proposal(1), proposal(2)], bad={0, 1, 2})
    assert crop_pages(gen(client), cand(), pages()) is None
    assert len(client.calls) == 2


def test_cached_page_pool_and_crop_verdicts_need_no_new_requests():
    client = Gemini([proposal(2)])
    generator = gen(client)
    assert crop_pages(generator, cand(), pages())[0] == 2
    assert crop_pages(generator, cand(), pages())[0] == 2
    assert len(client.calls) == 2


def test_partial_review_response_cannot_approve_other_scenes():
    client = Gemini([proposal(0), proposal(1)], malformed=True)
    assert crop_pages(gen(client), cand(), pages()) is None


@pytest.mark.parametrize("height", [2400, 20000, 100000])
def test_batch_tile_budget_covers_long_pages_without_gaps(height):
    regions = _windows(400, height, max_tiles=6)
    assert len(regions) <= 6 and regions[0][1] == 0 and regions[-1][3] == height
    assert all(a[3] >= b[1] for a, b in zip(regions, regions[1:]))


def test_individual_cached_reviews_are_reused_in_a_batch():
    client = Gemini([])
    generator = gen(client)
    scenes = [(scene(), scene()), (scene().crop((0, 0, 400, 1000)), scene())]
    assert all(good for good, _ in check_many(generator, scenes, "Comic"))
    assert all(good for good, _ in check_many(generator, scenes, "Comic"))
    assert len(client.calls) == 1


def test_pipeline_restores_selected_chapter_page_and_context(generator):
    generator.s.manga_character_crop = True
    generator.gemini_manga = Gemini([proposal(1)])
    reader = generator.mangadex
    picked = []

    def pick(card, excluded):
        index = len(picked)
        picked.append(index)
        reader.last_chapter = f"chapter-{index}"
        reader.last_source_link = f"https://reader/chapter-{index}"
        reader.last_page_info = {"neighbors": [
            dict(offset=1, url=f"https://cdn/context-{index}.png")]}
        return f"https://cdn/page-{index}.png"

    reader.panel_url = pick
    generator._get_bytes = lambda *args, **kwargs: data()
    candidate = ap.SongCandidate({}, make_anime(malId=656, kind="manhwa"),
                                 kind=ap.MANGA_KIND, media="manga")
    assert generator.download_manga_panel(candidate)
    assert len(picked) == 4 and len(generator.gemini_manga.calls) == 2
    assert candidate.frame_url == "https://cdn/page-1.png"
    assert candidate.source_link == "https://reader/chapter-1"
    assert candidate.extra_frame_urls == ["https://cdn/context-1.png"]


def test_prefetched_neighbors_are_downloaded_once_per_pool():
    calls = []
    generator = SimpleNamespace(stopped=lambda: False, _frames_lock=threading.Lock(),
                                _frames_used=set(), log=lambda *args: None,
                                _url_ext=lambda *args: ".png")
    generator._get_bytes = lambda url: (calls.append(url), data())[1]
    first = cand()
    first._manga_page_info = {"neighbors": [dict(offset=1, url="page-2")]}
    second = cand()
    second._manga_page_info = {"neighbors": [dict(offset=-1, url="page-1")]}
    cache = {}
    download(generator, first, "page-1", cache=cache)
    download(generator, second, "page-2", cache=cache)
    assert calls == ["page-1", "page-2"]


@pytest.mark.parametrize("count", [None, 0, 2, True, "1"])
def test_one_complete_face_cannot_approve_an_additional_partial_panel(count):
    client = Gemini([proposal(0)])
    original = client.generate_json

    def respond(parts, schema, temperature=0):
        result = original(parts, schema, temperature)
        for row in result.get("scenes", []):
            row["panel_count"] = count
        return result

    client.generate_json = respond
    assert crop_pages(gen(client), cand(), pages()) is None
    assert len(client.calls) == 2
