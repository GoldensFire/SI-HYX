# -*- coding: utf-8 -*-
"""A generation must not rewrite the entire database for every API batch."""
from types import SimpleNamespace

import pytest

import animepack as ap
from si_hyx_parts.animepack.generation_checkpoint import checkpoint
from test_animepack_mixed_streams import _generator, make_anime


def _gen(tmp_path, monkeypatch):
    gen = _generator(tmp_path, monkeypatch, [], [], questions=6,
                     pct_songs=0, pct_frames=100)
    gen.db_cache = ap.ShikimoriDbCache(str(tmp_path / "metadata.json"))
    gen.shikimori = SimpleNamespace(franchise_parts=lambda keys: {k: [] for k in keys})
    real_load = ap.AnimePackGenerator._load_franchise_indexes.__get__(gen)
    saves = []
    save = gen.db_cache.save

    def observed_save():
        saves.append(1)
        return save()

    monkeypatch.setattr(gen.db_cache, "save", observed_save)
    monkeypatch.setattr(gen, "_fetch_media", lambda _candidate: True)
    return gen, real_load, saves


def test_many_franchise_batches_are_saved_once_at_selection_end(tmp_path, monkeypatch):
    gen, load, saves = _gen(tmp_path, monkeypatch)

    def candidates():
        for number in range(1, 7):
            card = make_anime(number)
            load([card])
            assert not saves
            yield ap.SongCandidate({}, card, kind=ap.FRAME_KIND)

    monkeypatch.setattr(gen, "iter_candidates", candidates)
    assert len(gen.select_songs()) == 6
    assert saves == [1]
    saved = ap.ShikimoriDbCache(gen.db_cache.path)
    assert all(saved.franchise(f"fr{number}") == [] for number in range(1, 7))
    assert gen._defer_cache_writes is False


def test_candidate_failure_still_saves_new_metadata(tmp_path, monkeypatch):
    gen, load, saves = _gen(tmp_path, monkeypatch)

    def candidates():
        load([make_anime(1)])
        raise RuntimeError("catalog failed")
        yield

    monkeypatch.setattr(gen, "iter_candidates", candidates)
    with pytest.raises(RuntimeError, match="catalog failed"):
        gen.select_songs()
    assert saves == [1]
    assert ap.ShikimoriDbCache(gen.db_cache.path).franchise("fr1") == []
    assert gen._defer_cache_writes is False


def test_cancelled_selection_still_saves_new_metadata(tmp_path, monkeypatch):
    gen, load, saves = _gen(tmp_path, monkeypatch)
    cancelled = []
    gen._should_stop = lambda: bool(cancelled)

    def candidates():
        card = make_anime(1)
        load([card])
        cancelled.append(True)
        yield ap.SongCandidate({}, card, kind=ap.FRAME_KIND)

    monkeypatch.setattr(gen, "iter_candidates", candidates)
    gen.select_songs()
    assert saves == [1]
    assert ap.ShikimoriDbCache(gen.db_cache.path).franchise("fr1") == []


def test_refresh_outside_selection_still_checkpoints_immediately(tmp_path, monkeypatch):
    gen, load, saves = _gen(tmp_path, monkeypatch)
    load([make_anime(1)])
    assert saves == [1]
    assert ap.ShikimoriDbCache(gen.db_cache.path).franchise("fr1") == []
    assert checkpoint(gen) is False  # unchanged database
