# -*- coding: utf-8 -*-
"""Предекодер кадров на НАСТОЯЩЕМ видео (нужен bundled ffmpeg).

Смысл: сетку кадров можно проверить арифметикой, а вот «кадр N из буфера — это
действительно кадр N» проверяется только настоящим декодированием. Клип берём с
длинным GOP (120 кадров между ключевыми) — именно на таких файлах плеер и
промахивался мимо кадра, ради чего слой и написан.

В CI bin/ffmpeg.exe нет (внешний ассет, см. .gitignore) — тест там пропускается.
"""
import os
import subprocess
import time

import pytest

pytestmark = pytest.mark.integration

config = pytest.importorskip("config")
frames = pytest.importorskip("edit_tab_frames")

FPS = 24000 / 1001.0          # 23.976 — дробный, самый неудобный случай

pytestmark = [pytest.mark.integration,
              pytest.mark.skipif(not os.path.exists(config.FFMPEG),
                                 reason="нет bundled ffmpeg (внешний ассет)")]


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("frames") / "clip.mp4")
    subprocess.run(
        [config.FFMPEG, "-y", "-f", "lavfi",
         "-i", f"testsrc2=size=320x180:rate=24000/1001:duration=5",
         "-c:v", "libx264", "-g", "120", "-keyint_min", "120",
         "-sc_threshold", "0", "-pix_fmt", "yuv420p", path],
        capture_output=True, creationflags=config.CREATE_NO_WINDOW, timeout=120)
    assert os.path.exists(path) and os.path.getsize(path) > 1000
    return path


@pytest.fixture
def prefetcher(qapp, clip):
    pf = frames.FramePrefetcher()
    pf.set_source(clip, FPS)
    pf.start()
    yield pf
    pf.stop()
    pf.wait(3000)


def _pump(qapp, pf, indices, timeout=25.0):
    """Крутит цикл событий, пока не приедут нужные кадры (или не выйдет время)."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if all(pf.has(i) for i in indices):
            return True
        qapp.processEvents()
        time.sleep(0.02)
    return all(pf.has(i) for i in indices)


def _bytes(img):
    img = img.convertToFormat(img.Format.Format_RGB888)
    return bytes(img.constBits().asstring(img.sizeInBytes()))


def _mean_diff(a, b):
    ba, bb = _bytes(a), _bytes(b)
    if len(ba) != len(bb):
        return 999.0
    step = max(1, len(ba) // 20000)
    vals = [abs(ba[i] - bb[i]) for i in range(0, len(ba), step)]
    return sum(vals) / max(1, len(vals))


def _reference(clip, idx, out_dir):
    """Эталон: тот же кадр, извлечённый отдельным вызовом ffmpeg в PNG."""
    from PyQt6.QtGui import QImage
    grid = frames.FrameGrid(FPS, 5.0)
    out = os.path.join(out_dir, f"ref_{idx}.png")
    subprocess.run(
        [config.FFMPEG, "-y", "-ss", f"{grid.seek_of(idx):.4f}", "-i", clip,
         "-frames:v", "1", "-update", "1", out],
        capture_output=True, creationflags=config.CREATE_NO_WINDOW, timeout=60)
    img = QImage(out)
    assert not img.isNull()
    return img


def test_buffer_returns_requested_frame(qapp, prefetcher, clip, tmp_path):
    """Кадр 100 из буфера совпадает с кадром 100, извлечённым независимо."""
    prefetcher.request(100, ahead=6, behind=3)
    assert _pump(qapp, prefetcher, [100]), "кадр так и не приехал"
    got = prefetcher.frame(100)
    assert got is not None and got.width() == 320 and got.height() == 180
    assert _mean_diff(got, _reference(clip, 100, str(tmp_path))) < 2.0


def test_neighbours_are_prefetched_and_differ(qapp, prefetcher):
    """Соседи вокруг плейхеда приезжают ОДНИМ запуском ffmpeg и они разные —
    иначе шаг стрелкой показывал бы одну и ту же картинку."""
    prefetcher.request(100, ahead=6, behind=3)
    assert _pump(qapp, prefetcher, [97, 98, 99, 100, 101, 102])
    assert _mean_diff(prefetcher.frame(100), prefetcher.frame(101)) > 0.1


def test_step_forward_hits_cache(qapp, prefetcher):
    """Следующий кадр после шага уже в буфере — рисуется мгновенно, без ffmpeg."""
    prefetcher.request(50, ahead=6, behind=3)
    assert _pump(qapp, prefetcher, [50, 51])
    assert prefetcher.has(51) and prefetcher.frame(51) is not None


def test_new_source_drops_cache(qapp, prefetcher, clip):
    prefetcher.request(50, ahead=3, behind=0)
    assert _pump(qapp, prefetcher, [50])
    prefetcher.set_source(clip, FPS)      # тот же файл, но это «новый источник»
    assert not prefetcher.has(50)


def test_probe_frame_size(clip):
    assert frames.probe_frame_size(clip) == (320, 180)
    assert frames.probe_frame_size("нет-такого-файла.mp4") == (0, 0)
