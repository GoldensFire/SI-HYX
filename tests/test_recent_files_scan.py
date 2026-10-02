# -*- coding: utf-8 -*-
"""Slow folders cannot block Qt, enqueue duplicate scans, or show stale results."""
import os
import threading
import time

from PyQt6.QtCore import QTimer

from si_hyx_parts.widgets import recent_files_scan as scanning


def _until(qapp, condition):
    deadline = time.monotonic() + 5
    while not condition() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(.005)
    assert condition()


def test_scan_returns_only_the_newest_allowed_files(tmp_path):
    paths = []
    for number in range(45):
        path = tmp_path / f"{number:02}.mp4"
        path.write_bytes(b"x")
        os.utime(path, (number + 1, number + 1))
        paths.append(str(path))
    (tmp_path / "new.txt").write_text("excluded", encoding="utf-8")
    (tmp_path / "directory.mp4").mkdir()
    assert scanning.scan_recent(str(tmp_path), "media", {".mp4"}, set()) == paths[-1:14:-1]
    assert scanning.scan_recent(str(tmp_path), "all", set(), {".txt"}) == paths[-1:14:-1]
    assert scanning.scan_recent(str(tmp_path / "missing"), "all", set(), set()) == []


def test_slow_scan_leaves_gui_timers_running_and_coalesces_requests(qapp, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls, results, ticks = [], [], []
    gui_thread = threading.get_ident()

    def slow_scan(*request):
        calls.append(threading.get_ident())
        entered.set()
        assert release.wait(5)
        return [request[0]]

    monkeypatch.setattr(scanning, "scan_recent", slow_scan)
    scanner = scanning.DirectoryScanner()
    scanner.ready.connect(results.append)
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(5)
    try:
        scanner.request("old", "media", {".mp4"}, set())
        _until(qapp, entered.is_set)
        for _ in range(20):
            scanner.request("old", "media", {".mp4"}, set())
        _until(qapp, lambda: bool(ticks))
        assert not results
        assert len(calls) == 1 and calls[0] != gui_thread
    finally:
        release.set()
        timer.stop()
        _until(qapp, lambda: scanner.task is None)
    assert results == [["old"]]


def test_folder_changed_during_scan_discards_old_results(qapp, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls, results = [], []

    def slow_scan(folder, *_):
        calls.append(folder)
        if folder == "old":
            entered.set()
            assert release.wait(5)
        return [folder]

    monkeypatch.setattr(scanning, "scan_recent", slow_scan)
    scanner = scanning.DirectoryScanner()
    scanner.ready.connect(results.append)
    try:
        scanner.request("old", "media", set(), set())
        _until(qapp, entered.is_set)
        scanner.request("new", "media", set(), set())
    finally:
        release.set()
        _until(qapp, lambda: scanner.task is None)
    assert calls == ["old", "new"]
    assert results == [["new"]]
