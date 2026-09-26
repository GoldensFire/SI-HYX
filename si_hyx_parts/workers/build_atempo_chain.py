# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_build_atempo_chain. Public namespace: workers."""
import workers as _api


def _build_atempo_chain(speed_factor: float) -> list:
    """Строит цепочку atempo-фильтров для FFmpeg.
    FFmpeg ограничивает atempo диапазоном [0.5, 2.0], поэтому
    большие/малые значения разбиваются на несколько звеньев.
    """
    chain = []
    t = speed_factor
    while t > 2.0:
        chain.append("atempo=2.0")
        t /= 2.0
    while t < 0.5:
        chain.append("atempo=0.5")
        t *= 2.0
    if abs(t - 1.0) > 0.001:
        chain.append(f"atempo={t:.6f}")
    return chain

_build_atempo_chain.__module__ = _api.__name__
_api._build_atempo_chain = _build_atempo_chain

class _ImgRunnable(_api.QRunnable):
    """Обёртка для параллельной обработки одного изображения в QThreadPool.
    Потоки QThreadPool — настоящие потоки Qt: эмит сигналов из них безопасен,
    а очистка корректна (в отличие от обычных threading.Thread)."""
    def __init__(self, worker, item, start):
        super().__init__()
        self.worker = worker
        self.item = item
        self.start = start

    def run(self):
        try:
            self.worker._process_item(self.item, False, self.start)
        except Exception:
            pass

_ImgRunnable.__module__ = _api.__name__
_api._ImgRunnable = _ImgRunnable

class ProcessWorker(_api.QThread):
    progress = _api.pyqtSignal(str, int)
    status = _api.pyqtSignal(str, str, str)
    log = _api.pyqtSignal(str)
    global_progress = _api.pyqtSignal(int, str)
    finished_all = _api.pyqtSignal()
    update_item_sig = _api.pyqtSignal(str, str, str)
    update_lufs_sig = _api.pyqtSignal(str, object, object)
    update_dur_sig = _api.pyqtSignal(str, str)   # iid, длительность итогового файла (сек, строкой)
    active_threads = _api.pyqtSignal(int, int)  # (активных воркеров, максимум) — счётчик в UI
    xpsnr_sig = _api.pyqtSignal(str, object)     # iid, оценка XPSNR в дБ (float) | None

    # Нижняя граница preset для пробных кодирований в _metric_crf_search —
    # не даём поиску унаследовать очень медленный (0-4) preset финального
    # кодирования, иначе один пробный энкод 1080p может идти минутами.
    _SEARCH_PRESET_FLOOR = 6

    from si_hyx_parts.workers.process_worker___init import __init__

    _AI_BRANDS = ('gemini', 'chatgpt')
    _RAND_CHARS = 'abcdefghijklmnopqrstuvwxyz0123456789'

    from si_hyx_parts.workers.process_worker__sanitize_name import (
        _sanitize_name,
        stop,
        measure_loudness,
        _priority_creationflag,
        _inc_active,
        _dec_active,
        _out_dir_for,
        _source_has_alpha,
        _bt709_color_args,
    )

    # ── Обрезка чёрных полос ────────────────────────────────────────────────
    # Ярче этого (0..255) пиксель уже не «чёрный»: в сжатом видео полосы не
    # идеально нулевые.
    _CROP_LUMA_LIMIT = 24
    # Сколько ярких пикселей в линии списываем на шум — доля её длины (0.5%, но
    # не меньше 4 пикселей): полосы в сжатом видео звенят у края содержимого, и
    # пара засветок не должна отменять обрезку целой полосы. Выше поднимать
    # нельзя — у реальной «тонкой» строки содержимого (край панели задач) ярких
    # пикселей было 18 из 1920, то есть меньше процента. Именно этим детект и
    # отличается от cropdetect: тот считает СРЕДНЮЮ яркость линии, поэтому
    # строка, чёрная везде, кроме мелкого яркого элемента, для него «чёрная».
    _CROP_NOISE_SHARE = 0.005
    _CROP_NOISE_MIN = 4
    _CROP_WINDOW_SEC = 12.0     # длина анализируемого отрезка
    _CROP_SAMPLE_BYTES = 40_000_000   # сколько памяти отдаём под кадры выборки

    from si_hyx_parts.workers.process_worker__crop_from_counts import (
        _crop_from_counts,
        _detect_crop,
        _choose_pix_fmt,
        _target_dims,
    )

    # pix_fmt для AVIF (всегда 10-бит; при альфе цвет идёт yuva420p10le, а сама
    # альфа выносится alphaextract'ом отдельным потоком) — общий с avif_fit.
    _avif_pix_fmt = staticmethod(_api.avif_pix_fmt)

    from si_hyx_parts.workers.process_worker__av1_encoder_args import (
        _av1_encoder_args,
        _measure_metric,
        _short_sample,
        _measure_at_crf,
        _run_killable,
        _metric_crf_search,
    )

    from si_hyx_parts.workers.process_worker_run_ffmpeg_capture import (
        run_ffmpeg_capture,
        _estimate_total_frames,
        get_target_bitrate_str,
        _trim_seek_args,
        _out_suffix,
        _build_audio_filters,
        _scale_vf,
    )

    from si_hyx_parts.workers.process_worker__af_arg import (
        _af_arg,
        _map_av_args,
        _fps_args,
        _build_video_filters,
        _overlay_vf,
        _make_metric_sample,
        _wants_metric_score,
        _resolve_crf,
    )

    from si_hyx_parts.workers.process_worker_process_media import process_media

    from si_hyx_parts.workers.process_worker__search_quality_under_limit import (
        _search_quality_under_limit,
        _convert_simple_image,
    )

    # Команда кодирования и оценка даунскейла живут в avif_fit — тем же кодом
    # пользуется генератор аниме-паков, чтобы флаги libaom не разъезжались.
    _avif_encode_cmd = staticmethod(_api.avif_encode_cmd)

    from si_hyx_parts.workers.process_worker__avif_prepare_input import _avif_prepare_input

    _avif_downscale_side = staticmethod(_api.downscale_side)

    from si_hyx_parts.workers.process_worker_process_avif import process_avif

    from si_hyx_parts.workers.process_worker__fmt_eta import (
        _fmt_eta,
        _fmt_eta_rate,
        _guess_out_path,
        _overwrite_source_if_needed,
        _total_now,
        _process_item,
        run,
    )

ProcessWorker.__module__ = _api.__name__
_api.ProcessWorker = ProcessWorker
