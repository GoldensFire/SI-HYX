"""Real-output validation and recovery from HTTP readers with incomplete output."""
from contextlib import contextmanager
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

import animepack as ap
from test_animepack_manga_sakuga import generator  # noqa: F401
from si_hyx_parts.animepack import theme_stream as stream, theme_video as video
from si_hyx_parts.animepack.theme_http import Stopped


HTTP_HELP = """+-initial_request_size -request_size -short_seek_size -multiple_requests
-reconnect -reconnect_on_network_error -reconnect_on_http_error
-reconnect_streamed -reconnect_delay_max -reconnect_max_retries
-reconnect_delay_total_max -respect_retry_after
"""


def metadata(seconds=15, *, audio=15, visual=15):
    return {"format": {"duration": str(seconds)}, "streams": [
        {"codec_type": "video", "duration": str(visual)},
        {"codec_type": "audio", "duration": str(audio)}]}


@pytest.mark.parametrize("data,good", [
    (metadata(), True), (metadata(14.95, visual=14.95), True),
    (metadata(4, audio=4, visual=4), False), (metadata(35), False),
    (metadata(float("nan")), False), (metadata(float("inf")), False),
    (metadata(0), False), (metadata(audio=5), False),
    (metadata(visual=2), False), (metadata(visual=float("nan")), False),
    ({"format": {"duration": "15"}, "streams": [{"codec_type": "video"}]}, False),
])
def test_output_requires_full_audio_and_video(data, good):
    generator = SimpleNamespace(_run_capture=lambda *a, **kw: (0, json.dumps(data), ""))
    assert video.complete_output(generator, Path("video.mp4"), 15)[0] is good


def test_invalid_metadata_is_not_success():
    generator = SimpleNamespace(_run_capture=lambda *a, **kw: (0, "not JSON", ""))
    assert not video.complete_output(generator, Path("video.mp4"), 15)[0]


def test_full_duration_does_not_hide_decode_failure():
    results = iter([(0, json.dumps(metadata()), ""), (1, "", "corrupt packet")])
    generator = SimpleNamespace(_run_capture=lambda *a, **kw: next(results))
    good, reason = video.complete_output(generator, Path("video.mp4"), 15)
    assert not good and "corrupt packet" in reason


def test_http_capability_help_does_not_list_generic_rw_timeout():
    calls = []
    generator = SimpleNamespace(_run_capture=lambda *a, **kw:
                                calls.append(a) or (0, HTTP_HELP, ""))
    args = stream.input_args(generator, "ffmpeg")
    assert args and "-rw_timeout" in args
    assert args[args.index("-request_size") + 1] == str(4 * 1024 * 1024)
    assert stream.input_args(generator, "ffmpeg") == args
    assert len(calls) == 1


def test_old_ffmpeg_uses_full_transfer_without_unknown_options():
    generator = SimpleNamespace(_run_capture=lambda *a, **kw: (0, "-reconnect", ""))
    good, reason = stream.remote_encode(generator, None, "https://v/file.webm", None, None)
    assert not good and "не поддерживает" in reason


class Gate:
    def __init__(self):
        self.cooldowns = []
        self.active = False

    @contextmanager
    def slot(self, stopped):
        assert not self.active
        self.active = True
        try:
            yield
        finally:
            self.active = False

    def defer(self, seconds):
        self.cooldowns.append(seconds)


@pytest.fixture
def remote_generator(monkeypatch):
    gate = Gate()
    monkeypatch.setattr(stream, "GATE", gate)
    monkeypatch.setattr(stream, "input_args", lambda *a: ["-request_size", "4194304"])
    generator = SimpleNamespace(
        _video_len_lock=threading.Lock(), _video_len={}, stopped=lambda: False,
        s=SimpleNamespace(video_cut=15), _video_start=lambda *a: 20,
        video_encode_args=lambda: [], opus_args=lambda *a: [])
    generator._run_capture = lambda *a, **kw: (0, "90", "")
    return generator, gate


def test_zero_exit_with_premature_stream_is_discarded(remote_generator, tmp_path):
    generator, gate = remote_generator
    target = tmp_path / "clip.mp4"

    def run(command, **kw):
        assert gate.active
        target.write_bytes(b"x" * (ap.MIN_VIDEO_BYTES + 1))
        return 0, "File ended prematurely"
    generator._run_killable = run
    good, reason = stream.remote_encode(generator, None, "https://v/file.webm", target,
                                        lambda *a: pytest.fail("must not validate partial"))
    assert not good and "оборвался" in reason
    assert not target.exists() and gate.cooldowns == [8]


def test_validated_remote_success_needs_no_complete_transfer(remote_generator, tmp_path):
    generator, gate = remote_generator
    target = tmp_path / "clip.mp4"

    def run(command, **kw):
        assert gate.active and "-request_size" in command
        assert command[command.index("-ss") + 1] == "20"
        target.write_bytes(b"x" * (ap.MIN_VIDEO_BYTES + 1))
        return 0, ""
    generator._run_killable = run
    expected = []
    good, reason = stream.remote_encode(generator, None, "https://v/file.webm", target,
                                        lambda *a: expected.append(a[-1]) or (True, ""))
    assert good and not reason and target.exists()
    assert expected == [15]


def test_stop_after_ffmpeg_cleans_partial_in_outer_handler(generator, monkeypatch):
    candidate = ap.SongCandidate({}, {"malId": 1})
    target = Path(generator.folder) / "Video" / candidate.video_out
    monkeypatch.setattr(generator, "_theme_video", lambda *a: "https://v/file.webm")

    def cancelled(*a):
        target.write_bytes(b"partial")
        raise Stopped("stop")
    monkeypatch.setattr(video, "remote_encode", cancelled)
    assert not generator.download_video(candidate)
    assert not target.exists() and not candidate.has_video
