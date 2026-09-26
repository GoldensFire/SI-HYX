# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""TestAv1EncoderArgs. Public namespace: test_workers_helpers."""
import test_workers_helpers as _api


class TestAv1EncoderArgs:
    def test_args(self):
        args = _api.ProcessWorker._av1_encoder_args(35, 6, "yuv420p10le")
        assert args[args.index("-c:v") + 1] == "libsvtav1"
        assert args[args.index("-crf") + 1] == "35"
        assert args[args.index("-preset") + 1] == "6"
        assert "tune=0" in args[args.index("-svtav1-params") + 1]

    def test_preset_clamped(self):
        args = _api.ProcessWorker._av1_encoder_args(30, 99, "x")
        assert args[args.index("-preset") + 1] == "13"
        args = _api.ProcessWorker._av1_encoder_args(30, -5, "x")
        assert args[args.index("-preset") + 1] == "0"

    def test_tune_param(self):
        for tune in (0, 1, 2, 4, 5):
            args = _api.ProcessWorker._av1_encoder_args(35, 6, "yuv420p10le", tune)
            assert f"tune={tune}" in args[args.index("-svtav1-params") + 1]

TestAv1EncoderArgs.__module__ = _api.__name__
_api.TestAv1EncoderArgs = TestAv1EncoderArgs

class TestTrimSeekArgs:
    def test_early_start_no_preseek(self):
        pre, post, t0 = _api.ProcessWorker._trim_seek_args(2.0, 10.0)
        assert pre == []
        assert post == ["-ss", "2.000000", "-t", "8.000000"]
        assert t0 == 2.0

    def test_late_start_preseek(self):
        pre, post, t0 = _api.ProcessWorker._trim_seek_args(60.0, 70.0)
        assert pre == ["-ss", "57.000000"]
        assert post == ["-ss", "3.000000", "-t", "10.000000"]
        assert t0 == 3.0  # шкала фильтров начинается с выходного -ss

    def test_boundary_exactly_2preseek(self):
        # in_s == 6.0 НЕ больше 2*PRESEEK → ветка без пре-сика
        pre, post, t0 = _api.ProcessWorker._trim_seek_args(6.0, 10.0)
        assert pre == []
        assert t0 == 6.0

    def test_speed_factor_divides_duration(self):
        _, post, _ = _api.ProcessWorker._trim_seek_args(0.0, 5.0, speed_factor=1.5)
        t_idx = post.index("-t") + 1
        assert float(post[t_idx]) == _api.pytest.approx(5.0 / 1.5)

    def test_speed_factor_divides_output_seek_preseek(self):
        # ВЫХОДНОЙ -ss тоже делится на speed_factor (он в постфильтровой шкале,
        # где видео уже сжато setpts). Без деления старт уезжал вправо на
        # PRESEEK*(speed-1). Ветка pre-seek: post -ss = PRESEEK/speed.
        _, post, _ = _api.ProcessWorker._trim_seek_args(60.0, 70.0, speed_factor=1.07)
        ss_idx = post.index("-ss") + 1
        assert float(post[ss_idx]) == _api.pytest.approx(3.0 / 1.07)

    def test_speed_factor_divides_output_seek_no_preseek(self):
        # Ветка без pre-seek (in_s ≤ 2*PRESEEK): post -ss = in_s/speed.
        _, post, _ = _api.ProcessWorker._trim_seek_args(4.0, 9.0, speed_factor=1.07)
        ss_idx = post.index("-ss") + 1
        assert float(post[ss_idx]) == _api.pytest.approx(4.0 / 1.07)

    def test_speed_100pct_output_seek_unchanged(self):
        # При нормальной скорости деление на sf=1 ничего не меняет.
        _, post, _ = _api.ProcessWorker._trim_seek_args(60.0, 70.0, speed_factor=1.0)
        assert post[post.index("-ss") + 1] == "3.000000"

    def test_zero_speed_factor_no_crash(self):
        _, post, _ = _api.ProcessWorker._trim_seek_args(0.0, 5.0, speed_factor=0)
        assert float(post[post.index("-t") + 1]) == _api.pytest.approx(5.0)

    def test_negative_range_clamped(self):
        _, post, _ = _api.ProcessWorker._trim_seek_args(10.0, 5.0)
        assert float(post[post.index("-t") + 1]) == 0.0

TestTrimSeekArgs.__module__ = _api.__name__
_api.TestTrimSeekArgs = TestTrimSeekArgs

# ── ProcessWorker._out_suffix ────────────────────────────────────────────────
class TestOutSuffix:
    def test_video_manual_crf(self):
        s = _api.ProcessWorker._out_suffix(True, True, 'none', 45, 100,
                                      remove_audio=False, norm=False, fade=False)
        assert s == "_crf45_speed100"

    def test_video_xpsnr_autocrf(self):
        # метрика xpsnr → маркер режима вместо числа (реальный CRF ещё не подобран)
        s = _api.ProcessWorker._out_suffix(True, True, 'xpsnr', 45, 90,
                                      remove_audio=False, norm=False, fade=False)
        assert s == "_autocrf_speed90"

    def test_video_disabled_no_crf_part(self):
        s = _api.ProcessWorker._out_suffix(True, False, 'none', 45, 100,
                                      remove_audio=False, norm=True, fade=False)
        assert s == "_norm"

    def test_audio_only_no_crf_part(self):
        s = _api.ProcessWorker._out_suffix(False, True, 'none', 45, 100,
                                      remove_audio=False, norm=True, fade=True)
        assert s == "_norm_fade"

    def test_remove_audio_wins_over_norm(self):
        s = _api.ProcessWorker._out_suffix(True, True, 'none', 30, 100,
                                      remove_audio=True, norm=True, fade=True)
        # remove_audio → _noaudio, и _fade НЕ добавляется (звука нет)
        assert s == "_crf30_speed100_noaudio"

    def test_norm_and_fade(self):
        s = _api.ProcessWorker._out_suffix(False, False, 'none', 0, 100,
                                      remove_audio=False, norm=True, fade=True)
        assert s == "_norm_fade"

    def test_all_empty(self):
        s = _api.ProcessWorker._out_suffix(False, False, 'none', 0, 100,
                                      remove_audio=False, norm=False, fade=False)
        assert s == ""

TestOutSuffix.__module__ = _api.__name__
_api.TestOutSuffix = TestOutSuffix

# ── ProcessWorker._build_audio_filters ───────────────────────────────────────
class TestBuildAudioFilters:
    def test_empty_settings(self):
        assert _api.ProcessWorker._build_audio_filters({}, 0.0, 0.0, 1.0) == []

    def test_loudnorm_values(self):
        f = _api.ProcessWorker._build_audio_filters(
            {'norm': True, 'tgt': -18.0, 'lra': 9.0, 'tp': -2.0}, 0.0, 0.0, 1.0)
        assert f == ["loudnorm=I=-18.0:LRA=9.0:TP=-2.0"]

    def test_loudnorm_defaults(self):
        f = _api.ProcessWorker._build_audio_filters({'norm': True}, 0.0, 0.0, 1.0)
        assert f == ["loudnorm=I=-20.0:LRA=11.0:TP=-1.5"]

    def test_fade_in_uses_t0(self):
        f = _api.ProcessWorker._build_audio_filters(
            {'fade_in': True, 'fade_in_d': 2.0}, 5.0, 0.0, 1.0)
        assert f == ["afade=t=in:st=5.000:d=2.0"]

    def test_fade_out_position(self):
        # st = max(0, t0 + dur - d) = 3 + 10 - 1.5 = 11.5
        f = _api.ProcessWorker._build_audio_filters(
            {'fade': True, 'fade_d': 1.5}, 3.0, 10.0, 1.0)
        assert f == ["afade=t=out:st=11.500:d=1.5"]

    def test_fade_out_clamped_nonnegative(self):
        f = _api.ProcessWorker._build_audio_filters(
            {'fade': True, 'fade_d': 100.0}, 0.0, 1.0, 1.0)
        assert f == ["afade=t=out:st=0.000:d=100.0"]

    def test_degrade_chain(self):
        f = _api.ProcessWorker._build_audio_filters(
            {'deg': True, 'lp': 2500, 'hp': 300, 'hz': 8000, 'u8': True,
             'deg_gain_db': 3.0}, 0.0, 0.0, 1.0)
        assert f == ["lowpass=f=2500", "highpass=f=300",
                     "aformat=sample_fmts=u8:sample_rates=8000", "volume=3.0dB"]

    def test_degrade_no_u8_no_gain(self):
        f = _api.ProcessWorker._build_audio_filters(
            {'deg': True, 'lp': 3000, 'hp': 200, 'deg_gain_db': 0.0}, 0.0, 0.0, 1.0)
        assert f == ["lowpass=f=3000", "highpass=f=200"]

    def test_speed_appends_atempo_last(self):
        f = _api.ProcessWorker._build_audio_filters(
            {'norm': True}, 0.0, 0.0, 1.5)
        assert f[0].startswith("loudnorm")
        assert f[-1] == "atempo=1.500000"

    def test_full_order_preserved(self):
        f = _api.ProcessWorker._build_audio_filters(
            {'norm': True, 'fade_in': True, 'fade': True, 'deg': True}, 0.0, 5.0, 2.0)
        kinds = [x.split('=')[0] for x in f]
        # loudnorm → afade(in) → afade(out) → lowpass → highpass → atempo
        assert kinds[0] == "loudnorm"
        assert kinds[1] == "afade" and "t=in" in f[1]
        assert kinds[2] == "afade" and "t=out" in f[2]
        assert "lowpass" in kinds and "highpass" in kinds
        assert kinds[-1] == "atempo"

    def test_normal_speed_no_atempo(self):
        f = _api.ProcessWorker._build_audio_filters({'norm': True}, 0.0, 0.0, 1.0)
        assert not any("atempo" in x for x in f)

TestBuildAudioFilters.__module__ = _api.__name__
_api.TestBuildAudioFilters = TestBuildAudioFilters

# ── ProcessWorker._scale_vf ──────────────────────────────────────────────────
class TestScaleVf:
    def test_original_returns_none(self):
        assert _api.ProcessWorker._scale_vf("Исходное") is None

    def test_empty_returns_none(self):
        assert _api.ProcessWorker._scale_vf("") is None
        assert _api.ProcessWorker._scale_vf(None) is None

    def test_wxh_builds_fitted_scale(self):
        vf = _api.ProcessWorker._scale_vf("1280x720")
        assert vf == ("scale=w='min(iw,1280)':h='min(ih,720)'"
                      ":force_original_aspect_ratio=decrease:force_divisible_by=2")

    def test_bad_wxh_falls_back(self):
        vf = _api.ProcessWorker._scale_vf("axb")
        assert vf == "scale=axb:force_divisible_by=2"

    def test_expression_without_x(self):
        vf = _api.ProcessWorker._scale_vf("iw/2:ih/2")
        assert vf == "scale=iw/2:ih/2:force_divisible_by=2"

TestScaleVf.__module__ = _api.__name__
_api.TestScaleVf = TestScaleVf

# ── ProcessWorker._af_arg ────────────────────────────────────────────────────
class TestAfArg:
    def test_layout_fix_always_last(self):
        assert _api.ProcessWorker._af_arg([]) == _api.workers.OPUS_LAYOUT_FIX

    def test_filters_then_layout_fix(self):
        arg = _api.ProcessWorker._af_arg(["loudnorm=I=-20", "afade=t=in:st=0:d=1"])
        assert arg == f"loudnorm=I=-20,afade=t=in:st=0:d=1,{_api.workers.OPUS_LAYOUT_FIX}"

    def test_trim_tail_inserts_aresample_before_layout_fix(self):
        arg = _api.ProcessWorker._af_arg(["loudnorm=I=-20"], trim_tail=True)
        assert arg == f"loudnorm=I=-20,aresample=async=1,{_api.workers.OPUS_LAYOUT_FIX}"

    def test_does_not_mutate_input(self):
        src = ["loudnorm=I=-20"]
        _api.ProcessWorker._af_arg(src, trim_tail=True)
        assert src == ["loudnorm=I=-20"]

TestAfArg.__module__ = _api.__name__
_api.TestAfArg = TestAfArg

# ── ProcessWorker._map_av_args ───────────────────────────────────────────────
class TestMapAvArgs:
    def test_keeps_audio_by_default(self):
        assert _api.ProcessWorker._map_av_args(False, "0:a?") == [
            "-map", "0:V?", "-map", "0:a?"]

    def test_selected_track(self):
        assert _api.ProcessWorker._map_av_args(False, "0:3") == [
            "-map", "0:V?", "-map", "0:3"]

    def test_remove_audio_drops_map(self):
        assert _api.ProcessWorker._map_av_args(True, "0:3") == ["-map", "0:V?"]

TestMapAvArgs.__module__ = _api.__name__
_api.TestMapAvArgs = TestMapAvArgs

# ── ProcessWorker._fps_args ──────────────────────────────────────────────────
class TestFpsArgs:
    def test_original_is_noop(self):
        assert _api.ProcessWorker._fps_args("Исходный", "x.mp4") == []

    def test_max30_caps_fast_source(self, monkeypatch):
        monkeypatch.setattr(_api.workers, "get_fps_float", lambda p: 60.0)
        assert _api.ProcessWorker._fps_args("Исходный (max 30)", "x.mp4") == ["-r", "30"]

    def test_max30_leaves_slow_source(self, monkeypatch):
        monkeypatch.setattr(_api.workers, "get_fps_float", lambda p: 24.0)
        assert _api.ProcessWorker._fps_args("Исходный (max 30)", "x.mp4") == []

    def test_max30_probe_failure_is_noop(self, monkeypatch):
        def boom(p): raise OSError("ffprobe умер")
        monkeypatch.setattr(_api.workers, "get_fps_float", boom)
        assert _api.ProcessWorker._fps_args("Исходный (max 30)", "x.mp4") == []

    def test_numeric_value(self):
        assert _api.ProcessWorker._fps_args("30", "x.mp4") == ["-r", "30"]

    def test_non_numeric_ignored(self):
        assert _api.ProcessWorker._fps_args("мусор", "x.mp4") == []

TestFpsArgs.__module__ = _api.__name__
_api.TestFpsArgs = TestFpsArgs
