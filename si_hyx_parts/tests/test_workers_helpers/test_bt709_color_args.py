# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""TestBt709ColorArgs. Public namespace: test_workers_helpers."""
import test_workers_helpers as _api


class TestBt709ColorArgs:
    """_bt709_color_args тегирует BT.709 только когда это БЕЗОПАСНО — реальный
    HDR/BT.2020 источник не должен получить неверные цветовые теги."""

    def _mock_probe(self, monkeypatch, stdout_lines):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return _api._FakeProbeResult("\n".join(stdout_lines))
        monkeypatch.setattr(_api.workers.subprocess, "run", fake_run)
        return calls

    def test_untagged_source_gets_bt709(self, monkeypatch):
        # Типичный случай: обычный SDR-рип без явных цветовых тегов.
        self._mock_probe(monkeypatch, ["unknown", "unknown", "unknown"])
        args = _api.ProcessWorker._bt709_color_args("x.mp4")
        assert args == ["-color_primaries", "bt709", "-color_trc", "bt709",
                        "-colorspace", "bt709"]

    def test_already_bt709_source_gets_bt709(self, monkeypatch):
        self._mock_probe(monkeypatch, ["bt709", "bt709", "bt709"])
        args = _api.ProcessWorker._bt709_color_args("x.mp4")
        assert "bt709" in args

    def test_hdr_bt2020_source_untouched(self, monkeypatch):
        self._mock_probe(monkeypatch, ["bt2020", "smpte2084", "bt2020nc"])
        args = _api.ProcessWorker._bt709_color_args("x.mp4")
        assert args == []

    def test_hlg_hdr_source_untouched(self, monkeypatch):
        self._mock_probe(monkeypatch, ["bt2020", "arib-std-b67", "bt2020nc"])
        args = _api.ProcessWorker._bt709_color_args("x.mp4")
        assert args == []

    def test_unrecognized_tag_left_alone(self, monkeypatch):
        # Что-то нестандартное (не в белом списке и не HDR-маркер) — не тегируем
        # на всякий случай, а не угадываем.
        self._mock_probe(monkeypatch, ["smpte431", "unknown", "unknown"])
        args = _api.ProcessWorker._bt709_color_args("x.mp4")
        assert args == []

    def test_probe_failure_returns_empty(self, monkeypatch):
        def boom(cmd, **kw):
            raise OSError("no ffprobe")
        monkeypatch.setattr(_api.workers.subprocess, "run", boom)
        assert _api.ProcessWorker._bt709_color_args("x.mp4") == []

TestBt709ColorArgs.__module__ = _api.__name__
_api.TestBt709ColorArgs = TestBt709ColorArgs

class TestMeasureAtCrf:
    """_measure_at_crf: разовое пробное кодирование сэмпла + замер метрики
    (колонка «Оценка XPSNR» для ручного CRF — без бинарного поиска)."""

    class _Fake:
        """Лёгкая замена ProcessWorker: только нужные для _measure_at_crf
        атрибуты/методы, без QThread/QApplication."""
        stop_flag = False
        _SEARCH_PRESET_FLOOR = _api.ProcessWorker._SEARCH_PRESET_FLOOR

        def __init__(self, killable_ok=True, metric_score=41.5, sample=None):
            self._killable_ok = killable_ok
            self._metric_score = metric_score
            self._sample = sample          # чем притвориться короткому сэмплу
            self.killable_calls = []
            self.measure_calls = []
            self.sample_calls = []

        _av1_encoder_args = staticmethod(_api.ProcessWorker._av1_encoder_args)

        def _short_sample(self, path, *a, **k):
            self.sample_calls.append(path)
            return (self._sample or path), self._sample

        def _run_killable(self, cmd, cancel_check=None):
            self.killable_calls.append(cmd)
            return self._killable_ok

        def _measure_metric(self, orig, enc, metric):
            self.measure_calls.append((orig, enc, metric))
            return self._metric_score

    def _patch_fs(self, monkeypatch):
        monkeypatch.setattr(_api.workers.os.path, "exists", lambda p: True)
        monkeypatch.setattr(_api.workers.os, "remove", lambda p: None)

    def test_success_returns_score(self, monkeypatch):
        self._patch_fs(monkeypatch)
        fake = self._Fake(killable_ok=True, metric_score=41.5)
        score = _api.ProcessWorker._measure_at_crf(
            fake, "sample.mkv", 35, 6, "yuv420p10le", 0, [])
        assert score == 41.5
        assert len(fake.killable_calls) == 1
        assert fake.measure_calls[0][2] == "xpsnr"

    def test_encode_failure_returns_none(self, monkeypatch):
        self._patch_fs(monkeypatch)
        fake = self._Fake(killable_ok=False)
        score = _api.ProcessWorker._measure_at_crf(
            fake, "sample.mkv", 35, 6, "yuv420p10le", 0, [])
        assert score is None
        assert not fake.measure_calls  # не мерили — кодирование не удалось

    def test_stop_flag_short_circuits(self, monkeypatch):
        self._patch_fs(monkeypatch)
        fake = self._Fake()
        fake.stop_flag = True
        score = _api.ProcessWorker._measure_at_crf(
            fake, "sample.mkv", 35, 6, "yuv420p10le", 0, [])
        assert score is None
        assert not fake.killable_calls  # даже не пытались кодировать

    def test_cancel_check_short_circuits(self, monkeypatch):
        self._patch_fs(monkeypatch)
        fake = self._Fake()
        score = _api.ProcessWorker._measure_at_crf(
            fake, "sample.mkv", 35, 6, "yuv420p10le", 0, [],
            cancel_check=lambda: True)
        assert score is None
        assert not fake.killable_calls

    def test_vf_list_included_in_command(self, monkeypatch):
        self._patch_fs(monkeypatch)
        fake = self._Fake()
        _api.ProcessWorker._measure_at_crf(
            fake, "sample.mkv", 35, 6, "yuv420p10le", 0, ["scale=640:-2"])
        cmd = fake.killable_calls[0]
        assert "-vf" in cmd and "scale=640:-2" in cmd

    def test_measures_short_sample_not_whole_input(self, monkeypatch):
        """Замер идёт по короткому куску, а не по всему входу: иначе оценка
        стоила ещё одно полное кодирование файла (удвоение времени)."""
        self._patch_fs(monkeypatch)
        fake = self._Fake(sample="short.mkv")
        _api.ProcessWorker._measure_at_crf(
            fake, "whole.mkv", 35, 6, "yuv420p10le", 0, [])
        assert fake.sample_calls == ["whole.mkv"]
        assert "short.mkv" in fake.killable_calls[0]
        assert "whole.mkv" not in fake.killable_calls[0]
        assert fake.measure_calls[0][0] == "short.mkv"   # метрика против сэмпла

    def test_search_preset_floor_applied(self, monkeypatch):
        """Медленный финальный preset не тащим в пробное кодирование: проба
        на preset 2 идёт минутами, а оценка от этого не становится точнее
        (быстрый preset при том же CRF даёт качество не выше финального)."""
        self._patch_fs(monkeypatch)
        fake = self._Fake()
        _api.ProcessWorker._measure_at_crf(
            fake, "sample.mkv", 35, 2, "yuv420p10le", 0, [])
        cmd = fake.killable_calls[0]
        assert cmd[cmd.index("-preset") + 1] == str(_api.ProcessWorker._SEARCH_PRESET_FLOOR)

TestMeasureAtCrf.__module__ = _api.__name__
_api.TestMeasureAtCrf = TestMeasureAtCrf

class TestWantsMetricScore:
    """_wants_metric_score: оценку XPSNR считаем, только когда её видно."""

    def test_off_by_default(self):
        assert _api.ProcessWorker._wants_metric_score({}) is False
        assert _api.ProcessWorker._wants_metric_score(
            {'metric': 'none', 'show_metric_col': False}) is False

    def test_metric_enabled(self):
        assert _api.ProcessWorker._wants_metric_score({'metric': 'xpsnr'}) is True

    def test_column_visible(self):
        assert _api.ProcessWorker._wants_metric_score(
            {'metric': 'none', 'show_metric_col': True}) is True

TestWantsMetricScore.__module__ = _api.__name__
_api.TestWantsMetricScore = TestWantsMetricScore

class TestMetricSamples:
    """Нарезка сэмплов для пробных замеров: только ВХОДНОЙ seek.

    С `-c copy` ffmpeg не декодирует, поэтому выходной `-ss` (после `-i`)
    выбрасывает всё до следующего ключевого кадра — на обычном GOP от
    сэмпла оставалась пара кадров, и подбор CRF/оценка XPSNR при обрезке
    считались по ним."""

    @staticmethod
    def _capture(monkeypatch, size=1024):
        calls = []

        def fake_run(cmd, *a, **k):
            calls.append(list(cmd))
            return None

        monkeypatch.setattr(_api.workers.subprocess, "run", fake_run)
        monkeypatch.setattr(_api.workers.os.path, "exists", lambda p: True)
        monkeypatch.setattr(_api.workers.os.path, "getsize", lambda p: size)
        monkeypatch.setattr(_api.workers.os, "remove", lambda p: None)
        return calls

    @staticmethod
    def _ss_values(cmd):
        return [cmd[i + 1] for i, a in enumerate(cmd) if a == "-ss"]

    # ── _short_sample ────────────────────────────────────────────────────
    def test_short_sample_skips_short_source(self, monkeypatch):
        calls = self._capture(monkeypatch)
        monkeypatch.setattr(_api.workers, "get_media_info", lambda p: (12.0, "", "", "", ""))
        path, tmp = _api.ProcessWorker._short_sample("in.mkv")
        assert (path, tmp) == ("in.mkv", None)
        assert not calls          # резать нечего — ffmpeg не звали

    def test_short_sample_cuts_middle_with_input_seek(self, monkeypatch):
        calls = self._capture(monkeypatch)
        monkeypatch.setattr(_api.workers, "get_media_info", lambda p: (100.0, "", "", "", ""))
        path, tmp = _api.ProcessWorker._short_sample("in.mkv", max_len=15.0)
        assert path == tmp and tmp != "in.mkv"
        cmd = calls[0]
        # единственный -ss стоит ДО -i, длину задаёт -t
        assert self._ss_values(cmd) == ["42.500"]
        assert cmd.index("-ss") < cmd.index("-i")
        assert cmd[cmd.index("-t") + 1] == "15.000"

    # ── _make_metric_sample ──────────────────────────────────────────────
    def test_metric_sample_passthrough_without_trim(self, monkeypatch):
        calls = self._capture(monkeypatch)
        worker = _api.ProcessWorker.__new__(_api.ProcessWorker)
        assert worker._make_metric_sample("in.mkv", None) == ("in.mkv", None)
        assert not calls

    def test_metric_sample_takes_middle_of_range(self, monkeypatch):
        calls = self._capture(monkeypatch)
        worker = _api.ProcessWorker.__new__(_api.ProcessWorker)
        path, tmp = worker._make_metric_sample("in.mkv", (600.0, 700.0), max_len=20.0)
        assert path == tmp
        cmd = calls[0]
        # середина отрезка [600;700) → 640, длина 20 с, seek только входной
        assert self._ss_values(cmd) == ["640.000"]
        assert cmd.index("-ss") < cmd.index("-i")
        assert cmd[cmd.index("-t") + 1] == "20.000"

    def test_metric_sample_short_range_kept_whole(self, monkeypatch):
        calls = self._capture(monkeypatch)
        worker = _api.ProcessWorker.__new__(_api.ProcessWorker)
        worker._make_metric_sample("in.mkv", (5.0, 12.0), max_len=20.0)
        cmd = calls[0]
        assert self._ss_values(cmd) == ["5.000"]
        assert cmd[cmd.index("-t") + 1] == "7.000"

TestMetricSamples.__module__ = _api.__name__
_api.TestMetricSamples = TestMetricSamples

class TestAvifPixFmt:
    def test_alpha_forces_420(self):
        assert _api.ProcessWorker._avif_pix_fmt(True, "444") == "yuva420p10le"

    @_api.pytest.mark.parametrize("chroma,expected", [
        ("420", "yuv420p10le"), ("422", "yuv422p10le"), ("444", "yuv444p10le"),
        ("999", "yuv420p10le"), (None, "yuv420p10le"),
    ])
    def test_chroma(self, chroma, expected):
        assert _api.ProcessWorker._avif_pix_fmt(False, chroma) == expected

TestAvifPixFmt.__module__ = _api.__name__
_api.TestAvifPixFmt = TestAvifPixFmt

class TestTargetDims:
    def test_no_limits(self):
        assert _api.ProcessWorker._target_dims(1920, 1080) is None

    def test_fits_all_limits(self):
        assert _api.ProcessWorker._target_dims(800, 600, adim=1000, wlim=900, hlim=700) is None

    def test_adim(self):
        assert _api.ProcessWorker._target_dims(2000, 1000, adim=1000) == (1000, 500)

    def test_wlim(self):
        assert _api.ProcessWorker._target_dims(2000, 1000, wlim=500) == (500, 250)

    def test_hlim(self):
        assert _api.ProcessWorker._target_dims(2000, 1000, hlim=100) == (200, 100)

    def test_strictest_limit_wins(self):
        w, h = _api.ProcessWorker._target_dims(2000, 1000, adim=1500, wlim=1000, hlim=100)
        assert (w, h) == (200, 100)

    def test_even_dimensions(self):
        w, h = _api.ProcessWorker._target_dims(1001, 333, adim=999)
        assert w % 2 == 0 and h % 2 == 0

    def test_invalid_input(self):
        assert _api.ProcessWorker._target_dims("мусор", 100) is None
        assert _api.ProcessWorker._target_dims(0, 100, adim=50) is None
        assert _api.ProcessWorker._target_dims(-10, 100, adim=50) is None

    def test_minimum_two(self):
        w, h = _api.ProcessWorker._target_dims(10000, 10, adim=20)
        assert w >= 2 and h >= 2

TestTargetDims.__module__ = _api.__name__
_api.TestTargetDims = TestTargetDims
