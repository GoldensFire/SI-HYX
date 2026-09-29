# -*- coding: utf-8 -*-
"""Очередь, единая шкала и экономия запросов при параллельном сюжете."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import os
import re
import subprocess
import threading

import pytest

import animepack as ap
import animepack_tab
from si_hyx_parts.animepack.generation_priority import (
    apply_thread_priority, creation_flags, parallel_limit)
from si_hyx_parts.animepack.plot_batch import PlotBatcher
from test_animepack_tab_mix import _FakeMain


@pytest.fixture
def tab(qapp):
    widget = animepack_tab.AnimePackTab(main_window=_FakeMain())
    yield widget
    widget.cleanup()


def test_level_ranges_share_one_bar_with_bounded_average(tab):
    bars = (tab.level_range, tab.song_level_range, tab.studio_level_range,
            tab.char_level_range, tab.art_level_range,
            tab.manga_level_range, tab.plot_level_range)
    for bar in bars:
        assert (bar.minimum, bar.maximum) == (1, ap.MAX_LEVEL)
        assert bar.avg_control.parent() is bar
        bar.set_range(3, 6)
        bar.avg_control.setValue(8)
        assert bar.avg_control.value() == 6
        assert bar._legend_text() == "От 3 до 6 · В среднем: 6"
        bar.set_range(4, 5)
        assert bar.avg_control.value() == 5
        bar.any_check.setChecked(True)
        assert bar.avg_control.value() == 0
        assert bar._legend_text() == "От 4 до 5 · В среднем: Любая"
        bar.any_check.setChecked(False)
        assert 4 <= bar.avg_control.value() <= 5


def test_overlapping_average_does_not_trap_range_handle(tab):
    from PyQt6.QtCore import QPointF

    class Event:
        def __init__(self, x):
            self.x = x

        def position(self):
            return QPointF(self.x, 8)

    bar = tab.level_range
    bar.resize(400, 40)
    bar.set_range(3, 6)
    bar.avg_control.setValue(3)
    x = bar._x_of(bar._pct(3))
    bar.mousePressEvent(Event(x))
    bar.mouseMoveEvent(Event(x - 40))
    bar.mouseReleaseEvent(Event(x - 40))
    assert bar.range_values()[0] < 3
    assert bar.avg_control.value() == 3


def test_queue_snapshots_settings_and_excludes_finished_pack(tab, tmp_path, qapp):
    class Pool:
        def __init__(self):
            self.jobs = []

        def start(self, job):
            self.jobs.append(job)

    pool = Pool()
    tab._pool = pool
    tab.ed_title.setText("Первый")
    tab.start()
    assert len(pool.jobs) == 1
    tab.ed_title.setText("Второй")
    tab.start()
    assert len(tab._queue) == 1
    tab.ed_title.setText("Третий")
    tab.start()
    assert [item.title for item in tab._queue] == ["Второй", "Третий"]

    path = tmp_path / "first.siq"
    path.write_bytes(b"pack")
    tab._db_task = object()  # обновление базы началось в паузе между заданиями
    tab._on_finished(SimpleNamespace(
        songs=[], path=str(path), elapsed=1.0, cancelled=False,
        requested=0, pack_number=1))
    qapp.processEvents()
    assert len(pool.jobs) == 1
    tab._finish_db_ui()
    qapp.processEvents()
    assert len(pool.jobs) == 2
    next_settings = pool.jobs[1].settings
    assert next_settings.title == "Второй"
    assert str(path) in next_settings.exclude_siq
    assert str(path) in next_settings.exclude_exact_siq
    assert str(path) in tab._exclude_siq
    assert str(path) in tab._exclude_exact_siq


def test_low_priority_caps_parallelism_and_windows_priority():
    settings = ap.PackSettings(parallel=8, generation_priority="low")
    assert parallel_limit(settings) == 2
    settings.generation_priority = "normal"
    assert parallel_limit(settings) == 8
    if os.name != "nt":
        assert creation_flags(settings) == 0
        return
    assert creation_flags(ap.PackSettings(generation_priority="low")) == \
        subprocess.IDLE_PRIORITY_CLASS
    import ctypes
    kernel = ctypes.windll.kernel32
    kernel.GetCurrentThread.restype = ctypes.c_void_p
    kernel.GetThreadPriority.argtypes = [ctypes.c_void_p]
    kernel.GetThreadPriority.restype = ctypes.c_int
    kernel.SetThreadPriority.argtypes = [ctypes.c_void_p, ctypes.c_int]
    levels = []

    def probe():
        handle = kernel.GetCurrentThread()
        original = kernel.GetThreadPriority(handle)
        try:
            low = ap.PackSettings(generation_priority="low")
            apply_thread_priority(low)
            levels.append(kernel.GetThreadPriority(handle))
        finally:
            kernel.SetThreadPriority(handle, original)

    worker = threading.Thread(target=probe)
    worker.start()
    worker.join()
    assert levels == [-15]


def test_three_plot_pages_share_one_gemini_request():
    class Client:
        def __init__(self):
            self.prompts = []

        def generate_json(self, prompt, _schema, temperature=0.6):
            self.prompts.append(prompt)
            jobs = re.findall(r"<задание id=(\d+)>\n(.*?)\n</задание>",
                              prompt, flags=re.S)
            return {"results": [{"id": int(index), "items": [
                {"question": body}]} for index, body in reversed(jobs)]}

    client = Client()
    batch = PlotBatcher(client)
    schema = {"properties": {"items": {"type": "array", "items": {
        "type": "object", "properties": {"question": {"type": "string"}}}}}}
    with ThreadPoolExecutor(max_workers=3) as workers:
        answers = list(workers.map(
            lambda index: batch.generate_json(f"page-{index}", schema),
            range(3)))
    assert len(client.prompts) == 1
    assert [row["items"][0]["question"] for row in answers] == [
        "page-0", "page-1", "page-2"]


def test_old_one_use_media_is_purged_but_posters_remain(tmp_path, monkeypatch):
    import cover_cache
    import media_cache
    import poster_cache
    from si_hyx_parts.animepack import one_use_cache

    monkeypatch.setattr(one_use_cache, "_DONE", False)
    monkeypatch.setattr(media_cache, "MEDIA_CACHE_DIR", str(tmp_path / "media"))
    monkeypatch.setattr(media_cache, "_SIZE", None)
    monkeypatch.setattr(poster_cache, "POSTER_CACHE_DIR", str(tmp_path / "posters"))
    monkeypatch.setattr(cover_cache, "CACHE_DIR", str(tmp_path / "covers"))
    (tmp_path / "covers").mkdir()
    (tmp_path / "covers" / "7.npy").write_bytes(b"chroma")
    for kind in ("amq-audio", "anime-frame", "cover-audio", "avif"):
        media_cache.put(kind, kind, b"old")
    kept = media_cache.put("poster-avif", "poster", b"poster")
    portrait = poster_cache.put("character_7", b"portrait")
    poster = poster_cache.put("anime_7", b"poster")

    one_use_cache.purge()
    assert [row["namespace"] for row in media_cache.entries()] == [
        "poster-avif"]
    assert os.path.isfile(kept) and os.path.isfile(poster)
    assert not os.path.exists(portrait)
    assert not (tmp_path / "covers" / "7.npy").exists()
