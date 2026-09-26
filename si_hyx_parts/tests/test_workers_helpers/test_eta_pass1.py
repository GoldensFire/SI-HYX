# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""TestEtaPass1. Public namespace: test_workers_helpers."""
import test_workers_helpers as _api


# ── RealETACalculator ────────────────────────────────────────────────────────
class TestEtaPass1:
    def test_first_sample_none(self):
        eta = _api.RealETACalculator(total_frames=1000)
        assert eta.update(0, now=100.0) is None

    def test_steady_rate(self):
        eta = _api.RealETACalculator(total_frames=1000)
        eta.update(0, now=100.0)
        # 100 кадров за 10 сек → 10 fps → осталось 900 кадров → 90 сек
        assert eta.update(100, now=110.0) == _api.pytest.approx(90.0)

    def test_window_eviction(self):
        eta = _api.RealETACalculator(total_frames=10_000, window_sec=15.0)
        eta.update(0, now=0.0)      # старый медленный сэмпл
        eta.update(10, now=10.0)
        eta.update(1000, now=20.0)  # разгон
        # окно 15 сек: сэмпл t=0 вытеснен → скорость по (10..1000)/(10..20)=99 fps
        val = eta.update(2000, now=25.0)
        fps = (2000 - 10) / (25.0 - 10.0)
        assert val == _api.pytest.approx((10_000 - 2000) / fps)

    def test_second_pass_projection(self):
        eta = _api.RealETACalculator(total_frames=100, has_second_pass=True,
                                pass2_weight_coefficient=3.0)
        eta.update(0, now=0.0)
        # 10 fps → остаток 90/10=9 + прогноз второго прохода 100/(10/3)=30
        assert eta.update(10, now=1.0) == _api.pytest.approx(9.0 + 30.0)

    def test_no_progress_returns_none(self):
        eta = _api.RealETACalculator(total_frames=100)
        eta.update(50, now=0.0)
        assert eta.update(50, now=5.0) is None  # dx == 0

    def test_time_not_advancing_none(self):
        eta = _api.RealETACalculator(total_frames=100)
        eta.update(10, now=5.0)
        assert eta.update(20, now=5.0) is None  # dt == 0

    def test_frame_clamped_to_total(self):
        eta = _api.RealETACalculator(total_frames=100)
        eta.update(0, now=0.0)
        assert eta.update(500, now=10.0) == _api.pytest.approx(0.0)

    def test_total_frames_minimum_one(self):
        eta = _api.RealETACalculator(total_frames=0)
        assert eta.total_frames == 1
        eta2 = _api.RealETACalculator(total_frames=None)
        assert eta2.total_frames == 1

    def test_fmt(self):
        assert _api.RealETACalculator.fmt(None) == "..."
        assert _api.RealETACalculator.fmt(0) == "00:00:00"
        assert _api.RealETACalculator.fmt(3725) == "01:02:05"
        assert _api.RealETACalculator.fmt(-5) == "00:00:00"
        assert _api.RealETACalculator.fmt(59.9) == "00:00:59"

TestEtaPass1.__module__ = _api.__name__
_api.TestEtaPass1 = TestEtaPass1

class TestEtaPass2:
    def _passlog(self, tmp_path, weights):
        log = tmp_path / "ffmpeg2pass-0.log"
        log.write_text("\n".join(f"frame tex={w}" for w in weights),
                       encoding="utf-8")
        return str(tmp_path / "ffmpeg2pass")

    def test_complexity_map_loaded(self, tmp_path):
        base = self._passlog(tmp_path, [1.0, 1.0, 2.0])
        eta = _api.RealETACalculator(total_frames=3, pass_num=2, passlog_path=base)
        assert eta._cum == _api.pytest.approx([0.25, 0.5, 1.0])

    def test_pass2_eta_by_complexity(self, tmp_path):
        base = self._passlog(tmp_path, [1.0] * 10)
        eta = _api.RealETACalculator(total_frames=10, pass_num=2, passlog_path=base)
        eta.update(0, now=0.0)   # x = cum[0] = 0.1
        # к 5-му кадру x = cum[5] = 0.6: Δ0.5 за 5 c → остаток (1−0.6)/0.1 = 4 c
        val = eta.update(5, now=5.0)
        assert val == _api.pytest.approx(4.0, abs=0.01)

    def test_missing_log_falls_back_to_frames(self, tmp_path):
        eta = _api.RealETACalculator(total_frames=100, pass_num=2,
                                passlog_path=str(tmp_path / "нет_лога"))
        assert eta._cum is None
        eta.update(0, now=0.0)
        assert eta.update(50, now=5.0) == _api.pytest.approx(5.0)

    def test_frame_complexity_bounds(self, tmp_path):
        base = self._passlog(tmp_path, [1.0, 3.0])
        eta = _api.RealETACalculator(total_frames=2, pass_num=2, passlog_path=base)
        assert eta._frame_complexity(0) == _api.pytest.approx(0.25)
        assert eta._frame_complexity(999) == _api.pytest.approx(1.0)  # клип к концу

    def test_weight_regex_variants(self, tmp_path):
        log = tmp_path / "x-0.log"
        log.write_text("complexity: 2.5\nbits=100\nWEIGHT = 3\nмусор\n",
                       encoding="utf-8")
        eta = _api.RealETACalculator(total_frames=3, pass_num=2,
                                passlog_path=str(tmp_path / "x"))
        assert len(eta._cum) == 3

TestEtaPass2.__module__ = _api.__name__
_api.TestEtaPass2 = TestEtaPass2

# ── _build_atempo_chain ──────────────────────────────────────────────────────
class TestAtempoChain:
    def test_normal_speed_empty(self):
        assert _api._build_atempo_chain(1.0) == []

    def test_within_range(self):
        assert _api._build_atempo_chain(1.5) == ["atempo=1.500000"]

    def test_above_two(self):
        # 4.0: одно звено 2.0, остаток 2.0 идёт финальным точным звеном
        assert _api._build_atempo_chain(4.0) == ["atempo=2.0", "atempo=2.000000"]

    def test_above_two_fraction(self):
        chain = _api._build_atempo_chain(3.0)
        assert chain == ["atempo=2.0", "atempo=1.500000"]

    def test_below_half(self):
        assert _api._build_atempo_chain(0.25) == ["atempo=0.5", "atempo=0.500000"]

    def test_below_half_fraction(self):
        chain = _api._build_atempo_chain(0.4)
        assert chain[0] == "atempo=0.5"
        assert chain[1].startswith("atempo=0.8")

    def test_product_equals_factor(self):
        for factor in (0.3, 0.75, 1.25, 2.5, 5.0):
            prod = 1.0
            for link in _api._build_atempo_chain(factor):
                prod *= float(link.split("=")[1])
            assert prod == _api.pytest.approx(factor, rel=1e-4)

TestAtempoChain.__module__ = _api.__name__
_api.TestAtempoChain = TestAtempoChain

# ── InfoWorker парсеры ───────────────────────────────────────────────────────
class TestParseSubLangs:
    def test_valid(self):
        raw = _api.json.dumps({"ru": [], "en": [], "live_chat": []})
        assert _api.InfoWorker._parse_sub_langs(raw) == ["en", "ru"]

    def test_empty_dict(self):
        assert _api.InfoWorker._parse_sub_langs("{}") == []

    def test_not_dict(self):
        assert _api.InfoWorker._parse_sub_langs("[1,2]") == []

    def test_invalid_json(self):
        assert _api.InfoWorker._parse_sub_langs("не json") == []

    def test_empty_key_dropped(self):
        raw = _api.json.dumps({"": [], "ru": []})
        assert _api.InfoWorker._parse_sub_langs(raw) == ["ru"]

TestParseSubLangs.__module__ = _api.__name__
_api.TestParseSubLangs = TestParseSubLangs

class TestParseAudioLangs:
    def test_valid(self):
        raw = _api.json.dumps([
            {"acodec": "opus", "language": "ru"},
            {"acodec": "aac", "language": "en"},
            {"acodec": "none", "language": "fr"},      # видео-только
            {"acodec": "opus", "language": "ru"},       # дубль
            {"acodec": "opus", "language": "none"},     # мусорный язык
            {"acodec": "opus", "language": None},
            "мусор",
        ])
        assert _api.InfoWorker._parse_audio_langs(raw) == ["en", "ru"]

    def test_not_list(self):
        assert _api.InfoWorker._parse_audio_langs('{"a": 1}') == []

    def test_invalid_json(self):
        assert _api.InfoWorker._parse_audio_langs("хлам") == []

TestParseAudioLangs.__module__ = _api.__name__
_api.TestParseAudioLangs = TestParseAudioLangs

# ── YtdlpWorker статик-хелперы ───────────────────────────────────────────────
class TestIterStreamLines:
    def test_newlines(self):
        stream = _api.io.StringIO("a\nb\nc")
        assert list(_api.YtdlpWorker._iter_stream_lines(stream)) == ["a", "b", "c"]

    def test_carriage_returns(self):
        # ffmpeg-прогресс приходит через \r без \n
        stream = _api.io.StringIO("frame=1\rframe=2\rframe=3\n")
        assert list(_api.YtdlpWorker._iter_stream_lines(stream)) == \
            ["frame=1", "frame=2", "frame=3"]

    def test_mixed(self):
        stream = _api.io.StringIO("a\r\nb\rc\nd")
        assert list(_api.YtdlpWorker._iter_stream_lines(stream)) == ["a", "b", "c", "d"]

    def test_empty(self):
        assert list(_api.YtdlpWorker._iter_stream_lines(_api.io.StringIO(""))) == []

    def test_trailing_without_newline(self):
        assert list(_api.YtdlpWorker._iter_stream_lines(_api.io.StringIO("tail"))) == ["tail"]

TestIterStreamLines.__module__ = _api.__name__
_api.TestIterStreamLines = TestIterStreamLines

class TestInjectTiktokHeaders:
    def test_inserted_before_url(self):
        cmd = ["yt-dlp", "-f", "best", "https://tiktok.com/@a/video/1"]
        out = _api.YtdlpWorker._inject_tiktok_headers(cmd, "UA-X", ["Referer: t"])
        assert out[-1] == "https://tiktok.com/@a/video/1"
        assert out[out.index("--user-agent") + 1] == "UA-X"
        assert "--add-header" in out
        # исходный список не изменён
        assert cmd == ["yt-dlp", "-f", "best", "https://tiktok.com/@a/video/1"]

    def test_empty_cmd(self):
        out = _api.YtdlpWorker._inject_tiktok_headers([], "UA", [])
        assert out == ["--user-agent", "UA"]

    def test_multiple_headers(self):
        out = _api.YtdlpWorker._inject_tiktok_headers(["url"], "UA", ["A: 1", "B: 2"])
        assert out.count("--add-header") == 2

TestInjectTiktokHeaders.__module__ = _api.__name__
_api.TestInjectTiktokHeaders = TestInjectTiktokHeaders

class TestHeightFromFmt:
    def test_extracts(self):
        assert _api.YtdlpWorker._height_from_fmt(
            "bestvideo[height<=1080]+bestaudio") == 1080

    def test_strict_less(self):
        assert _api.YtdlpWorker._height_from_fmt("height<720") == 720

    def test_default(self):
        assert _api.YtdlpWorker._height_from_fmt("best") == 720
        assert _api.YtdlpWorker._height_from_fmt("") == 720
        assert _api.YtdlpWorker._height_from_fmt(None) == 720

TestHeightFromFmt.__module__ = _api.__name__
_api.TestHeightFromFmt = TestHeightFromFmt

# ── ProcessWorker статик-хелперы ─────────────────────────────────────────────
class TestSanitizeName:
    def test_ai_brand_replaced(self):
        out = _api.ProcessWorker._sanitize_name("видео от ChatGPT.mp4")
        assert "chatgpt" not in out.lower()
        assert len(out) == 6

    def test_gemini_replaced(self):
        assert "gemini" not in _api.ProcessWorker._sanitize_name("GEMINI_output").lower()

    def test_normal_name_kept(self):
        assert _api.ProcessWorker._sanitize_name("моё видео.mp4") == "моё видео.mp4"

TestSanitizeName.__module__ = _api.__name__
_api.TestSanitizeName = TestSanitizeName

class TestPriorityFlag:
    def test_low(self):
        import subprocess
        flag = _api.ProcessWorker._priority_creationflag("low")
        if _api.workers.IS_WIN:
            assert flag == subprocess.IDLE_PRIORITY_CLASS
        else:
            assert flag == 0

    def test_russian_labels(self):
        assert _api.ProcessWorker._priority_creationflag("Низкий") == \
            _api.ProcessWorker._priority_creationflag("low")
        assert _api.ProcessWorker._priority_creationflag("Высокий") == \
            _api.ProcessWorker._priority_creationflag("high")

    def test_default_normal(self):
        import subprocess
        flag = _api.ProcessWorker._priority_creationflag(None)
        if _api.workers.IS_WIN:
            assert flag == subprocess.NORMAL_PRIORITY_CLASS

    def test_unknown_is_normal(self):
        assert _api.ProcessWorker._priority_creationflag("экстрим") == \
            _api.ProcessWorker._priority_creationflag("normal")

TestPriorityFlag.__module__ = _api.__name__
_api.TestPriorityFlag = TestPriorityFlag

class TestChoosePixFmt:
    def test_alpha(self):
        assert _api.ProcessWorker._choose_pix_fmt(True) == "yuva420p10le"

    def test_no_alpha(self):
        assert _api.ProcessWorker._choose_pix_fmt(False) == "yuv420p10le"

TestChoosePixFmt.__module__ = _api.__name__
_api.TestChoosePixFmt = TestChoosePixFmt

class _FakeProbeResult:
    def __init__(self, stdout):
        self.stdout = stdout

_FakeProbeResult.__module__ = _api.__name__
_api._FakeProbeResult = _FakeProbeResult
