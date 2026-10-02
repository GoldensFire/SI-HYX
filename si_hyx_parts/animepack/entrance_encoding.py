# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Кодирование появления с ограничением параллельных задач генератора."""
import animepack as _api
from image_entrance_encoding import EntranceEncoder
from .generation_runtime import encoding_operation


def _encoder(generator):
    settings = generator.s
    return EntranceEncoder(
        folder=generator.folder, ffmpeg=_api.FFMPEG, ffprobe=_api.FFPROBE,
        run=generator._run_killable, capture=generator._run_capture,
        stopped=generator.stopped, fps=settings.entrance_fps,
        seconds=settings.entrance_seconds, strength=settings.entrance_strength,
        preset=settings.entrance_preset, crf=settings.video_crf,
        max_height=_api.PIXEL_HEIGHT, tune=_api.VIDEO_TUNE)


@encoding_operation
def encode_image(generator, source, output, effect, seed, seconds):
    return _encoder(generator).encode_image(source, output, effect, seed, seconds)


@encoding_operation
def encode_video(generator, source, output, effect, seed):
    return _encoder(generator).encode_video(source, output, effect, seed)
