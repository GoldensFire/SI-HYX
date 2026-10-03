# -*- coding: utf-8 -*-
"""Медленный каталог не задерживает готовые вопросы и рост параллелизма."""
import threading

import animepack as ap
from test_animepack_mixed_streams import _generator, make_anime


def test_song_average_uses_saved_favorites_before_media_selection(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from test_animepack_mixed_streams import make_song
    card = make_anime(1)
    gen = _generator(tmp_path, monkeypatch, [card], [make_song(1)], pct_songs=100, pct_frames=0)
    gen.db_cache.remember_memo("anime_favorites", card["id"], 5000)
    gen.shikimori = SimpleNamespace(title_favorites=lambda *_: 0)
    candidate = next(gen.iter_candidates())
    assert candidate.favorites == 5000
    before = candidate.level
    candidate.favorites = gen._title_favorites(candidate)
    assert candidate.favorites == 5000
    assert candidate.level == before, "Сохранённое избранное меняет уровень после выбора средней"


def _frame(number):
    return ap.SongCandidate({}, make_anime(number), kind=ap.FRAME_KIND)


def _run_in_thread(gen):
    results, errors = [], []

    def run():
        try:
            results.extend(gen.select_songs())
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=run)
    thread.start()
    return thread, results, errors


def test_finished_media_is_accepted_while_next_catalog_request_is_blocked(
        tmp_path, monkeypatch):
    gen = _generator(tmp_path, monkeypatch, [], [], pct_songs=0, pct_frames=100,
                     questions=2)
    catalog_waiting, allow_catalog = threading.Event(), threading.Event()
    accepted = threading.Event()

    def candidates():
        yield _frame(1)
        catalog_waiting.set()
        assert allow_catalog.wait(5)
        yield _frame(2)

    def fetch(candidate):
        if candidate.mal_id == 1:
            assert catalog_waiting.wait(5)
        return True

    monkeypatch.setattr(gen, "iter_candidates", candidates)
    monkeypatch.setattr(gen, "_fetch_media", fetch)
    gen._progress = lambda done, _total, _label: accepted.set() if done == 1 else None
    thread, results, errors = _run_in_thread(gen)
    try:
        assert catalog_waiting.wait(5)
        assert accepted.wait(5), "Готовый вопрос ждал окончания сетевого поиска"
        assert not allow_catalog.is_set()
    finally:
        allow_catalog.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert not errors
    assert len(results) == 2


def test_generation_started_low_can_grow_to_all_requested_workers(
        tmp_path, monkeypatch):
    gen = _generator(tmp_path, monkeypatch, [], [], pct_songs=0, pct_frames=100,
                     questions=8, parallel=8, generation_priority="low")
    changed = threading.Condition()
    release = threading.Event()
    started = []
    monkeypatch.setattr(gen, "iter_candidates", lambda: (_frame(i) for i in range(8)))

    def fetch(candidate):
        with changed:
            started.append(candidate.mal_id)
            changed.notify_all()
        assert release.wait(5)
        return True

    monkeypatch.setattr(gen, "_fetch_media", fetch)
    thread, results, errors = _run_in_thread(gen)
    try:
        with changed:
            assert changed.wait_for(lambda: len(started) == 2, timeout=5)
        gen._runtime.set_priority("high")
        with changed:
            assert changed.wait_for(lambda: len(started) == 8, timeout=5)
    finally:
        release.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert not errors
    assert len(results) == 8


def test_stopping_during_candidate_search_joins_the_producer(tmp_path, monkeypatch):
    gen = _generator(tmp_path, monkeypatch, [], [], pct_songs=0, pct_frames=100)
    started, stopped = threading.Event(), threading.Event()

    def candidates():
        started.set()
        while not gen.stopped():
            stopped.wait(.01)
        return
        yield  # make the cancellable test source an iterator

    monkeypatch.setattr(gen, "iter_candidates", candidates)
    gen._should_stop = stopped.is_set
    thread, results, errors = _run_in_thread(gen)
    assert started.wait(5)
    stopped.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert not errors
    assert results == []
