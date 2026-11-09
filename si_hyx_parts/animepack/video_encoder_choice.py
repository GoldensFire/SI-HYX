# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Чем кодировать видео пака в этом прогоне: AV1 видеокарты или SVT-AV1."""
from __future__ import annotations

import animepack as _api
import gpu_video_encoder


def choose_video_encoder(generator):
    """Выбирает кодировщик один раз на прогон и пишет выбор в журнал.

    Результат — `generator._gpu_video`: GpuEncoder (только AV1) или None
    (SVT-AV1 на процессоре). Его читают все места, где пак кодирует видео
    (video_encode_args, pixel_encode_args, ролики появления)."""
    mode = str(getattr(generator.s, "video_encoder", "auto") or "auto")
    crf = generator.s.video_crf
    try:
        gpu = gpu_video_encoder.pick(mode, _api.FFMPEG)
    except Exception as exc:  # noqa: BLE001 — выбор не должен ронять прогон
        gpu = None
        generator.log(f"Видео: видеокарту проверить не удалось ({exc}) — "
                      f"кодирую процессором (SVT-AV1, CRF {crf}).")
    else:
        if gpu is not None:
            where = f" {gpu.adapter}" if gpu.adapter else ""
            generator.log(f"Видео: AV1 на видеокарте{where} ({gpu.name}, "
                          f"качество ≈ CRF {crf} SVT-AV1).")
        elif mode != "cpu":
            generator.log("Видео: видеокарта не кодирует AV1 — кодирую "
                          f"процессором (SVT-AV1, CRF {crf}).")
    generator._gpu_video = gpu
    return gpu
