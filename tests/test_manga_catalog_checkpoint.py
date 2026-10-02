# -*- coding: utf-8 -*-
"""A slow checkpoint does not stop collection or lose newer details on close."""
from concurrent.futures import ThreadPoolExecutor
import threading

import animepack as api
from si_hyx_parts.animepack.catalog_checkpoint import CatalogCheckpoint


def test_background_checkpoint_keeps_collecting_and_flushes_later_answers(tmp_path, monkeypatch):
    cache = api.ShikimoriDbCache(str(tmp_path / "cache.json"))
    cache.remember_memo("details", "first", 1)
    writing = threading.Event()
    release = threading.Event()
    replacements = []
    original = api.os.replace

    def replace(source, destination):
        replacements.append(destination)
        if len(replacements) == 1:
            writing.set()
            assert release.wait(timeout=5)
        original(source, destination)

    monkeypatch.setattr(api.os, "replace", replace)
    checkpoint = CatalogCheckpoint(cache)
    try:
        assert checkpoint.schedule()
        assert writing.wait(timeout=5)
        cache.remember_memo("details", "later", 2)
        assert not checkpoint.schedule()  # No overlapping write or growing queue.
        release.set()
    finally:
        release.set()
        checkpoint.close()
    assert api.ShikimoriDbCache(cache.path).memo_group("details") == {"first": 1, "later": 2}
    assert len(replacements) == 2


def test_close_waits_for_the_inflight_checkpoint(tmp_path, monkeypatch):
    cache = api.ShikimoriDbCache(str(tmp_path / "cache.json"))
    cache.remember_memo("details", "first", 1)
    writing = threading.Event()
    release = threading.Event()
    original = cache.save

    def save():
        writing.set()
        assert release.wait(timeout=5)
        return original()

    monkeypatch.setattr(cache, "save", save)
    checkpoint = CatalogCheckpoint(cache)
    assert checkpoint.schedule()
    assert writing.wait(timeout=5)
    with ThreadPoolExecutor(max_workers=1) as pool:
        closing = pool.submit(checkpoint.close)
        try:
            assert not closing.done()
        finally:
            release.set()
        closing.result(timeout=5)
    assert api.ShikimoriDbCache(cache.path).memo("details", "first") == 1
