# -*- coding: utf-8 -*-
"""Смена приоритета влияет на активные задачи, процессы и поле вкладки."""
from concurrent.futures import ThreadPoolExecutor
import ctypes
import os
import subprocess
import sys
import threading

import pytest

import animepack as ap
import animepack_tab
from si_hyx_parts.animepack.generation_priority import current_thread_level
from si_hyx_parts.animepack.generation_runtime import GenerationRuntime
from test_animepack_tab_mix import _FakeMain


@pytest.mark.parametrize("initial,changed", [("high", "low"), ("low", "high")])
def test_dropdown_changes_active_task_without_changing_queued_snapshot(
        qapp, initial, changed):
    class Pool:
        def start(self, task):
            self.task = task

    tab = animepack_tab.AnimePackTab(main_window=_FakeMain())
    tab._pool = Pool()
    try:
        combo = tab.cb_generation_priority
        combo.setCurrentIndex(combo.findData(initial))
        tab.start()
        task = tab._task
        tab.start()
        queued = tab._queue[0]
        combo.setCurrentIndex(combo.findData(changed))
        assert combo.isEnabled()
        assert task.settings.generation_priority == changed
        assert task._runtime.settings.generation_priority == changed
        assert queued.generation_priority == initial
    finally:
        tab.cleanup()


def test_increasing_priority_releases_workers_already_waiting():
    runtime = GenerationRuntime(ap.PackSettings(parallel=4, generation_priority="low"))
    entered = threading.Condition()
    release = threading.Event()
    active = []

    def work(number):
        with entered:
            active.append(number)
            entered.notify_all()
        assert release.wait(5)

    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(runtime.wrap_task(work), i) for i in range(4)]
        try:
            with entered:
                assert entered.wait_for(lambda: len(active) == 2, timeout=5)
            runtime.set_priority("high")
            with entered:
                assert entered.wait_for(lambda: len(active) == 4, timeout=5)
        finally:
            release.set()
        for job in jobs:
            job.result()


def test_lowering_priority_waits_for_existing_work_before_starting_more():
    runtime = GenerationRuntime(ap.PackSettings(parallel=4, generation_priority="high"))
    entered = threading.Condition()
    release = [threading.Event() for _ in range(5)]
    active = []

    def work(number):
        with entered:
            active.append(number)
            entered.notify_all()
        assert release[number].wait(5)

    with ThreadPoolExecutor(max_workers=5) as pool:
        first = [pool.submit(runtime.wrap_task(work), i) for i in range(4)]
        try:
            with entered:
                assert entered.wait_for(lambda: len(active) == 4, timeout=5)
            runtime.set_priority("low")
            next_job = pool.submit(runtime.wrap_task(work), 4)
            release[0].set()
            release[1].set()
            first[0].result(timeout=5)
            first[1].result(timeout=5)
            assert runtime.active_tasks == 2
            assert len(active) == 4
            release[2].set()
            first[2].result(timeout=5)
            with entered:
                assert entered.wait_for(lambda: len(active) == 5, timeout=5)
            assert runtime.active_tasks == 2
        finally:
            for event in release:
                event.set()
        for job in first + [next_job]:
            job.result()


@pytest.mark.skipif(os.name != "nt", reason="Windows priority classes")
def test_priority_updates_a_running_windows_process():
    runtime = GenerationRuntime(ap.PackSettings(generation_priority="normal"))
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                               creationflags=subprocess.CREATE_NO_WINDOW)
    kernel = ctypes.windll.kernel32
    kernel.GetPriorityClass.argtypes = [ctypes.c_void_p]
    kernel.GetPriorityClass.restype = ctypes.c_ulong
    try:
        runtime.track(process)
        for value, expected in (("low", subprocess.IDLE_PRIORITY_CLASS),
                                ("high", subprocess.HIGH_PRIORITY_CLASS),
                                ("normal", subprocess.NORMAL_PRIORITY_CLASS)):
            runtime.set_priority(value)
            assert kernel.GetPriorityClass(int(process._handle)) == expected
    finally:
        runtime.untrack(process)
        process.kill()
        process.wait(timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Windows thread priorities")
def test_priority_updates_running_thread_and_restores_its_original_level():
    runtime = GenerationRuntime(ap.PackSettings(generation_priority="high"))
    entered, read = threading.Event(), threading.Event()
    readings = []

    def worker():
        original = current_thread_level()
        with runtime.worker():
            readings.append(current_thread_level())
            entered.set()
            assert read.wait(5)
            readings.append(current_thread_level())
        readings.extend([current_thread_level(), original])

    thread = threading.Thread(target=worker)
    thread.start()
    try:
        assert entered.wait(5)
        runtime.set_priority("low")
    finally:
        read.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert readings[:2] == [1, -15]
    assert readings[2] == readings[3]
