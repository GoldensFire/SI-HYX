"""Local scene proposals preserve drawing bands and reject empty sources."""
from concurrent.futures import ThreadPoolExecutor
import threading

from PIL import Image, ImageDraw
import pytest

from si_hyx_parts.animepack.manga_scene_prefilter import windows
from si_hyx_parts.animepack.manga_page_downloads import PageDownloads


def test_local_candidates_keep_full_panels_between_gutters():
    picture = Image.new("RGB", (400, 1800), "white")
    draw = ImageDraw.Draw(picture)
    for top in (100, 650, 1200):
        draw.rectangle((25, top, 375, top + 430), fill="navy")
        draw.rectangle((50, top + 30, 200, top + 150), fill="yellow")
    regions = windows(picture, 6)
    assert len(regions) == 3
    for top in (100, 650, 1200):
        assert any(left == 0 and right == 400 and upper < top and lower > top + 430
                   for left, upper, right, lower in regions)


def test_blank_or_single_band_preserves_full_source_fallback():
    picture = Image.new("RGB", (400, 1200), "white")
    assert windows(picture, 6) == []
    ImageDraw.Draw(picture).rectangle((30, 200, 370, 700), fill="blue")
    assert windows(picture, 6) == []


def test_parallel_neighbor_downloads_share_one_result():
    cache = PageDownloads()
    calls = []
    ready, release = threading.Event(), threading.Event()
    def action():
        calls.append("download")
        ready.set()
        assert release.wait(3)
        return b"image", ".png"
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cache.fetch, "page", action)
        assert ready.wait(3)
        second = pool.submit(cache.fetch, "page", action)
        release.set()
        assert first.result() == second.result() == (b"image", ".png")
    assert calls == ["download"]


def test_a_failed_shared_download_never_becomes_successful_bytes():
    cache = PageDownloads()
    def fail():
        raise TimeoutError("reader unavailable")
    for _ in range(2):
        with pytest.raises(TimeoutError):
            cache.fetch("bad-page", fail)
