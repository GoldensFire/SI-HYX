# -*- coding: utf-8 -*-
"""Metadata network failures remain diagnosable and cancelled processes are reaped."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import workers
from si_hyx_parts.workers.download_network import network_hint
from si_hyx_parts.workers.download_process import stop_process


@pytest.fixture
def metadata(tmp_path, monkeypatch, qapp):
    worker = workers.InfoWorker("https://www.youtube.com/watch?v=one")
    monkeypatch.setattr(workers, "ytdlp_base_cmd", lambda: ["yt-dlp"])
    monkeypatch.setattr(workers, "get_cookies_path", lambda _: str(tmp_path / "absent"))
    monkeypatch.setattr(workers.time, "sleep", lambda _: None)
    success, errors = [], []
    worker.success.connect(lambda *args: success.append(args))
    worker.error.connect(errors.append)
    worker.successes, worker.errors = success, errors
    return worker


def process(*responses):
    return SimpleNamespace(communicate=Mock(side_effect=responses),
                           poll=lambda: None, kill=Mock(), pid=None)


def test_connection_reset_gets_one_new_attempt(metadata, monkeypatch):
    first = process(("", "ConnectionResetError(10054)"))
    second = process(("@@DT@@195\tNA\n@@SB@@{}\n@@FM@@[]", ""))
    popen = Mock(side_effect=[first, second])
    monkeypatch.setattr(workers.subprocess, "Popen", popen)
    metadata.run()
    assert metadata.successes[0][0] == 195
    assert not metadata.errors
    assert popen.call_count == 2


def test_repeated_reset_preserves_the_cause_and_zapret_hint(metadata, monkeypatch):
    popen = Mock(side_effect=[process(("", "ConnectionResetError(10054)")) for _ in range(2)])
    monkeypatch.setattr(workers.subprocess, "Popen", popen)
    metadata.run()
    assert not metadata.successes
    assert "10054" in metadata.errors[0]
    assert "zapret-discord-youtube" in metadata.errors[0]
    assert network_hint() in metadata.errors[0]


def test_timeout_kills_and_drains_process_before_retry(metadata, monkeypatch):
    timeout = workers.subprocess.TimeoutExpired("yt-dlp", 60)
    first = process(timeout, ("", "10054"))
    second = process(("@@DT@@195\tNA", ""))
    monkeypatch.setattr(workers.subprocess, "Popen", Mock(side_effect=[first, second]))
    metadata.run()
    first.kill.assert_called_once()
    assert first.communicate.call_count == 2
    assert metadata.successes[0][0] == 195


def test_cancel_terminates_the_owned_subprocess(metadata):
    metadata._proc = process(("", ""))
    metadata.cancel()
    assert metadata.cancelled
    metadata._proc.kill.assert_called_once()


def test_windows_stop_terminates_ffmpeg_children(monkeypatch):
    proc = SimpleNamespace(pid=1234, poll=Mock(side_effect=[None, 0]), kill=Mock())
    run = Mock()
    monkeypatch.setattr(workers, "IS_WIN", True)
    monkeypatch.setattr(workers.subprocess, "run", run)
    stop_process(proc)
    assert run.call_args.args[0] == ["taskkill", "/PID", "1234", "/T", "/F"]
    assert run.call_args.kwargs['creationflags'] == workers.CREATE_NO_WINDOW
    proc.kill.assert_not_called()
