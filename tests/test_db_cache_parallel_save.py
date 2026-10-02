# -*- coding: utf-8 -*-
"""Параллельные источники не перезаписывают свежую базу старым снимком."""
from concurrent.futures import ThreadPoolExecutor
import threading

import animepack as ap


def test_parallel_saves_preserve_updates_arriving_during_disk_write(tmp_path, monkeypatch):
    cache = ap.ShikimoriDbCache(str(tmp_path / "cache.json"))
    cache.remember_memo("source", "first", 1)
    first_write = threading.Event()
    release = threading.Event()
    second_started = threading.Event()
    second_write = threading.Event()
    real_replace = ap.os.replace
    calls = []

    def replace(src, dst):
        calls.append(dst)
        if len(calls) == 1:
            first_write.set()
            assert release.wait(timeout=5)
        else:
            second_write.set()
        real_replace(src, dst)

    def save_second():
        second_started.set()
        return cache.save()

    monkeypatch.setattr(ap.os, "replace", replace)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cache.save)
        try:
            assert first_write.wait(timeout=5)
            cache.remember_memo("source", "second", 2)
            second = pool.submit(save_second)
            assert second_started.wait(timeout=5)
            overlap = second_write.wait(timeout=.1)
        finally:
            release.set()
        assert first.result(timeout=5)
        assert second.result(timeout=5)
    assert not overlap and len(calls) == 2
    assert ap.ShikimoriDbCache(cache.path).memo_group("source") == {"first": 1, "second": 2}
