"""Deadlines include queue time and both acoustic stages, without real models."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from karaoke import budget, fallback, recognition
from karaoke.lyrics import Sheet
from animepack import PackSettings


def test_attempt_shares_remaining_time_across_processes(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(budget.time, "monotonic", lambda: now[0])
    limits = []
    def runner(command, timeout, *, stopped):
        limits.append(timeout)
        now[0] += 20
        return 0, ""
    with pytest.raises(TimeoutError, match="общий лимит"):
        with budget.attempt(lambda: False, 30) as stopped:
            budget.run("separate", runner, [], 1800, stopped=stopped)
            budget.run("ASR", runner, [], 1800, stopped=stopped)
    assert limits == [30, 10]
    assert budget._current.get() is None


def test_user_stop_is_preserved_instead_of_timeout():
    stopped = [False]
    with pytest.raises(RuntimeError, match="остановлено"):
        with budget.attempt(lambda: stopped[0], 30) as token:
            stopped[0] = True
            token.check()


@pytest.mark.parametrize("values, expected", [
    ({}, (300, "auto")),
    ({"karaoke_ai_timeout": 600, "karaoke_separator": "kim"}, (600, "kim")),
    ({"karaoke_ai_timeout": 0, "karaoke_separator": "unknown"}, (60, "auto")),
    ({"karaoke_ai_timeout": 9999}, (3600, "auto")),
])
def test_budget_settings_migrate_safely(values, expected):
    settings = PackSettings.from_dict(values)
    assert (settings.karaoke_ai_timeout, settings.karaoke_separator) == expected


def test_queue_expiry_never_starts_models(tmp_path, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(budget.time, "monotonic", lambda: now[0])
    @contextmanager
    def queue(stopped):
        now[0] = 31
        assert stopped()
        raise RuntimeError("cancelled while waiting")
        yield
    monkeypatch.setattr(fallback, "model_slot", queue)
    def unexpected(*args):
        raise AssertionError("Expired queue must not load models")
    monkeypatch.setattr(fallback, "ensure_runtime", unexpected)
    source = tmp_path / "audio"
    source.write_bytes(b"recording")
    sheet = Sheet("Song", "Artist", "site", ["kimi wa"], [])
    with pytest.raises(TimeoutError):
        fallback.align(source, sheet, SimpleNamespace(karaoke_ai_timeout=300, karaoke_ai_queue_timeout=30),
                       stopped=lambda: False, log=lambda _: None, cache=tmp_path / "cache")
    assert not list((tmp_path / "cache").glob("*.ttml"))


@pytest.mark.parametrize("preferred", ["cpu", "directml"])
def test_auto_separator_avoids_cpu_kim_after_gpu_failure(tmp_path, monkeypatch, preferred):
    calls, logs = [], []
    monkeypatch.setattr(recognition, "kim_disabled", lambda: False)
    monkeypatch.setattr(recognition, "_FAILED_SEPARATORS", set())
    monkeypatch.setattr(recognition, "ensure_separator", lambda *a, **k: None)
    monkeypatch.setattr(recognition, "ensure_packages", lambda *a, **k: None)
    def runner(command, timeout, **kwargs):
        backend = command[command.index("--backend") + 1]
        calls.append((backend, command[command.index("--device") + 1]))
        if backend == "kim-onnx":
            return 1, "ONNX Runtime: 8007000E"
        Path(command[command.index("separate") + 2]).write_bytes(b"vocals")
        return 0, ""
    monkeypatch.setattr(recognition, "run_process", runner)
    info = {"separator": preferred, "separator_policy": "auto", "demucs": "cpu"}
    result, backend = recognition.vocal_source("python", tmp_path / "source", "sha", tmp_path,
        info, stopped=lambda: False, log=logs.append)
    assert result.is_file() and backend == "htdemucs"
    assert calls == ([] if preferred == "cpu" else [("kim-onnx", "directml")]) + [("htdemucs", "cpu")]
    assert not any("повторяю Kim ONNX на CPU" in row for row in logs)
