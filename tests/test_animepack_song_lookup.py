# -*- coding: utf-8 -*-
"""Песни запрашиваются только для ещё нужной доли и подходящих карточек."""
import animepack as ap
from test_animepack_mixed_streams import _generator, make_anime, make_song


def _feed(gen):
    return ap.AnimeCardFeed(gen, gen.collect_anime_ids(), want_songs=True)


def test_filled_song_quota_stops_requests_and_keeps_remaining_titles(
        tmp_path, monkeypatch):
    monkeypatch.setattr(ap, "ANISONG_BATCH", 1)
    cards = [make_anime(i) for i in range(1, 5)]
    gen = _generator(tmp_path, monkeypatch, cards, [make_song(i) for i in range(1, 5)])
    feed = _feed(gen)
    candidates = feed.songs(gen._used_franchise)
    assert next(candidates).mal_id == 1
    gen._song_lookup_needed = False
    remaining = list(candidates)
    assert [cand.mal_id for cand in remaining] == [2, 3, 4]
    assert all(cand.kind == ap.FRAME_KIND for cand in remaining)
    assert gen.anisong.asked == [[1]]


def test_song_requests_resume_if_redistributed_quota_needs_songs_again(
        tmp_path, monkeypatch):
    monkeypatch.setattr(ap, "ANISONG_BATCH", 1)
    cards = [make_anime(i) for i in range(1, 4)]
    gen = _generator(tmp_path, monkeypatch, cards, [make_song(i) for i in range(1, 4)])
    candidates = _feed(gen).songs(gen._used_franchise)
    assert next(candidates).kind == "opening"
    gen._song_lookup_needed = False
    assert next(candidates).kind == ap.FRAME_KIND
    gen._song_lookup_needed = True
    assert next(candidates).kind == "opening"
    assert gen.anisong.asked == [[1], [3]]


def test_cached_filtered_and_excluded_titles_are_removed_before_song_request(
        tmp_path, monkeypatch):
    cards = [make_anime(1), make_anime(2, airedOn={"year": 1900}), make_anime(3)]
    gen = _generator(tmp_path, monkeypatch, cards, [make_song(i) for i in range(1, 4)],
                     year_from=2000)
    gen._card_cache.update({card["malId"]: card for card in cards})
    gen._excluded_franchises.add("fr3")
    feed = _feed(gen)
    _songs, _siblings, ids = feed._ask_songs([1, 2, 3, 4])
    assert gen.anisong.asked == [[1, 4]]  # unknown card keeps its chance
    assert ids == [1, 2, 3, 4]
    assert gen._used_franchise == set()  # early filter never reserves titles


def test_ann_catalog_still_looks_up_mal_identifiers_when_songs_are_full(
        tmp_path, monkeypatch):
    gen = _generator(tmp_path, monkeypatch, [], [])
    monkeypatch.setattr(type(gen), "_ids_are_ann", property(lambda self: True))
    asked = []
    gen.anisong.songs_by_ann_ids = lambda ids: asked.append(list(ids)) or [make_song(7)]
    gen._song_lookup_needed = False
    _songs, _siblings, mapped = _feed(gen)._ask_songs([700])
    assert asked == [[700]]
    assert mapped == [7]


def test_completed_song_rows_are_available_to_silent_questions(
        tmp_path, monkeypatch):
    cards = [make_anime(1), make_anime(2)]
    gen = _generator(tmp_path, monkeypatch, cards, [make_song(1), make_song(2)])
    feed = _feed(gen)
    assert next(feed._source)
    assert len(feed.with_song) == 2
    gen._song_lookup_needed = False
    candidates = list(feed.pictures(ap.FRAME_KIND, gen._used_franchise))
    assert {cand.mal_id for cand in candidates} == {1, 2}
