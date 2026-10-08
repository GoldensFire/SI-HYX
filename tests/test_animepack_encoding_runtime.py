# -*- coding: utf-8 -*-
"""Отдельные слоты AV1, повторный вход AVIF и общий запуск процессов."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from types import SimpleNamespace

import animepack as ap
import avif_fit
from si_hyx_parts.animepack.generation_runtime import GenerationRuntime
from test_animepack_mixed_streams import _generator


def test_encoding_has_separate_limit_and_does_not_hold_network_workers(monkeypatch):
    from si_hyx_parts.animepack import generation_runtime as module
    monkeypatch.setattr(module.os, "cpu_count", lambda: 8)
    runtime = GenerationRuntime(ap.PackSettings(parallel=8, generation_priority="high"))
    entered = threading.Condition()
    release = threading.Event()
    encoders = []

    def encode(number):
        with runtime.encoding():
            with entered:
                encoders.append(number)
                entered.notify_all()
            assert release.wait(5)

    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(encode, i) for i in range(3)]
        try:
            with entered:
                assert entered.wait_for(lambda: len(encoders) == 2, timeout=5)
            assert pool.submit(lambda: "network available").result(timeout=5)
            assert runtime.active_encoders == 2
            assert len(encoders) == 2
        finally:
            release.set()
        for job in jobs:
            job.result()


def test_nested_avif_runner_uses_one_encoding_slot():
    runtime = GenerationRuntime(ap.PackSettings(generation_priority="low"))
    with runtime.encoding():
        with runtime.encoding():
            assert runtime.active_encoders == 1
    assert runtime.active_encoders == 0


def test_encoder_queue_is_included_in_process_timeout():
    from si_hyx_parts.animepack.generation_runtime import encoding_operation
    runtime = GenerationRuntime(ap.PackSettings(generation_priority="low"))
    executed = []
    @encoding_operation
    def _run_capture(generator, cmd, timeout=180):
        executed.append(True)
        return 0, "", ""
    gen = SimpleNamespace(_runtime=runtime)
    with runtime.encoding(), ThreadPoolExecutor(max_workers=1) as pool:
        code, _, error = pool.submit(_run_capture, gen, ["libsvtav1"], 0.05).result(timeout=2)
    assert code == 1 and "кодировщика" in error and not executed
    assert runtime.active_encoders == 0


def test_remaining_process_budget_shrinks_after_encoder_wait():
    from si_hyx_parts.animepack.generation_runtime import encoding_operation
    runtime = GenerationRuntime(ap.PackSettings(generation_priority="low"))
    @encoding_operation
    def _run_capture(generator, cmd, timeout=180):
        return timeout
    gen = SimpleNamespace(_runtime=runtime)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with runtime.encoding():
            future = pool.submit(_run_capture, gen, ["libsvtav1"], 1)
            time.sleep(0.05)
        assert 0 < future.result(timeout=2) < 0.98


def test_cancellation_wakes_a_waiting_encoder():
    stopped = threading.Event()
    runtime = GenerationRuntime(ap.PackSettings(generation_priority="low"),
                                stopped.is_set)
    waiting = threading.Event()

    def encode():
        waiting.set()
        try:
            with runtime.encoding():
                return "started"
        except RuntimeError:
            return "cancelled"

    with ThreadPoolExecutor(max_workers=1) as pool:
        with runtime.encoding():
            future = pool.submit(encode)
            assert waiting.wait(5)
            stopped.set()
            assert future.result(timeout=5) == "cancelled"
    assert runtime.active_encoders == 0


def test_avif_uses_generator_runner_and_retains_encoding_settings(tmp_path, monkeypatch):
    gen = _generator(tmp_path, monkeypatch, [], [], generation_priority="high")
    gen.folder = str(tmp_path)
    (tmp_path / "Images").mkdir()
    commands, settings = [], []
    command = [ap.FFMPEG, "-c:v", "libaom-av1", "output.avif"]

    def fit(_source, _out, _limit, **kwargs):
        settings.append(kwargs)
        assert gen._runtime.active_encoders == 1
        return kwargs["runner"](command)

    monkeypatch.setattr(ap, "fit_to_limit", fit)
    monkeypatch.setattr(gen, "_run_capture", lambda cmd, timeout: (
        commands.append((cmd, timeout)) or (0, "", "")))
    assert gen._to_avif(b"image bytes", "answer.avif")
    assert commands == [(command, 600)]
    assert settings[0]["speed"] == gen.s.image_speed
    assert settings[0]["passes"] == ap.IMAGE_FIT_PASSES
    assert settings[0]["max_side"] == ap.IMAGE_MAX_SIDE
    assert gen._runtime.active_encoders == 0


def test_avif_fallback_also_uses_supplied_runner(monkeypatch):
    monkeypatch.setattr(avif_fit, "_allintra_ok", None)
    commands = []

    def runner(command):
        commands.append(command)
        return "allintra" not in command

    def independent_runner(*_args):
        raise AssertionError("Обход приоритета генератора")

    monkeypatch.setattr(avif_fit, "_run_once", independent_runner)
    assert avif_fit._run(["ffmpeg", "-usage", "allintra", "result.avif"], runner=runner)
    assert commands == [["ffmpeg", "-usage", "allintra", "result.avif"],
                        ["ffmpeg", "result.avif"]]


def test_priority_does_not_change_video_presets_or_crf(tmp_path, monkeypatch):
    gen = _generator(tmp_path, monkeypatch, [], [])
    expected = gen.video_encode_args(), gen.pixel_encode_args("setsar=1")
    for priority in ("low", "high", "normal"):
        gen._runtime.set_priority(priority)
        assert (gen.video_encode_args(), gen.pixel_encode_args("setsar=1")) == expected
