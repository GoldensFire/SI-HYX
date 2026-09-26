# -*- coding: utf-8 -*-
"""Чистилка кладовой каверов: что считается стенкой, а что осечкой ролика.

Ни сети, ни yt-dlp: скрипт читает и переписывает json-файлы кладовой. Папка —
tmp_path, реальный %APPDATA% тесты не трогают никогда.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))

import clean_cover_cache as cleaner  # noqa: E402 — путь добавлен выше


def _entry(**fails):
    return {"song_id": "1", "song": "unravel",
            "videos": {vid: {"title": f"unravel cover {vid}"} for vid in fails},
            "audio": {vid: {"version": "chroma-2", "norm": 0.9}
                      for vid in fails},
            "fail": {vid: {"n": 1, "last": 1, "reason": reason}
                     for vid, reason in fails.items()}}


def _write(directory, name, entry):
    path = directory / f"{name}.json"
    path.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.mark.parametrize("reason", [
    "w-do-i-pass-cookies-to-yt-dlp  for how to manually pass cookies. Also ",
    "p` to add a delay between video requests to avoid exceeding the rate l",
    "ERROR: [youtube] x: This content isn't available, try again later.",
    "ERROR: unable to download video data: HTTP Error 403: Forbidden",
    "yt-dlp не отдал звук",
    "ERROR: [youtube] a: Video unavailable\nERROR: [youtube] b: Video unavailable",
    "",
])
def test_wall_reasons_are_recognised(reason):
    """Всё это записано про YouTube целиком, а не про конкретный ролик."""
    assert cleaner.is_wall(reason) is True


@pytest.mark.parametrize("reason", [
    "ERROR: [youtube] x: Video unavailable",
    "ffmpeg не разобрал звук",
    "Invalid data found when processing input",
])
def test_real_video_failures_survive(reason):
    """Один снятый ролик и битый звук — показания про сам ролик."""
    assert cleaner.is_wall(reason) is False


def test_only_the_wall_records_are_dropped(tmp_path):
    entry = _entry(v0="yt-dlp не отдал звук",
                   v1="ffmpeg не разобрал звук",
                   v2="try again later")
    fresh, gone, kept = cleaner.clean_entry(entry)
    assert (gone, kept) == (2, 1)
    assert set(fresh["fail"]) == {"v1"}


def test_verdicts_and_findings_are_left_alone(tmp_path):
    """Вердикты звука стенкой не испорчены: их пересчёт стоит загрузки и
    полутора секунд ЦПУ на каждого кандидата."""
    entry = _entry(v0="try again later")
    fresh, _gone, _kept = cleaner.clean_entry(entry)
    assert fresh["audio"] == entry["audio"]
    assert fresh["videos"] == entry["videos"]
    assert "fail" not in fresh


def test_a_dry_run_counts_without_touching_the_files(tmp_path):
    path = _write(tmp_path, "song", _entry(v0="try again later"))
    before = path.read_text(encoding="utf-8")
    songs, dropped, kept = cleaner.sweep(str(tmp_path), apply=False)
    assert (songs, dropped, kept) == (1, 1, 0)
    assert path.read_text(encoding="utf-8") == before


def test_apply_rewrites_only_what_it_promised(tmp_path):
    walled = _write(tmp_path, "walled", _entry(v0="try again later"))
    honest = _write(tmp_path, "honest", _entry(v0="ffmpeg не разобрал звук"))
    kept_before = honest.read_text(encoding="utf-8")

    songs, dropped, kept = cleaner.sweep(str(tmp_path), apply=True)
    assert (songs, dropped, kept) == (1, 1, 1)
    assert "fail" not in json.loads(walled.read_text(encoding="utf-8"))
    assert honest.read_text(encoding="utf-8") == kept_before


def test_a_broken_file_does_not_stop_the_sweep(tmp_path):
    (tmp_path / "junk.json").write_text("не json", encoding="utf-8")
    _write(tmp_path, "song", _entry(v0="try again later"))
    assert cleaner.sweep(str(tmp_path), apply=True)[1] == 1
