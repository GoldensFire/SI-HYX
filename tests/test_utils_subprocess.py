# -*- coding: utf-8 -*-
"""Тесты функций utils.py, зависящих от subprocess/ОС — всё замокано."""
import json
import os
import subprocess
import types

import pytest

import utils


class _Proc:
    """Заглушка результата subprocess.run."""
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


# ── check_ffmpeg ─────────────────────────────────────────────────────────────
class TestCheckFfmpeg:
    def test_ok(self, monkeypatch):
        monkeypatch.setattr(utils.subprocess, "run", lambda *a, **k: _Proc())
        assert utils.check_ffmpeg() is True

    def test_missing(self, monkeypatch):
        def boom(*a, **k):
            raise FileNotFoundError("ffmpeg")
        monkeypatch.setattr(utils.subprocess, "run", boom)
        assert utils.check_ffmpeg() is False


# ── get_media_info ───────────────────────────────────────────────────────────
class TestGetMediaInfo:
    def _patch_run(self, monkeypatch, ffprobe_json, packets=""):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if "packet=size" in " ".join(map(str, cmd)):
                return _Proc(stdout=packets)
            return _Proc(stdout=ffprobe_json)
        monkeypatch.setattr(utils.subprocess, "run", fake_run)
        return calls

    def test_full_info(self, monkeypatch, tmp_path):
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x" * 1000)
        data = {"format": {"duration": "12.5", "bit_rate": "192000"},
                "streams": [{"codec_name": "mp3", "bit_rate": "192000"}]}
        self._patch_run(monkeypatch, json.dumps(data))
        dur, br, size, a_br, a_codec = utils.get_media_info(str(f))
        assert dur == 12.5
        assert br == "192 кбит/с"
        assert size == 1000
        assert a_br == "192 кбит/с"
        assert a_codec == "mp3"

    def test_pcm_computed_bitrate(self, monkeypatch, tmp_path):
        f = tmp_path / "a.wav"
        f.write_bytes(b"x" * 10)
        data = {"format": {"duration": "1.0"},
                "streams": [{"codec_name": "pcm_s16le", "sample_rate": "48000",
                             "channels": "2", "bits_per_sample": "16"}]}
        self._patch_run(monkeypatch, json.dumps(data))
        dur, br, size, a_br, a_codec = utils.get_media_info(str(f))
        assert a_br == f"{48000 * 2 * 16 // 1000} кбит/с"
        assert a_codec == "pcm_s16le"

    def test_bitrate_from_packets(self, monkeypatch, tmp_path):
        f = tmp_path / "a.opus"
        f.write_bytes(b"x")
        data = {"format": {"duration": "2.0"},
                "streams": [{"codec_name": "opus"}]}
        # 2 сек, 4000 байт пакетов → 4000*8/2/1000 = 16 кбит/с
        self._patch_run(monkeypatch, json.dumps(data), packets="2000\n2000\n")
        _, br, _, a_br, _ = utils.get_media_info(str(f))
        assert a_br == "16 кбит/с"

    def test_fallback_format_bitrate(self, monkeypatch, tmp_path):
        f = tmp_path / "a.m4a"
        f.write_bytes(b"x")
        data = {"format": {"duration": "0", "bit_rate": "96000"},
                "streams": [{"codec_name": "aac"}]}
        self._patch_run(monkeypatch, json.dumps(data))
        _, br, _, a_br, _ = utils.get_media_info(str(f))
        assert a_br == "96 кбит/с"

    def test_estimate_from_size(self, monkeypatch, tmp_path):
        f = tmp_path / "a.bin"
        f.write_bytes(b"x" * 4000)
        data = {"format": {"duration": "2.0"}, "streams": []}
        self._patch_run(monkeypatch, json.dumps(data))
        dur, br, size, a_br, _ = utils.get_media_info(str(f))
        # 4000 байт за 2 сек = 16000 бит/с = 16 кбит/с
        assert br == "16 кбит/с"
        assert a_br == "16 кбит/с"

    def test_missing_file(self, monkeypatch):
        self._patch_run(monkeypatch, "{}")
        dur, br, size, a_br, a_codec = utils.get_media_info("нет_такого.mp4")
        assert (dur, br, size, a_br, a_codec) == (0.0, "-", 0, "-", None)

    def test_broken_json(self, monkeypatch, tmp_path):
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x")
        self._patch_run(monkeypatch, "мусор не json")
        dur, br, size, a_br, a_codec = utils.get_media_info(str(f))
        assert dur == 0.0 and a_codec is None

    def test_ffprobe_crash(self, monkeypatch, tmp_path):
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x" * 8)

        def boom(*a, **k):
            raise OSError("no ffprobe")
        monkeypatch.setattr(utils.subprocess, "run", boom)
        dur, br, size, a_br, a_codec = utils.get_media_info(str(f))
        assert size == 8 and dur == 0.0


# ── get_fps_float / get_video_codec ──────────────────────────────────────────
class TestFpsCodec:
    def test_fps_fraction(self, monkeypatch):
        monkeypatch.setattr(utils.subprocess, "run",
                            lambda *a, **k: _Proc(stdout="30000/1001\n"))
        assert utils.get_fps_float("v.mp4") == pytest.approx(29.97, abs=0.01)

    def test_fps_plain(self, monkeypatch):
        monkeypatch.setattr(utils.subprocess, "run",
                            lambda *a, **k: _Proc(stdout="25\n"))
        assert utils.get_fps_float("v.mp4") == 25.0

    def test_fps_zero_denominator(self, monkeypatch):
        monkeypatch.setattr(utils.subprocess, "run",
                            lambda *a, **k: _Proc(stdout="0/0"))
        assert utils.get_fps_float("v.mp4") == 0.0

    def test_fps_error(self, monkeypatch):
        def boom(*a, **k):
            raise OSError()
        monkeypatch.setattr(utils.subprocess, "run", boom)
        assert utils.get_fps_float("v.mp4") == 0.0

    def test_codec(self, monkeypatch):
        monkeypatch.setattr(utils.subprocess, "run",
                            lambda *a, **k: _Proc(stdout="H264\n"))
        assert utils.get_video_codec("v.mp4") == "h264"

    def test_codec_empty(self, monkeypatch):
        monkeypatch.setattr(utils.subprocess, "run",
                            lambda *a, **k: _Proc(stdout="\n"))
        assert utils.get_video_codec("v.mp4") is None

    def test_codec_label_combined(self, monkeypatch):
        monkeypatch.setattr(utils.subprocess, "run",
                            lambda *a, **k: _Proc(stdout="av1\n"))
        assert utils.get_video_codec_label("v.mp4") == "AV1"

    def test_codec_label_none(self, monkeypatch):
        def boom(*a, **k):
            raise OSError()
        monkeypatch.setattr(utils.subprocess, "run", boom)
        assert utils.get_video_codec_label("v.mp4") is None


# ── measure_loudness ─────────────────────────────────────────────────────────
class _FakePopen:
    def __init__(self, stderr_text, hang_iterations=0):
        self._stderr = stderr_text
        self._hangs = hang_iterations
        self.killed = False

    def communicate(self, timeout=None):
        if self._hangs > 0 and timeout is not None:
            self._hangs -= 1
            raise subprocess.TimeoutExpired("ffmpeg", timeout)
        return ("", self._stderr)

    def kill(self):
        self.killed = True


LOUDNORM_STDERR = """
[Parsed_loudnorm_0 @ 0x1]
{
\t"input_i" : "-23.40",
\t"input_tp" : "-5.0"
}
"""


class TestMeasureLoudness:
    def test_basic(self, monkeypatch):
        monkeypatch.setattr(utils.subprocess, "Popen",
                            lambda *a, **k: _FakePopen(LOUDNORM_STDERR))
        assert utils.measure_loudness("f.mp3") == pytest.approx(-23.4)

    def test_no_json_in_output(self, monkeypatch):
        monkeypatch.setattr(utils.subprocess, "Popen",
                            lambda *a, **k: _FakePopen("нет данных"))
        assert utils.measure_loudness("f.mp3") is None

    def test_should_stop_kills_process(self, monkeypatch):
        proc = _FakePopen(LOUDNORM_STDERR, hang_iterations=100)
        monkeypatch.setattr(utils.subprocess, "Popen", lambda *a, **k: proc)
        assert utils.measure_loudness("f.mp3", should_stop=lambda: True) is None
        assert proc.killed

    def test_should_stop_false_completes(self, monkeypatch):
        proc = _FakePopen(LOUDNORM_STDERR, hang_iterations=2)
        monkeypatch.setattr(utils.subprocess, "Popen", lambda *a, **k: proc)
        assert utils.measure_loudness("f.mp3",
                                      should_stop=lambda: False) == pytest.approx(-23.4)

    def test_start_dur_in_cmd(self, monkeypatch):
        captured = {}

        def fake_popen(cmd, **kw):
            captured["cmd"] = cmd
            return _FakePopen(LOUDNORM_STDERR)
        monkeypatch.setattr(utils.subprocess, "Popen", fake_popen)
        utils.measure_loudness("f.mp3", start=5.0, dur=2.5)
        cmd = captured["cmd"]
        assert "-ss" in cmd and "5.000" in cmd
        assert "-t" in cmd and "2.500" in cmd

    def test_popen_crash_returns_none(self, monkeypatch):
        def boom(*a, **k):
            raise OSError()
        monkeypatch.setattr(utils.subprocess, "Popen", boom)
        assert utils.measure_loudness("f.mp3") is None


# ── detect_ffmpeg_encoders / require_svt ─────────────────────────────────────
ENCODERS_OUT = """Encoders:
 V....D libx264              H.264 / MPEG-4 AVC
 V....D libsvtav1            SVT-AV1
 A....D aac                  AAC (Advanced Audio Coding)
"""


class TestDetectEncoders:
    def setup_method(self):
        utils.detect_ffmpeg_encoders.cache_clear()

    def teardown_method(self):
        utils.detect_ffmpeg_encoders.cache_clear()

    def test_parses_encoders(self, monkeypatch):
        monkeypatch.setattr(utils.subprocess, "run",
                            lambda *a, **k: _Proc(stdout=ENCODERS_OUT))
        encs = utils.detect_ffmpeg_encoders()
        assert {"libx264", "libsvtav1", "aac"} <= encs

    def test_cached_single_call(self, monkeypatch):
        calls = []

        def fake_run(*a, **k):
            calls.append(1)
            return _Proc(stdout=ENCODERS_OUT)
        monkeypatch.setattr(utils.subprocess, "run", fake_run)
        utils.detect_ffmpeg_encoders()
        utils.detect_ffmpeg_encoders()
        assert len(calls) == 1

    def test_error_returns_empty(self, monkeypatch):
        def boom(*a, **k):
            raise OSError()
        monkeypatch.setattr(utils.subprocess, "run", boom)
        assert utils.detect_ffmpeg_encoders() == frozenset()

    def test_require_svt(self, monkeypatch):
        monkeypatch.setattr(utils.subprocess, "run",
                            lambda *a, **k: _Proc(stdout=ENCODERS_OUT))
        assert utils.require_svt() is True

    def test_require_svt_missing(self, monkeypatch):
        monkeypatch.setattr(utils.subprocess, "run",
                            lambda *a, **k: _Proc(stdout="Encoders:\n V..... libx264 x\n"))
        assert utils.require_svt() is False


# ── ensure_deno_on_path ──────────────────────────────────────────────────────
class TestEnsureDeno:
    def test_found_in_bin(self, monkeypatch, tmp_path):
        exe = "deno.exe" if utils.IS_WIN else "deno"
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / exe).write_bytes(b"MZ")
        monkeypatch.setattr(utils.sys, "argv", [str(tmp_path / "app.exe")])
        old_path = os.environ.get("PATH", "")
        try:
            assert utils.ensure_deno_on_path() is True
            assert str(bin_dir) in os.environ["PATH"]
        finally:
            os.environ["PATH"] = old_path

    def test_found_in_system_path(self, monkeypatch, tmp_path):
        monkeypatch.setattr(utils.sys, "argv", [str(tmp_path / "app.exe")])
        monkeypatch.setattr(utils.shutil, "which",
                            lambda name: "C:\\tools\\deno.exe" if name == "deno" else None)
        monkeypatch.setattr(utils.os, "getenv",
                            lambda k, d=None: None if k == "LOCALAPPDATA" else os.getenv(k, d))
        assert utils.ensure_deno_on_path() is True

    def test_not_found(self, monkeypatch, tmp_path):
        monkeypatch.setattr(utils.sys, "argv", [str(tmp_path / "app.exe")])
        monkeypatch.setattr(utils.shutil, "which", lambda name: None)
        monkeypatch.setattr(utils.os, "getenv", lambda k, d=None: None)
        monkeypatch.setattr(utils.os.path, "expanduser", lambda p: str(tmp_path))
        # __file__-папка проекта может содержать bin/deno.exe — прячем и её
        real_isfile = os.path.isfile
        monkeypatch.setattr(
            utils.os.path, "isfile",
            lambda p: False if p.lower().endswith(("deno.exe", "deno")) else real_isfile(p))
        assert utils.ensure_deno_on_path() is False


# ── move_to_trash (безопасные ветки) ─────────────────────────────────────────
class TestMoveToTrash:
    def test_nonexistent_returns_true(self, tmp_path):
        assert utils.move_to_trash(str(tmp_path / "нет.txt")) is True

    def test_abspath_failure_returns_false(self, monkeypatch):
        def boom(p):
            raise ValueError("bad path")
        monkeypatch.setattr(utils.os.path, "abspath", boom)
        assert utils.move_to_trash("что-то") is False

    @pytest.mark.skipif(os.name == "nt", reason="ветка не-Windows")
    def test_posix_removes(self, tmp_path):
        f = tmp_path / "f.txt"
        f.write_text("x")
        assert utils.move_to_trash(str(f)) is True
        assert not f.exists()


# ── download_cdn_direct ──────────────────────────────────────────────────────
class _FakeHttpResp:
    def __init__(self, data, with_length=True):
        self._data = data
        self._pos = 0
        self.headers = {"Content-Length": str(len(data))} if with_length else {}

    def read(self, n):
        chunk = self._data[self._pos:self._pos + n]
        self._pos += n
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


class TestDownloadCdnDirect:
    def test_downloads_file(self, monkeypatch, tmp_path):
        data = b"video-bytes" * 100
        monkeypatch.setattr(utils, "http_get",
                            lambda url, **kw: _FakeHttpResp(data))
        logs = []
        out = utils.download_cdn_direct(
            "https://v.fbcdn.net/v/file.mp4?tok=1", str(tmp_path), log_fn=logs.append)
        assert os.path.basename(out) == "file.mp4"
        with open(out, "rb") as f:
            assert f.read() == data
        assert any("100%" in l for l in logs)

    def test_unsafe_chars_sanitized(self, monkeypatch, tmp_path):
        monkeypatch.setattr(utils, "http_get",
                            lambda url, **kw: _FakeHttpResp(b"x"))
        out = utils.download_cdn_direct(
            "https://v.fbcdn.net/dir/we%20ird$name!.mp4", str(tmp_path))
        name = os.path.basename(out)
        assert " " not in name and "$" not in name and "!" not in name
        assert name.endswith(".mp4")

    def test_no_extension_gets_mp4(self, monkeypatch, tmp_path):
        monkeypatch.setattr(utils, "http_get",
                            lambda url, **kw: _FakeHttpResp(b"x"))
        out = utils.download_cdn_direct("https://v.fbcdn.net/stream", str(tmp_path))
        assert out.endswith(".mp4")

    def test_collision_gets_suffix(self, monkeypatch, tmp_path):
        monkeypatch.setattr(utils, "http_get",
                            lambda url, **kw: _FakeHttpResp(b"x"))
        (tmp_path / "file.mp4").write_bytes(b"old")
        out = utils.download_cdn_direct("https://v.fbcdn.net/file.mp4", str(tmp_path))
        assert os.path.basename(out) != "file.mp4"
        assert (tmp_path / "file.mp4").read_bytes() == b"old"

    def test_http_error_propagates(self, monkeypatch, tmp_path):
        def boom(url, **kw):
            raise OSError("сеть недоступна")
        monkeypatch.setattr(utils, "http_get", boom)
        with pytest.raises(OSError):
            utils.download_cdn_direct("https://v.fbcdn.net/f.mp4", str(tmp_path))


# ── play_done_sound ──────────────────────────────────────────────────────────
class TestPlayDoneSound:
    def test_does_not_raise(self, monkeypatch, capsys):
        # не пищим настоящим динамиком: уводим в ветку print('\a')
        monkeypatch.setattr(utils, "IS_WIN", False)
        utils.play_done_sound()  # просто не должно бросить
