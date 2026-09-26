# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""TestAvifEncodeCmd. Public namespace: test_workers_helpers."""
import test_workers_helpers as _api


# ── ProcessWorker._avif_encode_cmd ───────────────────────────────────────────
class TestAvifEncodeCmd:
    def _cmd(self, **kw):
        args = dict(src="in.png", tmp_out="out.avif", crf_val=30, scale_vf=None,
                    has_alpha=False, pix_fmt="yuv420p10le", aspd=4)
        args.update(kw)
        return _api.ProcessWorker._avif_encode_cmd(**args)

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

TestAvifEncodeCmd.__module__ = _api.__name__
_api.TestAvifEncodeCmd = TestAvifEncodeCmd

# ── ProcessWorker._avif_downscale_side ───────────────────────────────────────
class TestAvifDownscaleSide:
    def test_halving_bytes_scales_side_by_sqrt(self):
        # нужна половина байт → примерно 1/√2 стороны (с запасом 2% по площади)
        side = _api.ProcessWorker._avif_downscale_side(4000, 3000, baseline_kb=1000,
                                                  limit_kb=500)
        assert 2780 <= side <= 2840

    def test_always_shrinks_even_if_baseline_fits(self):
        # Доля площади клампится к 1.0, но запас 0.98 всё равно срезает ~1%
        # стороны — проба никогда не повторяет предыдущую один в один.
        side = _api.ProcessWorker._avif_downscale_side(1000, 800, baseline_kb=100,
                                                  limit_kb=5000)
        assert side == 989

    def test_tiny_image_hits_the_ten_percent_guard(self):
        # На совсем мелких сторонах усечение int() съедает весь запас 0.98 →
        # срабатывает явный откат «уменьшить на 10%».
        assert _api.ProcessWorker._avif_downscale_side(10, 8, baseline_kb=100,
                                                  limit_kb=5000) == 9

    def test_ratio_floor_prevents_zero_side(self):
        side = _api.ProcessWorker._avif_downscale_side(4000, 3000, baseline_kb=10 ** 6,
                                                  limit_kb=1)
        assert side >= 1

    def test_zero_baseline_falls_back_to_half(self):
        side = _api.ProcessWorker._avif_downscale_side(1000, 1000, baseline_kb=0,
                                                  limit_kb=100)
        assert 690 <= side <= 710

TestAvifDownscaleSide.__module__ = _api.__name__
_api.TestAvifDownscaleSide = TestAvifDownscaleSide

# ── Обрезка чёрных полос ─────────────────────────────────────────────────────
class TestCropFromCounts:
    """`_crop_from_counts` получает число ЯРКИХ пикселей в каждой строке и
    столбце кадра (максимум по просмотренным кадрам) и возвращает рамку.

    Числа в тестах — с реального файла пользователя (запись экрана 1920×1080 с
    полосами по 96 px и панелью задач внизу), на котором ffmpeg cropdetect
    срезал 18 строк панели: он смотрит на СРЕДНЮЮ яркость линии, а строка
    «чёрная везде, кроме мелкого яркого элемента» для него полоса."""

    W, H = 1920, 1080

    def _counts(self, bars_left=96, bars_right=96, bottom_rows=(), top_rows=()):
        """Столбцы: чёрные полосы по бокам. Строки: содержимое всюду, кроме
        указанных чёрных строк снизу/сверху."""
        cols = [0] * self.W
        for x in range(bars_left, self.W - bars_right):
            cols[x] = 1027
        rows = [1728] * self.H
        for y in bottom_rows:
            rows[y] = 0
        for y in top_rows:
            rows[y] = 0
        return rows, cols

    def test_pillarbox_only(self):
        rows, cols = self._counts()
        assert _api.ProcessWorker._crop_from_counts(rows, cols, self.W, self.H) == \
            (1728, 1080, 96, 0)

    def test_dim_taskbar_row_survives(self):
        """Панель задач: в строке всего 18 ярких пикселей из 1920, но это
        содержимое — резать её нельзя (порог шума = 0.5% длины, т.е. 9)."""
        rows, cols = self._counts(bottom_rows=(1077, 1078, 1079))
        rows[1076] = 18
        w, h, x, y = _api.ProcessWorker._crop_from_counts(rows, cols, self.W, self.H)
        assert (w, x, y) == (1728, 96, 0)
        assert h == 1078          # 1077 строк содержимого + чётность наружу
        assert h > 1062           # ровно то, что срезал cropdetect

    def test_a_few_noisy_pixels_do_not_cancel_the_bar(self):
        """В сжатом видео полосы не идеально чёрные (звон у края содержимого) —
        единичные засветки не должны отменять обрезку."""
        rows, cols = self._counts()
        cols[0] = 2
        cols[self.W - 1] = 4
        cols[self.W - 2] = 5
        assert _api.ProcessWorker._crop_from_counts(rows, cols, self.W, self.H) == \
            (1728, 1080, 96, 0)

    def test_letterbox(self):
        rows = [0] * self.H
        for y in range(140, 940):
            rows[y] = 1900
        cols = [1000] * self.W
        assert _api.ProcessWorker._crop_from_counts(rows, cols, self.W, self.H) == \
            (1920, 800, 0, 140)

    def test_no_bars_returns_none(self):
        rows, cols = self._counts(bars_left=0, bars_right=0)
        assert _api.ProcessWorker._crop_from_counts(rows, cols, self.W, self.H) is None

    def test_one_pixel_bar_is_not_worth_cropping(self):
        """Рамка совпала с кадром с точностью до 2 px — обрезать нечего."""
        rows, cols = self._counts(bars_left=1, bars_right=1)
        assert _api.ProcessWorker._crop_from_counts(rows, cols, self.W, self.H) is None

    def test_fully_black_sample_is_not_cropped(self):
        """Затемнение/пустая сцена: обрезать «во всё чёрное» нельзя."""
        assert _api.ProcessWorker._crop_from_counts([0] * self.H, [0] * self.W,
                                               self.W, self.H) is None

    def test_offsets_are_even_and_never_cut_content(self):
        """Смещение округляется к меньшему чётному, размер — к большему: yuv420
        требует чётности, но содержимое от этого страдать не должно."""
        rows = [0] * self.H
        for y in range(101, 1000):
            rows[y] = 1900
        cols = [0] * self.W
        for x in range(97, 1800):
            cols[x] = 1000
        w, h, x, y = _api.ProcessWorker._crop_from_counts(rows, cols, self.W, self.H)
        assert (x, y) == (96, 100)             # содержимое с 97 и 101 — внутри
        assert x + w >= 1800 and y + h >= 1000  # правый/нижний край тоже внутри
        assert w % 2 == 0 and h % 2 == 0

TestCropFromCounts.__module__ = _api.__name__
_api.TestCropFromCounts = TestCropFromCounts

# ── ProcessWorker.process_media: настройки видео в ОБОИХ профилях ────────────
class TestProcessMediaProfiles:
    """Регресс: настройка FPS обязана попадать в команду кодирования и в
    «Стандартном» профиле, и в «Тёмных сценах». Раньше `-r` дописывался только
    к команде стандартного профиля, и с preset_mode='dark' 60-кадровый источник
    выходил как 60 fps при выбранном «Исходный (max 30)»."""

    class _Fake:
        """Замена ProcessWorker: перехватывает команды ffmpeg, ничего не считая."""
        stop_flag = False
        svt_available = True
        removed_ids = ()

        class _Sig:
            def emit(self, *a, **k): pass

        def __init__(self, settings):
            self.settings = settings
            self.cmds = []
            self.log = self._Sig()
            for name in ("update_lufs_sig", "update_item_sig", "update_dur_sig",
                         "xpsnr_sig"):
                setattr(self, name, self._Sig())

        # Чистые статики берём настоящие — их логика и проверяется.
        _sanitize_name = staticmethod(_api.ProcessWorker._sanitize_name)
        _trim_seek_args = staticmethod(_api.ProcessWorker._trim_seek_args)
        _out_suffix = staticmethod(_api.ProcessWorker._out_suffix)
        _build_audio_filters = staticmethod(_api.ProcessWorker._build_audio_filters)
        _af_arg = staticmethod(_api.ProcessWorker._af_arg)
        _map_av_args = staticmethod(_api.ProcessWorker._map_av_args)
        _fps_args = staticmethod(_api.ProcessWorker._fps_args)
        _choose_pix_fmt = staticmethod(_api.ProcessWorker._choose_pix_fmt)
        _av1_encoder_args = staticmethod(_api.ProcessWorker._av1_encoder_args)
        _wants_metric_score = staticmethod(_api.ProcessWorker._wants_metric_score)

        def _out_dir_for(self, path): return "out"
        def _source_has_alpha(self, path): return False
        def _bt709_color_args(self, path): return []
        def _build_video_filters(self, *a, **k): return []
        def _overlay_vf(self, vf_list, item, current_input): return ""
        def _make_metric_sample(self, ci, trim, **k): return ci, None
        def _resolve_crf(self, item, sv, crf, *a, **k): return crf
        def _estimate_total_frames(self, *a, **k): return 0
        def get_target_bitrate_str(self, path, sel): return "160k"
        def measure_loudness(self, *a, **k): return -20.0

        def run_ffmpeg_capture(self, cmd, *a, **k):
            self.cmds.append(list(cmd))

    def _run(self, monkeypatch, preset_mode, fps_sel="Исходный (max 30)"):
        settings = {
            'video': {'enabled': True, 'speed': 100, 'crf': 40, 'pre': 1,
                      'res': '1280x720', 'fps': fps_sel,
                      'preset_mode': preset_mode, 'metric': 'none'},
            'audio': {'remove': False, 'norm': True, 'fade': True, 'bitrate': '160'},
        }
        fake = self._Fake(settings)
        monkeypatch.setattr(_api.workers, "get_video_codec", lambda p: "h264")
        monkeypatch.setattr(_api.workers, "get_video_codec_label", lambda p: "AV1")
        monkeypatch.setattr(_api.workers, "get_media_info",
                            lambda p: (10.0, "1000k", None, "160k", "opus"))
        monkeypatch.setattr(_api.workers, "get_fps_float", lambda p: 59.94)
        monkeypatch.setattr(_api.workers, "human_size", lambda n: "1 МБ")
        monkeypatch.setattr(_api.workers, "fmt_bitrate_with_codec", lambda c, b: "opus 160k")
        monkeypatch.setattr(_api.workers.os.path, "exists", lambda p: True)
        monkeypatch.setattr(_api.workers.os.path, "getsize", lambda p: 1_000_000)
        item = {'iid': 'x', 'path': 'src.mp4', 'dur': 10.0}
        _api.ProcessWorker.process_media(fake, item, lambda *a, **k: None)
        # Команда кодирования — единственная, что дошла до ffmpeg.
        assert len(fake.cmds) == 1
        return fake.cmds[0]

    def test_std_profile_applies_fps(self, monkeypatch):
        cmd = self._run(monkeypatch, "std")
        assert "-r" in cmd and cmd[cmd.index("-r") + 1] == "30"

    def test_dark_profile_applies_fps(self, monkeypatch):
        cmd = self._run(monkeypatch, "dark")
        assert "-r" in cmd and cmd[cmd.index("-r") + 1] == "30"

    def test_dark_profile_original_fps_untouched(self, monkeypatch):
        cmd = self._run(monkeypatch, "dark", fps_sel="Исходный")
        assert "-r" not in cmd

TestProcessMediaProfiles.__module__ = _api.__name__
_api.TestProcessMediaProfiles = TestProcessMediaProfiles
