# -*- coding: utf-8 -*-
"""Тесты вспомогательной логики workers.py: ETA, atempo, парсеры, статик-хелперы."""
import io
import json

import pytest

import workers
from workers import (RealETACalculator, _build_atempo_chain, InfoWorker,
                     YtdlpWorker, ProcessWorker)


# ── RealETACalculator ────────────────────────────────────────────────────────
class TestEtaPass1:
    def test_first_sample_none(self):
        eta = RealETACalculator(total_frames=1000)
        assert eta.update(0, now=100.0) is None

    def test_steady_rate(self):
        eta = RealETACalculator(total_frames=1000)
        eta.update(0, now=100.0)
        # 100 кадров за 10 сек → 10 fps → осталось 900 кадров → 90 сек
        assert eta.update(100, now=110.0) == pytest.approx(90.0)

    def test_window_eviction(self):
        eta = RealETACalculator(total_frames=10_000, window_sec=15.0)
        eta.update(0, now=0.0)      # старый медленный сэмпл
        eta.update(10, now=10.0)
        eta.update(1000, now=20.0)  # разгон
        # окно 15 сек: сэмпл t=0 вытеснен → скорость по (10..1000)/(10..20)=99 fps
        val = eta.update(2000, now=25.0)
        fps = (2000 - 10) / (25.0 - 10.0)
        assert val == pytest.approx((10_000 - 2000) / fps)

    def test_second_pass_projection(self):
        eta = RealETACalculator(total_frames=100, has_second_pass=True,
                                pass2_weight_coefficient=3.0)
        eta.update(0, now=0.0)
        # 10 fps → остаток 90/10=9 + прогноз второго прохода 100/(10/3)=30
        assert eta.update(10, now=1.0) == pytest.approx(9.0 + 30.0)

    def test_no_progress_returns_none(self):
        eta = RealETACalculator(total_frames=100)
        eta.update(50, now=0.0)
        assert eta.update(50, now=5.0) is None  # dx == 0

    def test_time_not_advancing_none(self):
        eta = RealETACalculator(total_frames=100)
        eta.update(10, now=5.0)
        assert eta.update(20, now=5.0) is None  # dt == 0

    def test_frame_clamped_to_total(self):
        eta = RealETACalculator(total_frames=100)
        eta.update(0, now=0.0)
        assert eta.update(500, now=10.0) == pytest.approx(0.0)

    def test_total_frames_minimum_one(self):
        eta = RealETACalculator(total_frames=0)
        assert eta.total_frames == 1
        eta2 = RealETACalculator(total_frames=None)
        assert eta2.total_frames == 1

    def test_fmt(self):
        assert RealETACalculator.fmt(None) == "..."
        assert RealETACalculator.fmt(0) == "00:00:00"
        assert RealETACalculator.fmt(3725) == "01:02:05"
        assert RealETACalculator.fmt(-5) == "00:00:00"
        assert RealETACalculator.fmt(59.9) == "00:00:59"


class TestEtaPass2:
    def _passlog(self, tmp_path, weights):
        log = tmp_path / "ffmpeg2pass-0.log"
        log.write_text("\n".join(f"frame tex={w}" for w in weights),
                       encoding="utf-8")
        return str(tmp_path / "ffmpeg2pass")

    def test_complexity_map_loaded(self, tmp_path):
        base = self._passlog(tmp_path, [1.0, 1.0, 2.0])
        eta = RealETACalculator(total_frames=3, pass_num=2, passlog_path=base)
        assert eta._cum == pytest.approx([0.25, 0.5, 1.0])

    def test_pass2_eta_by_complexity(self, tmp_path):
        base = self._passlog(tmp_path, [1.0] * 10)
        eta = RealETACalculator(total_frames=10, pass_num=2, passlog_path=base)
        eta.update(0, now=0.0)   # x = cum[0] = 0.1
        # к 5-му кадру x = cum[5] = 0.6: Δ0.5 за 5 c → остаток (1−0.6)/0.1 = 4 c
        val = eta.update(5, now=5.0)
        assert val == pytest.approx(4.0, abs=0.01)

    def test_missing_log_falls_back_to_frames(self, tmp_path):
        eta = RealETACalculator(total_frames=100, pass_num=2,
                                passlog_path=str(tmp_path / "нет_лога"))
        assert eta._cum is None
        eta.update(0, now=0.0)
        assert eta.update(50, now=5.0) == pytest.approx(5.0)

    def test_frame_complexity_bounds(self, tmp_path):
        base = self._passlog(tmp_path, [1.0, 3.0])
        eta = RealETACalculator(total_frames=2, pass_num=2, passlog_path=base)
        assert eta._frame_complexity(0) == pytest.approx(0.25)
        assert eta._frame_complexity(999) == pytest.approx(1.0)  # клип к концу

    def test_weight_regex_variants(self, tmp_path):
        log = tmp_path / "x-0.log"
        log.write_text("complexity: 2.5\nbits=100\nWEIGHT = 3\nмусор\n",
                       encoding="utf-8")
        eta = RealETACalculator(total_frames=3, pass_num=2,
                                passlog_path=str(tmp_path / "x"))
        assert len(eta._cum) == 3


# ── _build_atempo_chain ──────────────────────────────────────────────────────
class TestAtempoChain:
    def test_normal_speed_empty(self):
        assert _build_atempo_chain(1.0) == []

    def test_within_range(self):
        assert _build_atempo_chain(1.5) == ["atempo=1.500000"]

    def test_above_two(self):
        # 4.0: одно звено 2.0, остаток 2.0 идёт финальным точным звеном
        assert _build_atempo_chain(4.0) == ["atempo=2.0", "atempo=2.000000"]

    def test_above_two_fraction(self):
        chain = _build_atempo_chain(3.0)
        assert chain == ["atempo=2.0", "atempo=1.500000"]

    def test_below_half(self):
        assert _build_atempo_chain(0.25) == ["atempo=0.5", "atempo=0.500000"]

    def test_below_half_fraction(self):
        chain = _build_atempo_chain(0.4)
        assert chain[0] == "atempo=0.5"
        assert chain[1].startswith("atempo=0.8")

    def test_product_equals_factor(self):
        for factor in (0.3, 0.75, 1.25, 2.5, 5.0):
            prod = 1.0
            for link in _build_atempo_chain(factor):
                prod *= float(link.split("=")[1])
            assert prod == pytest.approx(factor, rel=1e-4)


# ── InfoWorker парсеры ───────────────────────────────────────────────────────
class TestParseSubLangs:
    def test_valid(self):
        raw = json.dumps({"ru": [], "en": [], "live_chat": []})
        assert InfoWorker._parse_sub_langs(raw) == ["en", "ru"]

    def test_empty_dict(self):
        assert InfoWorker._parse_sub_langs("{}") == []

    def test_not_dict(self):
        assert InfoWorker._parse_sub_langs("[1,2]") == []

    def test_invalid_json(self):
        assert InfoWorker._parse_sub_langs("не json") == []

    def test_empty_key_dropped(self):
        raw = json.dumps({"": [], "ru": []})
        assert InfoWorker._parse_sub_langs(raw) == ["ru"]


class TestParseAudioLangs:
    def test_valid(self):
        raw = json.dumps([
            {"acodec": "opus", "language": "ru"},
            {"acodec": "aac", "language": "en"},
            {"acodec": "none", "language": "fr"},      # видео-только
            {"acodec": "opus", "language": "ru"},       # дубль
            {"acodec": "opus", "language": "none"},     # мусорный язык
            {"acodec": "opus", "language": None},
            "мусор",
        ])
        assert InfoWorker._parse_audio_langs(raw) == ["en", "ru"]

    def test_not_list(self):
        assert InfoWorker._parse_audio_langs('{"a": 1}') == []

    def test_invalid_json(self):
        assert InfoWorker._parse_audio_langs("хлам") == []


# ── YtdlpWorker статик-хелперы ───────────────────────────────────────────────
class TestIterStreamLines:
    def test_newlines(self):
        stream = io.StringIO("a\nb\nc")
        assert list(YtdlpWorker._iter_stream_lines(stream)) == ["a", "b", "c"]

    def test_carriage_returns(self):
        # ffmpeg-прогресс приходит через \r без \n
        stream = io.StringIO("frame=1\rframe=2\rframe=3\n")
        assert list(YtdlpWorker._iter_stream_lines(stream)) == \
            ["frame=1", "frame=2", "frame=3"]

    def test_mixed(self):
        stream = io.StringIO("a\r\nb\rc\nd")
        assert list(YtdlpWorker._iter_stream_lines(stream)) == ["a", "b", "c", "d"]

    def test_empty(self):
        assert list(YtdlpWorker._iter_stream_lines(io.StringIO(""))) == []

    def test_trailing_without_newline(self):
        assert list(YtdlpWorker._iter_stream_lines(io.StringIO("tail"))) == ["tail"]


class TestInjectTiktokHeaders:
    def test_inserted_before_url(self):
        cmd = ["yt-dlp", "-f", "best", "https://tiktok.com/@a/video/1"]
        out = YtdlpWorker._inject_tiktok_headers(cmd, "UA-X", ["Referer: t"])
        assert out[-1] == "https://tiktok.com/@a/video/1"
        assert out[out.index("--user-agent") + 1] == "UA-X"
        assert "--add-header" in out
        # исходный список не изменён
        assert cmd == ["yt-dlp", "-f", "best", "https://tiktok.com/@a/video/1"]

    def test_empty_cmd(self):
        out = YtdlpWorker._inject_tiktok_headers([], "UA", [])
        assert out == ["--user-agent", "UA"]

    def test_multiple_headers(self):
        out = YtdlpWorker._inject_tiktok_headers(["url"], "UA", ["A: 1", "B: 2"])
        assert out.count("--add-header") == 2


class TestHeightFromFmt:
    def test_extracts(self):
        assert YtdlpWorker._height_from_fmt(
            "bestvideo[height<=1080]+bestaudio") == 1080

    def test_strict_less(self):
        assert YtdlpWorker._height_from_fmt("height<720") == 720

    def test_default(self):
        assert YtdlpWorker._height_from_fmt("best") == 720
        assert YtdlpWorker._height_from_fmt("") == 720
        assert YtdlpWorker._height_from_fmt(None) == 720


# ── ProcessWorker статик-хелперы ─────────────────────────────────────────────
class TestSanitizeName:
    def test_ai_brand_replaced(self):
        out = ProcessWorker._sanitize_name("видео от ChatGPT.mp4")
        assert "chatgpt" not in out.lower()
        assert len(out) == 6

    def test_gemini_replaced(self):
        assert "gemini" not in ProcessWorker._sanitize_name("GEMINI_output").lower()

    def test_normal_name_kept(self):
        assert ProcessWorker._sanitize_name("моё видео.mp4") == "моё видео.mp4"


class TestPriorityFlag:
    def test_low(self):
        import subprocess
        flag = ProcessWorker._priority_creationflag("low")
        if workers.IS_WIN:
            assert flag == subprocess.IDLE_PRIORITY_CLASS
        else:
            assert flag == 0

    def test_russian_labels(self):
        assert ProcessWorker._priority_creationflag("Низкий") == \
            ProcessWorker._priority_creationflag("low")
        assert ProcessWorker._priority_creationflag("Высокий") == \
            ProcessWorker._priority_creationflag("high")

    def test_default_normal(self):
        import subprocess
        flag = ProcessWorker._priority_creationflag(None)
        if workers.IS_WIN:
            assert flag == subprocess.NORMAL_PRIORITY_CLASS

    def test_unknown_is_normal(self):
        assert ProcessWorker._priority_creationflag("экстрим") == \
            ProcessWorker._priority_creationflag("normal")


class TestChoosePixFmt:
    def test_alpha(self):
        assert ProcessWorker._choose_pix_fmt(True) == "yuva420p10le"

    def test_no_alpha(self):
        assert ProcessWorker._choose_pix_fmt(False) == "yuv420p10le"


class _FakeProbeResult:
    def __init__(self, stdout):
        self.stdout = stdout


class TestBt709ColorArgs:
    """_bt709_color_args тегирует BT.709 только когда это БЕЗОПАСНО — реальный
    HDR/BT.2020 источник не должен получить неверные цветовые теги."""

    def _mock_probe(self, monkeypatch, stdout_lines):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return _FakeProbeResult("\n".join(stdout_lines))
        monkeypatch.setattr(workers.subprocess, "run", fake_run)
        return calls

    def test_untagged_source_gets_bt709(self, monkeypatch):
        # Типичный случай: обычный SDR-рип без явных цветовых тегов.
        self._mock_probe(monkeypatch, ["unknown", "unknown", "unknown"])
        args = ProcessWorker._bt709_color_args("x.mp4")
        assert args == ["-color_primaries", "bt709", "-color_trc", "bt709",
                        "-colorspace", "bt709"]

    def test_already_bt709_source_gets_bt709(self, monkeypatch):
        self._mock_probe(monkeypatch, ["bt709", "bt709", "bt709"])
        args = ProcessWorker._bt709_color_args("x.mp4")
        assert "bt709" in args

    def test_hdr_bt2020_source_untouched(self, monkeypatch):
        self._mock_probe(monkeypatch, ["bt2020", "smpte2084", "bt2020nc"])
        args = ProcessWorker._bt709_color_args("x.mp4")
        assert args == []

    def test_hlg_hdr_source_untouched(self, monkeypatch):
        self._mock_probe(monkeypatch, ["bt2020", "arib-std-b67", "bt2020nc"])
        args = ProcessWorker._bt709_color_args("x.mp4")
        assert args == []

    def test_unrecognized_tag_left_alone(self, monkeypatch):
        # Что-то нестандартное (не в белом списке и не HDR-маркер) — не тегируем
        # на всякий случай, а не угадываем.
        self._mock_probe(monkeypatch, ["smpte431", "unknown", "unknown"])
        args = ProcessWorker._bt709_color_args("x.mp4")
        assert args == []

    def test_probe_failure_returns_empty(self, monkeypatch):
        def boom(cmd, **kw):
            raise OSError("no ffprobe")
        monkeypatch.setattr(workers.subprocess, "run", boom)
        assert ProcessWorker._bt709_color_args("x.mp4") == []


class TestMeasureAtCrf:
    """_measure_at_crf: разовое пробное кодирование сэмпла + замер метрики
    (колонка «Оценка XPSNR» для ручного CRF — без бинарного поиска)."""

    class _Fake:
        """Лёгкая замена ProcessWorker: только нужные для _measure_at_crf
        атрибуты/методы, без QThread/QApplication."""
        stop_flag = False

        def __init__(self, killable_ok=True, metric_score=41.5):
            self._killable_ok = killable_ok
            self._metric_score = metric_score
            self.killable_calls = []
            self.measure_calls = []

        _av1_encoder_args = staticmethod(ProcessWorker._av1_encoder_args)

        def _run_killable(self, cmd, cancel_check=None):
            self.killable_calls.append(cmd)
            return self._killable_ok

        def _measure_metric(self, orig, enc, metric):
            self.measure_calls.append((orig, enc, metric))
            return self._metric_score

    def _patch_fs(self, monkeypatch):
        monkeypatch.setattr(workers.os.path, "exists", lambda p: True)
        monkeypatch.setattr(workers.os, "remove", lambda p: None)

    def test_success_returns_score(self, monkeypatch):
        self._patch_fs(monkeypatch)
        fake = self._Fake(killable_ok=True, metric_score=41.5)
        score = ProcessWorker._measure_at_crf(
            fake, "sample.mkv", 35, 6, "yuv420p10le", 0, [])
        assert score == 41.5
        assert len(fake.killable_calls) == 1
        assert fake.measure_calls[0][2] == "xpsnr"

    def test_encode_failure_returns_none(self, monkeypatch):
        self._patch_fs(monkeypatch)
        fake = self._Fake(killable_ok=False)
        score = ProcessWorker._measure_at_crf(
            fake, "sample.mkv", 35, 6, "yuv420p10le", 0, [])
        assert score is None
        assert not fake.measure_calls  # не мерили — кодирование не удалось

    def test_stop_flag_short_circuits(self, monkeypatch):
        self._patch_fs(monkeypatch)
        fake = self._Fake()
        fake.stop_flag = True
        score = ProcessWorker._measure_at_crf(
            fake, "sample.mkv", 35, 6, "yuv420p10le", 0, [])
        assert score is None
        assert not fake.killable_calls  # даже не пытались кодировать

    def test_cancel_check_short_circuits(self, monkeypatch):
        self._patch_fs(monkeypatch)
        fake = self._Fake()
        score = ProcessWorker._measure_at_crf(
            fake, "sample.mkv", 35, 6, "yuv420p10le", 0, [],
            cancel_check=lambda: True)
        assert score is None
        assert not fake.killable_calls

    def test_vf_list_included_in_command(self, monkeypatch):
        self._patch_fs(monkeypatch)
        fake = self._Fake()
        ProcessWorker._measure_at_crf(
            fake, "sample.mkv", 35, 6, "yuv420p10le", 0, ["scale=640:-2"])
        cmd = fake.killable_calls[0]
        assert "-vf" in cmd and "scale=640:-2" in cmd


class TestAvifPixFmt:
    def test_alpha_forces_420(self):
        assert ProcessWorker._avif_pix_fmt(True, "444") == "yuva420p10le"

    @pytest.mark.parametrize("chroma,expected", [
        ("420", "yuv420p10le"), ("422", "yuv422p10le"), ("444", "yuv444p10le"),
        ("999", "yuv420p10le"), (None, "yuv420p10le"),
    ])
    def test_chroma(self, chroma, expected):
        assert ProcessWorker._avif_pix_fmt(False, chroma) == expected


class TestTargetDims:
    def test_no_limits(self):
        assert ProcessWorker._target_dims(1920, 1080) is None

    def test_fits_all_limits(self):
        assert ProcessWorker._target_dims(800, 600, adim=1000, wlim=900, hlim=700) is None

    def test_adim(self):
        assert ProcessWorker._target_dims(2000, 1000, adim=1000) == (1000, 500)

    def test_wlim(self):
        assert ProcessWorker._target_dims(2000, 1000, wlim=500) == (500, 250)

    def test_hlim(self):
        assert ProcessWorker._target_dims(2000, 1000, hlim=100) == (200, 100)

    def test_strictest_limit_wins(self):
        w, h = ProcessWorker._target_dims(2000, 1000, adim=1500, wlim=1000, hlim=100)
        assert (w, h) == (200, 100)

    def test_even_dimensions(self):
        w, h = ProcessWorker._target_dims(1001, 333, adim=999)
        assert w % 2 == 0 and h % 2 == 0

    def test_invalid_input(self):
        assert ProcessWorker._target_dims("мусор", 100) is None
        assert ProcessWorker._target_dims(0, 100, adim=50) is None
        assert ProcessWorker._target_dims(-10, 100, adim=50) is None

    def test_minimum_two(self):
        w, h = ProcessWorker._target_dims(10000, 10, adim=20)
        assert w >= 2 and h >= 2


class TestAv1EncoderArgs:
    def test_args(self):
        args = ProcessWorker._av1_encoder_args(35, 6, "yuv420p10le")
        assert args[args.index("-c:v") + 1] == "libsvtav1"
        assert args[args.index("-crf") + 1] == "35"
        assert args[args.index("-preset") + 1] == "6"
        assert "tune=0" in args[args.index("-svtav1-params") + 1]

    def test_preset_clamped(self):
        args = ProcessWorker._av1_encoder_args(30, 99, "x")
        assert args[args.index("-preset") + 1] == "13"
        args = ProcessWorker._av1_encoder_args(30, -5, "x")
        assert args[args.index("-preset") + 1] == "0"

    def test_tune_param(self):
        for tune in (0, 1, 2, 4, 5):
            args = ProcessWorker._av1_encoder_args(35, 6, "yuv420p10le", tune)
            assert f"tune={tune}" in args[args.index("-svtav1-params") + 1]


class TestTrimSeekArgs:
    def test_early_start_no_preseek(self):
        pre, post, t0 = ProcessWorker._trim_seek_args(2.0, 10.0)
        assert pre == []
        assert post == ["-ss", "2.000000", "-t", "8.000000"]
        assert t0 == 2.0

    def test_late_start_preseek(self):
        pre, post, t0 = ProcessWorker._trim_seek_args(60.0, 70.0)
        assert pre == ["-ss", "57.000000"]
        assert post == ["-ss", "3.000000", "-t", "10.000000"]
        assert t0 == 3.0  # шкала фильтров начинается с выходного -ss

    def test_boundary_exactly_2preseek(self):
        # in_s == 6.0 НЕ больше 2*PRESEEK → ветка без пре-сика
        pre, post, t0 = ProcessWorker._trim_seek_args(6.0, 10.0)
        assert pre == []
        assert t0 == 6.0

    def test_speed_factor_divides_duration(self):
        _, post, _ = ProcessWorker._trim_seek_args(0.0, 5.0, speed_factor=1.5)
        t_idx = post.index("-t") + 1
        assert float(post[t_idx]) == pytest.approx(5.0 / 1.5)

    def test_speed_factor_divides_output_seek_preseek(self):
        # ВЫХОДНОЙ -ss тоже делится на speed_factor (он в постфильтровой шкале,
        # где видео уже сжато setpts). Без деления старт уезжал вправо на
        # PRESEEK*(speed-1). Ветка pre-seek: post -ss = PRESEEK/speed.
        _, post, _ = ProcessWorker._trim_seek_args(60.0, 70.0, speed_factor=1.07)
        ss_idx = post.index("-ss") + 1
        assert float(post[ss_idx]) == pytest.approx(3.0 / 1.07)

    def test_speed_factor_divides_output_seek_no_preseek(self):
        # Ветка без pre-seek (in_s ≤ 2*PRESEEK): post -ss = in_s/speed.
        _, post, _ = ProcessWorker._trim_seek_args(4.0, 9.0, speed_factor=1.07)
        ss_idx = post.index("-ss") + 1
        assert float(post[ss_idx]) == pytest.approx(4.0 / 1.07)

    def test_speed_100pct_output_seek_unchanged(self):
        # При нормальной скорости деление на sf=1 ничего не меняет.
        _, post, _ = ProcessWorker._trim_seek_args(60.0, 70.0, speed_factor=1.0)
        assert post[post.index("-ss") + 1] == "3.000000"

    def test_zero_speed_factor_no_crash(self):
        _, post, _ = ProcessWorker._trim_seek_args(0.0, 5.0, speed_factor=0)
        assert float(post[post.index("-t") + 1]) == pytest.approx(5.0)

    def test_negative_range_clamped(self):
        _, post, _ = ProcessWorker._trim_seek_args(10.0, 5.0)
        assert float(post[post.index("-t") + 1]) == 0.0


# ── ProcessWorker._out_suffix ────────────────────────────────────────────────
class TestOutSuffix:
    def test_video_manual_crf(self):
        s = ProcessWorker._out_suffix(True, True, 'none', 45, 100,
                                      remove_audio=False, norm=False, fade=False)
        assert s == "_crf45_speed100"

    def test_video_xpsnr_autocrf(self):
        # метрика xpsnr → маркер режима вместо числа (реальный CRF ещё не подобран)
        s = ProcessWorker._out_suffix(True, True, 'xpsnr', 45, 90,
                                      remove_audio=False, norm=False, fade=False)
        assert s == "_autocrf_speed90"

    def test_video_disabled_no_crf_part(self):
        s = ProcessWorker._out_suffix(True, False, 'none', 45, 100,
                                      remove_audio=False, norm=True, fade=False)
        assert s == "_norm"

    def test_audio_only_no_crf_part(self):
        s = ProcessWorker._out_suffix(False, True, 'none', 45, 100,
                                      remove_audio=False, norm=True, fade=True)
        assert s == "_norm_fade"

    def test_remove_audio_wins_over_norm(self):
        s = ProcessWorker._out_suffix(True, True, 'none', 30, 100,
                                      remove_audio=True, norm=True, fade=True)
        # remove_audio → _noaudio, и _fade НЕ добавляется (звука нет)
        assert s == "_crf30_speed100_noaudio"

    def test_norm_and_fade(self):
        s = ProcessWorker._out_suffix(False, False, 'none', 0, 100,
                                      remove_audio=False, norm=True, fade=True)
        assert s == "_norm_fade"

    def test_all_empty(self):
        s = ProcessWorker._out_suffix(False, False, 'none', 0, 100,
                                      remove_audio=False, norm=False, fade=False)
        assert s == ""


# ── ProcessWorker._build_audio_filters ───────────────────────────────────────
class TestBuildAudioFilters:
    def test_empty_settings(self):
        assert ProcessWorker._build_audio_filters({}, 0.0, 0.0, 1.0) == []

    def test_loudnorm_values(self):
        f = ProcessWorker._build_audio_filters(
            {'norm': True, 'tgt': -18.0, 'lra': 9.0, 'tp': -2.0}, 0.0, 0.0, 1.0)
        assert f == ["loudnorm=I=-18.0:LRA=9.0:TP=-2.0"]

    def test_loudnorm_defaults(self):
        f = ProcessWorker._build_audio_filters({'norm': True}, 0.0, 0.0, 1.0)
        assert f == ["loudnorm=I=-20.0:LRA=11.0:TP=-1.5"]

    def test_fade_in_uses_t0(self):
        f = ProcessWorker._build_audio_filters(
            {'fade_in': True, 'fade_in_d': 2.0}, 5.0, 0.0, 1.0)
        assert f == ["afade=t=in:st=5.000:d=2.0"]

    def test_fade_out_position(self):
        # st = max(0, t0 + dur - d) = 3 + 10 - 1.5 = 11.5
        f = ProcessWorker._build_audio_filters(
            {'fade': True, 'fade_d': 1.5}, 3.0, 10.0, 1.0)
        assert f == ["afade=t=out:st=11.500:d=1.5"]

    def test_fade_out_clamped_nonnegative(self):
        f = ProcessWorker._build_audio_filters(
            {'fade': True, 'fade_d': 100.0}, 0.0, 1.0, 1.0)
        assert f == ["afade=t=out:st=0.000:d=100.0"]

    def test_degrade_chain(self):
        f = ProcessWorker._build_audio_filters(
            {'deg': True, 'lp': 2500, 'hp': 300, 'hz': 8000, 'u8': True,
             'deg_gain_db': 3.0}, 0.0, 0.0, 1.0)
        assert f == ["lowpass=f=2500", "highpass=f=300",
                     "aformat=sample_fmts=u8:sample_rates=8000", "volume=3.0dB"]

    def test_degrade_no_u8_no_gain(self):
        f = ProcessWorker._build_audio_filters(
            {'deg': True, 'lp': 3000, 'hp': 200, 'deg_gain_db': 0.0}, 0.0, 0.0, 1.0)
        assert f == ["lowpass=f=3000", "highpass=f=200"]

    def test_speed_appends_atempo_last(self):
        f = ProcessWorker._build_audio_filters(
            {'norm': True}, 0.0, 0.0, 1.5)
        assert f[0].startswith("loudnorm")
        assert f[-1] == "atempo=1.500000"

    def test_full_order_preserved(self):
        f = ProcessWorker._build_audio_filters(
            {'norm': True, 'fade_in': True, 'fade': True, 'deg': True}, 0.0, 5.0, 2.0)
        kinds = [x.split('=')[0] for x in f]
        # loudnorm → afade(in) → afade(out) → lowpass → highpass → atempo
        assert kinds[0] == "loudnorm"
        assert kinds[1] == "afade" and "t=in" in f[1]
        assert kinds[2] == "afade" and "t=out" in f[2]
        assert "lowpass" in kinds and "highpass" in kinds
        assert kinds[-1] == "atempo"

    def test_normal_speed_no_atempo(self):
        f = ProcessWorker._build_audio_filters({'norm': True}, 0.0, 0.0, 1.0)
        assert not any("atempo" in x for x in f)


# ── ProcessWorker._scale_vf ──────────────────────────────────────────────────
class TestScaleVf:
    def test_original_returns_none(self):
        assert ProcessWorker._scale_vf("Исходное") is None

    def test_empty_returns_none(self):
        assert ProcessWorker._scale_vf("") is None
        assert ProcessWorker._scale_vf(None) is None

    def test_wxh_builds_fitted_scale(self):
        vf = ProcessWorker._scale_vf("1280x720")
        assert vf == ("scale=w='min(iw,1280)':h='min(ih,720)'"
                      ":force_original_aspect_ratio=decrease:force_divisible_by=2")

    def test_bad_wxh_falls_back(self):
        vf = ProcessWorker._scale_vf("axb")
        assert vf == "scale=axb:force_divisible_by=2"

    def test_expression_without_x(self):
        vf = ProcessWorker._scale_vf("iw/2:ih/2")
        assert vf == "scale=iw/2:ih/2:force_divisible_by=2"


# ── ProcessWorker._af_arg ────────────────────────────────────────────────────
class TestAfArg:
    def test_layout_fix_always_last(self):
        assert ProcessWorker._af_arg([]) == workers.OPUS_LAYOUT_FIX

    def test_filters_then_layout_fix(self):
        arg = ProcessWorker._af_arg(["loudnorm=I=-20", "afade=t=in:st=0:d=1"])
        assert arg == f"loudnorm=I=-20,afade=t=in:st=0:d=1,{workers.OPUS_LAYOUT_FIX}"

    def test_trim_tail_inserts_aresample_before_layout_fix(self):
        arg = ProcessWorker._af_arg(["loudnorm=I=-20"], trim_tail=True)
        assert arg == f"loudnorm=I=-20,aresample=async=1,{workers.OPUS_LAYOUT_FIX}"

    def test_does_not_mutate_input(self):
        src = ["loudnorm=I=-20"]
        ProcessWorker._af_arg(src, trim_tail=True)
        assert src == ["loudnorm=I=-20"]


# ── ProcessWorker._map_av_args ───────────────────────────────────────────────
class TestMapAvArgs:
    def test_keeps_audio_by_default(self):
        assert ProcessWorker._map_av_args(False, "0:a?") == [
            "-map", "0:V?", "-map", "0:a?"]

    def test_selected_track(self):
        assert ProcessWorker._map_av_args(False, "0:3") == [
            "-map", "0:V?", "-map", "0:3"]

    def test_remove_audio_drops_map(self):
        assert ProcessWorker._map_av_args(True, "0:3") == ["-map", "0:V?"]


# ── ProcessWorker._fps_args ──────────────────────────────────────────────────
class TestFpsArgs:
    def test_original_is_noop(self):
        assert ProcessWorker._fps_args("Исходный", "x.mp4") == []

    def test_max30_caps_fast_source(self, monkeypatch):
        monkeypatch.setattr(workers, "get_fps_float", lambda p: 60.0)
        assert ProcessWorker._fps_args("Исходный (max 30)", "x.mp4") == ["-r", "30"]

    def test_max30_leaves_slow_source(self, monkeypatch):
        monkeypatch.setattr(workers, "get_fps_float", lambda p: 24.0)
        assert ProcessWorker._fps_args("Исходный (max 30)", "x.mp4") == []

    def test_max30_probe_failure_is_noop(self, monkeypatch):
        def boom(p): raise OSError("ffprobe умер")
        monkeypatch.setattr(workers, "get_fps_float", boom)
        assert ProcessWorker._fps_args("Исходный (max 30)", "x.mp4") == []

    def test_numeric_value(self):
        assert ProcessWorker._fps_args("30", "x.mp4") == ["-r", "30"]

    def test_non_numeric_ignored(self):
        assert ProcessWorker._fps_args("мусор", "x.mp4") == []


# ── ProcessWorker._avif_encode_cmd ───────────────────────────────────────────
class TestAvifEncodeCmd:
    def _cmd(self, **kw):
        args = dict(src="in.png", tmp_out="out.avif", crf_val=30, scale_vf=None,
                    has_alpha=False, pix_fmt="yuv420p10le", aspd=4)
        args.update(kw)
        return ProcessWorker._avif_encode_cmd(**args)

    def test_plain_uses_libaom_and_tune_iq(self):
        c = self._cmd()
        assert c[-1] == "out.avif"
        assert c[c.index("-c:v") + 1] == "libaom-av1"
        assert c[c.index("-aom-params") + 1] == "tune=iq"
        assert c[c.index("-crf") + 1] == "30"
        assert c[c.index("-pix_fmt") + 1] == "yuv420p10le"
        assert "-frames:v" in c and "-filter_complex" not in c

    def test_plain_scale_goes_to_vf(self):
        c = self._cmd(scale_vf="scale=800:600")
        assert c[c.index("-vf") + 1] == "scale=800:600"

    def test_plain_without_scale_has_no_vf(self):
        assert "-vf" not in self._cmd()

    def test_cpu_used_is_clamped(self):
        hi = self._cmd(aspd=99)
        assert hi[hi.index("-cpu-used") + 1] == "8"
        lo = self._cmd(aspd=-5)
        assert lo[lo.index("-cpu-used") + 1] == "0"

    def test_alpha_splits_before_scale(self):
        # split ДО scale — иначе ffmpeg роняет альфу на alphaextract
        c = self._cmd(has_alpha=True, scale_vf="scale=800:600")
        fc = c[c.index("-filter_complex") + 1]
        assert fc.index("split") < fc.index("scale=800:600")
        assert "alphaextract,scale=800:600[alf]" in fc
        assert c[c.index("-still-picture") + 1] == "1"

    def test_alpha_without_scale(self):
        c = self._cmd(has_alpha=True)
        fc = c[c.index("-filter_complex") + 1]
        assert fc == "[0:v]format=yuva420p10le,split[main][a];[a]alphaextract[alf]"

    def test_alpha_maps_both_streams_and_ignores_pix_fmt(self):
        c = self._cmd(has_alpha=True)
        assert c.count("-map") == 2 and "[main]" in c and "[alf]" in c
        assert "-pix_fmt" not in c


# ── ProcessWorker._avif_downscale_side ───────────────────────────────────────
class TestAvifDownscaleSide:
    def test_halving_bytes_scales_side_by_sqrt(self):
        # нужна половина байт → примерно 1/√2 стороны (с запасом 2% по площади)
        side = ProcessWorker._avif_downscale_side(4000, 3000, baseline_kb=1000,
                                                  limit_kb=500)
        assert 2780 <= side <= 2840

    def test_always_shrinks_even_if_baseline_fits(self):
        # Доля площади клампится к 1.0, но запас 0.98 всё равно срезает ~1%
        # стороны — проба никогда не повторяет предыдущую один в один.
        side = ProcessWorker._avif_downscale_side(1000, 800, baseline_kb=100,
                                                  limit_kb=5000)
        assert side == 989

    def test_tiny_image_hits_the_ten_percent_guard(self):
        # На совсем мелких сторонах усечение int() съедает весь запас 0.98 →
        # срабатывает явный откат «уменьшить на 10%».
        assert ProcessWorker._avif_downscale_side(10, 8, baseline_kb=100,
                                                  limit_kb=5000) == 9

    def test_ratio_floor_prevents_zero_side(self):
        side = ProcessWorker._avif_downscale_side(4000, 3000, baseline_kb=10 ** 6,
                                                  limit_kb=1)
        assert side >= 1

    def test_zero_baseline_falls_back_to_half(self):
        side = ProcessWorker._avif_downscale_side(1000, 1000, baseline_kb=0,
                                                  limit_kb=100)
        assert 690 <= side <= 710
