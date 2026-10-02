# -*- coding: utf-8 -*-
"""Повторы не тратят медиа, а неудачная попытка возвращает свою бронь."""
from types import SimpleNamespace

import animepack as ap
from si_hyx_parts.animepack import early_repeat, sakuga_generation
from si_hyx_parts.animepack.exact_repeat import known_keys


def _candidate(number=1, kind="opening"):
    card = {"id": 1, "malId": 1, "russian": "Тестовое аниме",
            "name": "Test anime", "kind": "tv", "airedOn": {"year": 2020}}
    song = {"songType": f"Opening {number}", "songName": f"Song {number}"}
    return ap.SongCandidate(song if kind == "opening" else {}, card, kind=kind)


def _generator(tmp_path, monkeypatch):
    monkeypatch.setattr(ap, "CONFIG_DIR", str(tmp_path))
    settings = ap.PackSettings(rounds=1, themes=1, questions=1, parallel=2)
    return ap.AnimePackGenerator(
        settings, session=object(), shikimori=object(), anisong=object(),
        amq=object(), mal=object(), tmdb=object())


def test_old_song_is_rejected_before_media_and_other_opening_survives(
        tmp_path, monkeypatch):
    gen = _generator(tmp_path, monkeypatch)
    old, fresh = _candidate(1), _candidate(2)
    gen._exact_keys = known_keys(old)
    monkeypatch.setattr(gen, "iter_candidates", lambda: iter([old, fresh]))
    monkeypatch.setattr(gen, "_pick_kind", lambda *args: "opening")
    monkeypatch.setattr(gen, "_level_fits", lambda *args: True)
    fetched = []
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: fetched.append(cand) or True)
    assert gen.select_songs() == [fresh]
    assert fetched == [fresh]
    assert gen._tries["opening"] == 1
    assert gen._early_repeats == 1
    assert not gen._exact_pending


def test_parallel_reservation_is_released_after_failure(tmp_path, monkeypatch):
    gen = _generator(tmp_path, monkeypatch)
    gen._exact_keys = {("source", "https://old.invalid/1")}
    first, concurrent, replacement = _candidate(), _candidate(), _candidate()
    assert early_repeat.reserve(gen, first)
    assert early_repeat.reserve(gen, first)  # своя бронь не мешает
    assert not early_repeat.reserve(gen, concurrent)
    assert concurrent._exact_waiting
    early_repeat.release(gen, first)
    assert early_repeat.reserve(gen, replacement)
    assert gen._early_repeats == 0


def test_waiting_song_can_replace_a_failed_parallel_attempt(tmp_path, monkeypatch):
    import time
    gen = _generator(tmp_path, monkeypatch)
    gen.s.questions = 2
    gen.s.openings, gen.s.endings, gen.s.inserts = 100, 0, 0
    gen._exact_keys = {("source", "https://old.invalid/1")}
    first, replacement, other = _candidate(), _candidate(), _candidate(2)
    monkeypatch.setattr(gen, "iter_candidates", lambda: iter([first, replacement, other]))
    monkeypatch.setattr(gen, "_pick_kind", lambda *args: "opening")
    monkeypatch.setattr(gen, "_level_fits", lambda *args: True)
    def fetch(candidate):
        if candidate is first:
            time.sleep(0.02)
            return False
        return True
    monkeypatch.setattr(gen, "_fetch_media", fetch)
    assert set(map(id, gen.select_songs())) == {id(replacement), id(other)}
    assert not gen._exact_pending


def test_old_sakuga_post_never_reaches_download_or_encoder(tmp_path, monkeypatch):
    gen = _generator(tmp_path, monkeypatch)
    cand = _candidate(kind=ap.SAKUGA_KIND)
    gen._exact_keys = {("source", ap.sakuga_post_link(123).casefold())}
    gen.sakuga = SimpleNamespace(clip=lambda *_: {
        "id": 123, "url": "https://video.invalid/123.mp4"})
    encoded = []
    monkeypatch.setattr(sakuga_generation, "_encode",
                        lambda *args: encoded.append(args) or True)
    assert not gen.download_sakuga(cand)
    assert not encoded
    assert cand._exact_duplicate
    assert gen._early_repeats == 1


def test_final_hash_check_still_rejects_identical_images(tmp_path, monkeypatch):
    import hashlib
    gen = _generator(tmp_path, monkeypatch)
    gen.folder = str(tmp_path)
    images = tmp_path / "Images"
    images.mkdir()
    cand = _candidate(kind=ap.FRAME_KIND)
    cand.frame_name = "same.png"
    cand.has_frame = True
    (images / cand.frame_file).write_bytes(b"same image")
    gen._exact_keys = {("media", hashlib.sha256(b"same image").hexdigest())}
    assert early_repeat.reserve(gen, cand)
    assert not early_repeat.accept(gen, cand)
