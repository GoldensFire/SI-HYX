# -*- coding: utf-8 -*-
"""Кладовая каверов: что переживает перезапуск, а что обязано пересчитаться.

Ни сети, ни ffmpeg: кэш — это файлы и словари. Папка подменена autouse-фикстурой
conftest (реальный %APPDATA% тесты не трогают никогда).
"""
import json
import os
import time

import numpy as np
import pytest

import cover_cache as cache
import cover_match as match
from cover_meta import song_ref


@pytest.fixture(autouse=True)
def _dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", str(tmp_path / "covers"))


def _song(name="unravel", anime="Tokyo Ghoul", kind="Opening 1"):
    return song_ref({"annSongId": 77, "songName": name, "songArtist": "TK",
                     "songType": kind, "animeENName": anime,
                     "animeJPName": anime, "animeAltName": []})


def _found(*titles):
    return [{"id": f"vid{n}", "title": title, "channel": "Кто-то",
             "duration": 210, "views": 1000}
            for n, title in enumerate(titles)]


def _verdict(norm=6.0, reason=""):
    return {"score": norm * 30, "norm": norm, "shift": 0, "tempo": 1.0,
            "closeness": 0.3, "reason": reason}


def _windows(count=3, step=20.0):
    return [{"at": round(n * step, 2), "density": 0.9,
             "cover": (round(n * step + 5.0, 2), round(n * step + 25.0, 2))}
            for n in range(count)]


# ── файлы и ключи ────────────────────────────────────────────────────────
def test_key_is_the_composition_and_survives_odd_ids():
    """Ключ — annSongId; из него получается имя файла, а не путь."""
    assert cache.path("12345").endswith("12345.json")
    assert cache.path("a/b c").endswith("a_b_c.json")
    assert cache.path("") == "" and cache.chroma_path("") == ""


def test_missing_entry_reads_as_empty_not_as_error():
    assert cache.load("нет-такой") == {}
    assert cache.stale({}) is True


def test_titles_survive_the_roundtrip_in_utf8():
    """Японские и русские заголовки — обычное дело; cp1251 их не переживёт."""
    cache.remember_search("1", _found("【歌ってみた】unravel", "кавер на русском"))
    titles = [row["title"] for row in cache.load("1")["videos"].values()]
    assert "【歌ってみた】unravel" in titles and "кавер на русском" in titles
    raw = json.loads(open(cache.path("1"), encoding="utf-8").read())
    assert raw["videos"]["vid0"]["title"] == "【歌ってみた】unravel"


# ── срок годности поиска ─────────────────────────────────────────────────
def test_search_gets_stale_but_a_fresh_one_does_not():
    entry = cache.remember_search("1", _found("unravel cover"))
    assert cache.stale(entry) is False
    old = dict(entry, searched=time.time() - cache.SEARCH_TTL_DAYS * cache.DAY - 1)
    assert cache.stale(old) is True


def test_second_search_adds_to_the_first_instead_of_replacing_it():
    cache.remember_search("1", _found("unravel cover"))
    cache.remember_search("1", [{"id": "vid9", "title": "unravel piano cover",
                                 "duration": 200}])
    assert set(cache.load("1")["videos"]) == {"vid0", "vid9"}


# ── гейт считается заново ────────────────────────────────────────────────
def test_gate_is_recomputed_from_stored_titles_not_frozen():
    """Правки словаря правил обязаны действовать на уже собранный кэш."""
    cache.remember_search("1", _found("unravel cover", "unravel REACTION"))
    pool, rejected = cache.screened(cache.load("1"), _song())
    assert [row["id"] for row in pool] == ["vid0"]
    assert [row["reason"] for row in rejected] == ["reaction"]


def test_stored_row_carries_the_gate_verdict_into_the_pool():
    cache.remember_search("1", _found("unravel piano cover"))
    pool, _bad = cache.screened(cache.load("1"), _song())
    assert pool[0]["strength"] == "strong" and pool[0]["type"] == "piano"
    assert pool[0]["checked"] is False and pool[0]["windows"] == []


# ── вердикты звука ───────────────────────────────────────────────────────
def test_audio_verdict_and_windows_come_back_unchanged():
    cache.remember_search("1", _found("unravel cover"))
    cache.remember_audio("1", "vid0", _verdict(norm=6.5), _windows(3))
    row = cache.screened(cache.load("1"), _song())[0][0]
    assert row["checked"] is True and row["norm"] == 6.5
    assert [w["at"] for w in row["windows"]] == [0.0, 20.0, 40.0]
    assert row["windows"][1]["cover"] == (25.0, 45.0)
    assert cache.confirmed([row]) == [row]


def test_raising_the_threshold_drops_the_candidate_without_redownloading():
    """Хранится сырой счёт: правка порога не стоит повторной загрузки."""
    cache.remember_search("1", _found("unravel cover"))
    cache.remember_audio("1", "vid0", _verdict(norm=3.2), _windows(2))
    row = cache.screened(cache.load("1"), _song())[0][0]
    assert cache.confirmed([row])
    saved = match.MIN_SCORE
    try:
        match.MIN_SCORE = 5.0
        assert cache.confirmed([row]) == []
        assert row["norm"] == 3.2          # сам вердикт не тронут
    finally:
        match.MIN_SCORE = saved


def test_a_verdict_from_another_chroma_version_is_recomputed():
    cache.remember_search("1", _found("unravel cover"))
    cache.remember_audio("1", "vid0", _verdict(), _windows(2))
    entry = cache.load("1")
    entry["audio"]["vid0"]["version"] = "chroma-0"
    cache.save("1", entry)
    row = cache.screened(cache.load("1"), _song())[0][0]
    assert row["checked"] is False
    assert cache.confirmed([row]) == [] and cache.unchecked([row]) == [row]


def test_a_scored_candidate_without_windows_is_not_confirmed():
    """Счёт есть, а связного окна нет — резать нечего (reason no_window)."""
    cache.remember_search("1", _found("unravel cover"))
    cache.remember_audio("1", "vid0", _verdict(reason="no_window"), [])
    row = cache.screened(cache.load("1"), _song())[0][0]
    assert cache.confirmed([row]) == []


# ── история ──────────────────────────────────────────────────────────────
def test_use_counts_remembers_the_window_and_the_last_video():
    cache.remember_search("1", _found("unravel cover"))
    cache.remember_audio("1", "vid0", _verdict(), _windows(3))
    cache.remember_use("1", "vid0", 20.0, when=1000)
    entry = cache.remember_use("1", "vid0", 40.0, when=2000)
    assert cache.last_used(entry) == "vid0"
    row = cache.screened(entry, _song())[0][0]
    assert row["uses"] == 2 and row["used"] == [20.0, 40.0]
    assert row["last_used"] == 2000


def test_used_windows_are_capped_so_the_file_cannot_grow_forever():
    cache.remember_search("1", _found("unravel cover"))
    for number in range(cache.USED_LIMIT + 5):
        cache.remember_use("1", "vid0", float(number))
    used = cache.load("1")["use"]["vid0"]["at"]
    assert len(used) == cache.USED_LIMIT and used[-1] == cache.USED_LIMIT + 4


def test_a_video_that_keeps_failing_stops_being_offered():
    cache.remember_search("1", _found("unravel cover"))
    for _ in range(cache.FAIL_LIMIT):
        cache.remember_failure("1", "vid0", "yt-dlp: 403")
    row = cache.screened(cache.load("1"), _song())[0][0]
    assert row["fails"] == cache.FAIL_LIMIT and cache.unchecked([row]) == []


# ── хрома эталона ────────────────────────────────────────────────────────
def test_reference_chroma_is_stored_next_to_the_findings():
    chroma = np.random.default_rng(0).random((40, 12), dtype=np.float32)
    assert cache.put_ref_chroma("1", chroma) is True
    assert np.array_equal(cache.ref_chroma("1"), chroma)
    assert cache.ref_chroma("2") is None


def test_a_broken_chroma_file_is_ignored_instead_of_crashing():
    os.makedirs(cache.CACHE_DIR, exist_ok=True)
    np.save(cache.chroma_path("1"), np.zeros((5, 7), dtype=np.float32))
    assert cache.ref_chroma("1") is None


# ── обслуживание ─────────────────────────────────────────────────────────
def test_prune_drops_the_oldest_until_the_cache_fits():
    for number in range(3):
        cache.remember_search(str(number), _found("unravel cover" * 200))
    os.utime(cache.path("0"), (1000, 1000))
    songs, size = cache.stats()
    assert songs == 3 and size > 0
    assert cache.prune(limit_mb=0) == 0          # потолок 0 — не трогаем ничего
    gone = cache.prune(limit_mb=max(1, size // (1024 * 1024)))
    assert gone in (0, 1)
    assert cache.clear() >= 1 and cache.stats() == (0, 0)


# ── срок годности осечек ─────────────────────────────────────────────────
def test_a_stale_failure_is_forgiven_and_the_video_comes_back():
    """Осечка загрузки — чаще про минуту, чем про ролик.

    YouTube, режущий по частоте запросов, отвечает «Video unavailable» и
    вполне живому ролику. Без срока один такой прогон вычёркивал кандидата
    навсегда: поле `last` писалось, а читать его было некому."""
    cache.remember_search("1", _found("unravel cover"))
    for _ in range(cache.FAIL_LIMIT):
        cache.remember_failure("1", "vid0", "Video unavailable")
    entry = cache.load("1")
    old = time.time() - (cache.FAIL_TTL_DAYS + 1) * cache.DAY
    entry["fail"]["vid0"]["last"] = int(old)
    cache.save("1", entry)

    row = cache.screened(cache.load("1"), _song())[0][0]
    assert row["fails"] == 0
    assert cache.unchecked([row]) == [row]


def test_the_failure_counter_restarts_after_the_ttl():
    """Три осечки должны означать «ролик не даётся раз за разом», а не
    «не дался однажды в марте, однажды в мае и однажды сегодня»."""
    cache.remember_search("1", _found("unravel cover"))
    for _ in range(cache.FAIL_LIMIT - 1):
        cache.remember_failure("1", "vid0", "yt-dlp: 403")
    entry = cache.load("1")
    entry["fail"]["vid0"]["last"] = int(time.time()
                                        - (cache.FAIL_TTL_DAYS + 1) * cache.DAY)
    cache.save("1", entry)

    cache.remember_failure("1", "vid0", "yt-dlp: 403")
    assert cache.load("1")["fail"]["vid0"]["n"] == 1
    row = cache.screened(cache.load("1"), _song())[0][0]
    assert cache.unchecked([row]) == [row]


def test_fresh_failures_still_add_up():
    """Срок не должен отменять саму защиту: ролик, который не даётся подряд,
    из очереди по-прежнему выбывает."""
    cache.remember_search("1", _found("unravel cover"))
    for _ in range(cache.FAIL_LIMIT):
        cache.remember_failure("1", "vid0", "yt-dlp: 403")
    row = cache.screened(cache.load("1"), _song())[0][0]
    assert row["fails"] == cache.FAIL_LIMIT and cache.unchecked([row]) == []
