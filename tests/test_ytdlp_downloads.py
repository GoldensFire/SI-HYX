# -*- coding: utf-8 -*-
"""Downloader regressions: truncated sound, hidden demux failures and retries."""
import io
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import workers
from si_hyx_parts.workers.download_validation import (
    DownloadValidationError, expected_duration, track_duration, validate_streams,
)


def media_info(video=195, audio=195, *, include_audio=True):
    streams = [{"codec_type": "video", "duration": str(video)}]
    if include_audio:
        streams.append({"codec_type": "audio", "duration": str(audio)})
    return {"streams": streams, "format": {"duration": str(video)}}


@pytest.fixture
def download(tmp_path, monkeypatch, qapp):
    worker = workers.YtdlpWorker({
        "iid": "job", "url": "https://www.youtube.com/watch?v=example",
        "outdir": str(tmp_path), "source_duration": 195,
    })
    worker._sleep_interruptible = Mock()
    monkeypatch.setattr(workers, "ytdlp_base_cmd", lambda: ["yt-dlp"])
    monkeypatch.setattr(workers, "get_cookies_path", lambda _: str(tmp_path / "no-cookies"))
    monkeypatch.setattr(workers, "deno_available", lambda: True)
    completed, errors = [], []
    worker.finished_sig.connect(lambda *args: completed.append(args))
    worker.error_sig.connect(lambda *args: errors.append(args))
    worker.completed, worker.errors = completed, errors
    probe = Mock(return_value=SimpleNamespace(
        returncode=0, stdout=json.dumps(media_info()), stderr=""))
    monkeypatch.setattr(workers.subprocess, "run", probe)
    worker.probe = probe
    worker.path = tmp_path / "video.mp4"
    return worker


def attempts(worker, results):
    def execute(*_):
        rc, tail = next(results)
        worker._download_failure = ""
        if rc == 0:
            worker.path.write_bytes(b"downloaded media")
        return rc, str(worker.path), "1920x1080", tail
    worker._exec_ytdlp = Mock(side_effect=execute)


def test_complete_container_with_short_audio_is_rejected():
    with pytest.raises(DownloadValidationError, match="Звук скачан не полностью"):
        validate_streams(media_info(audio=90), duration=195)


def test_duration_is_checked_without_source_metadata():
    with pytest.raises(DownloadValidationError):
        validate_streams(media_info(audio=90))


def test_missing_expected_audio_is_rejected():
    with pytest.raises(DownloadValidationError, match="аудиодорожку"):
        validate_streams(media_info(include_audio=False), expect_audio=True)


def test_silent_source_and_small_muxing_difference_are_allowed():
    validate_streams(media_info(include_audio=False), expect_audio=False, duration=195)
    validate_streams(media_info(audio=194.7), expect_audio=True, duration=195)


def test_attached_cover_does_not_count_as_video():
    info = media_info()
    info["streams"][0]["disposition"] = {"attached_pic": 1}
    with pytest.raises(DownloadValidationError, match="видеодорожку"):
        validate_streams(info)
    validate_streams(info, audio_only=True, duration=195)


def test_webm_tags_and_rational_duration():
    assert track_duration({"tags": {"DURATION": "00:03:14.720000000"}}) == 194.72
    assert track_duration({"duration_ts": 195000, "time_base": "1/1000"}) == 195
    assert expected_duration(194.72, 30, 195) == pytest.approx(164.72)
    assert expected_duration(195, 30, None) == 165


def test_false_success_after_demux_error_retries_and_preserves_data(download):
    attempts(download, iter([
        (0, ["[in#1/matroska,webm] Error during demuxing: Error number -10054 occurred"]),
        (0, []),
    ]))
    download.run()
    assert len(download.completed) == 1
    assert not download.errors
    assert download._exec_ytdlp.call_count == 2
    assert download.path.with_name("video.mp4.incomplete").read_bytes() == b"downloaded media"


def test_short_audio_retries_without_trusting_overall_duration(download):
    download.probe.side_effect = [SimpleNamespace(
        returncode=0, stdout=json.dumps(media_info(audio=90)), stderr=""),
        download.probe.return_value]
    attempts(download, iter([(0, []), (0, [])]))
    download.run()
    assert len(download.completed) == 1
    assert download._exec_ytdlp.call_count == 2


def test_repeated_truncation_is_an_error_not_done(download):
    download.probe.return_value.stdout = json.dumps(media_info(audio=90))
    attempts(download, iter([(0, [])] * 3))
    download.run()
    assert not download.completed
    assert "Звук скачан не полностью" in download.errors[0][1]
    assert download._exec_ytdlp.call_count == 3
    assert not download.path.exists()
    assert len(list(download.path.parent.glob("*.incomplete*"))) == 3


def test_nonzero_exit_cannot_be_hidden_by_an_existing_file(download):
    download.path.write_bytes(b"previous file")
    attempts(download, iter([(1, ["ERROR: Unsupported URL"])]))
    download.run()
    assert not download.completed
    assert download.errors
    assert download.path.read_bytes() == b"previous file"
    assert not download.probe.called


def test_network_extraction_failure_is_retried(download):
    attempts(download, iter([(1, ["ConnectionResetError(10054)"]), (0, [])]))
    download.run()
    assert len(download.completed) == 1
    assert download._exec_ytdlp.call_count == 2


def test_missing_probe_never_reports_unverified_success(download):
    download.probe.side_effect = FileNotFoundError("ffprobe")
    attempts(download, iter([(0, [])]))
    download.run()
    assert not download.completed
    assert "ffprobe" in download.errors[0][1]
    assert download._exec_ytdlp.call_count == 1


@pytest.mark.parametrize("start,end,section", [(0, 195, False), (30, 60, True), (30, None, True)])
def test_full_range_uses_native_download_and_cuts_reconnect_both_inputs(download, start, end, section):
    download.c.update(start_s=start, end_s=end, overwrite=True)
    duration = expected_duration(195, start, end)
    download.probe.return_value.stdout = json.dumps(media_info(duration, duration))
    attempts(download, iter([(0, [])]))
    download.run()
    command = download._exec_ytdlp.call_args.args[0]
    assert ("--download-sections" in command) is section
    assert "--force-overwrites" in command
    if section:
        arguments = command[command.index("--downloader-args") + 1]
        assert arguments.startswith("ffmpeg_i:")
        assert "-reconnect 1" in arguments
        assert "-reconnect_on_network_error 1" in arguments
        assert "-reconnect_at_eof" not in arguments
        assert "ffmpeg_o:-xerror" in command


def test_demux_failure_survives_a_long_log_tail(download, monkeypatch):
    output = "\n".join([
        "@@CHECK@@195\tav1\topus",
        "[in#1/webm] Error during demuxing: I/O error",
        *(f"log line {i}" for i in range(60)),
        "Conversion failed!",
    ])
    proc = SimpleNamespace(stdout=io.StringIO(output), returncode=0,
                           wait=lambda: None, poll=lambda: 0)
    monkeypatch.setattr(workers.subprocess, "Popen", lambda *a, **kw: proc)
    result = download._exec_ytdlp(["yt-dlp"], "job", False)
    assert not any("demuxing" in line for line in result[3])
    assert "demuxing" in download._download_failure
    assert download._source_duration == 195
    assert download._expected_audio is True


def test_stopped_worker_does_not_start_another_process(download, monkeypatch):
    popen = Mock()
    monkeypatch.setattr(workers.subprocess, "Popen", popen)
    download.is_running = False
    download._exec_ytdlp(["yt-dlp"], "job", False)
    popen.assert_not_called()


def test_stop_during_validation_cannot_become_done(download):
    def probe(*args, **kwargs):
        download.is_running = False
        return SimpleNamespace(returncode=0, stdout=json.dumps(media_info()), stderr="")
    download.probe.side_effect = probe
    attempts(download, iter([(0, [])]))
    download.run()
    assert not download.completed
    assert download.errors[0][1] == "Остановлено"


def test_saved_network_cause_is_used_when_nonzero_exit_tail_is_generic(download):
    calls = []

    def execute(*args):
        calls.append(args)
        if len(calls) == 1:
            download._download_failure = "[in#1/webm] Error during demuxing: I/O error"
            return 1, "", "", ["Conversion failed!"]
        download._download_failure = ""
        download.path.write_bytes(b"complete file")
        return 0, str(download.path), "1920x1080", []

    download._exec_ytdlp = execute
    download.run()
    assert len(calls) == 2
    assert len(download.completed) == 1
    assert not download.errors
