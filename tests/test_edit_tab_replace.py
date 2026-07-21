# -*- coding: utf-8 -*-
"""Перенос результата обрезки temp → final: занятая цель (WinError 32) и
перенос между дисками (WinError 17 / EXDEV)."""
import errno
import os

import pytest

edit_tab = pytest.importorskip("edit_tab")
EditTab = edit_tab.EditTab


def _write(path, data=b"data"):
    with open(path, "wb") as f:
        f.write(data)
    return str(path)


def test_move_tolerant_plain(tmp_path):
    temp = _write(tmp_path / "tmp.mp4")
    final = str(tmp_path / "out.mp4")
    assert EditTab._move_tolerant(temp, final) == final
    assert os.path.exists(final) and not os.path.exists(temp)


def test_replace_tolerant_cross_drive(tmp_path, monkeypatch):
    """os.replace между дисками падает с WinError 17 — результат обязан
    сохраниться копированием, а не потеряться с ошибкой."""
    temp = _write(tmp_path / "tmp.mp4", b"payload")
    final = str(tmp_path / "out.mp4")

    def _fake_replace(src, dst):
        err = OSError(errno.EXDEV, "cannot move the file to a different disk drive")
        err.winerror = 17
        raise err

    monkeypatch.setattr(edit_tab.os, "replace", _fake_replace)
    assert EditTab._replace_tolerant(temp, final) == final
    with open(final, "rb") as f:
        assert f.read() == b"payload"
    assert not os.path.exists(temp)


def test_replace_tolerant_cross_drive_overwrites_existing(tmp_path, monkeypatch):
    temp = _write(tmp_path / "tmp.mp4", b"new")
    final = _write(tmp_path / "out.mp4", b"old")

    def _fake_replace(src, dst):
        err = OSError(errno.EXDEV, "different disk drive")
        err.winerror = 17
        raise err

    monkeypatch.setattr(edit_tab.os, "replace", _fake_replace)
    assert EditTab._replace_tolerant(temp, final) == final
    with open(final, "rb") as f:
        assert f.read() == b"new"


def test_replace_tolerant_busy_target_gets_new_name(tmp_path, monkeypatch):
    """Занятая цель (её читает «Обработка») → соседнее свободное имя."""
    temp = _write(tmp_path / "tmp.mp4")
    final = _write(tmp_path / "out.mp4", b"busy")  # цель существует и «занята»
    calls = {"n": 0}
    real_replace = os.replace

    def _fake_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            err = PermissionError(13, "used by another process")
            err.winerror = 32
            raise err
        return real_replace(src, dst)

    monkeypatch.setattr(edit_tab.os, "replace", _fake_replace)
    saved = EditTab._replace_tolerant(temp, final)
    assert os.path.normpath(saved) != os.path.normpath(final)
    assert os.path.exists(saved)


def test_make_temp_out_sits_next_to_final(tmp_path):
    """Временный файл создаётся рядом с результатом — иначе на другом диске
    ловим WinError 17."""
    final = str(tmp_path / "video.mkv")
    temp = EditTab._make_temp_out(final)
    try:
        assert os.path.dirname(temp) == str(tmp_path)
        assert temp.endswith(".mkv")
        assert os.path.exists(temp)
    finally:
        os.remove(temp)


def test_make_temp_out_falls_back_to_system_temp(tmp_path):
    """Каталог назначения недоступен на запись → системный temp (перенос
    вытянет _move_tolerant)."""
    final = str(tmp_path / "nope" / "video.mp4")  # каталога не существует
    temp = EditTab._make_temp_out(final)
    try:
        assert os.path.exists(temp)
        assert temp.endswith(".mp4")
    finally:
        os.remove(temp)
