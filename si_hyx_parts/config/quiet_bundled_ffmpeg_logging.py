# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_quiet_bundled_ffmpeg_logging. Public namespace: config."""
import config as _api


# Раз аппаратный AV1-декодер отсутствует на многих GPU (см. коммент выше),
# FFmpeg-бэкенд QtMultimedia на КАЖДЫЙ кадр AV1 пишет в консоль "Failed setup
# for format d3d11: hwaccel initialisation returned error" (сам кадр при этом
# успешно докодируется программно — это просто спам, не ошибка воспроизведения).
# ВАЖНО: это НЕ идёт через QLoggingCategory (QT_LOGGING_RULES тут бессилен) —
# это сырой av_log() из libavutil/libavcodec, который FFmpeg печатает в stderr
# напрямую. Единственный способ заглушить именно эти строки — вызвать
# av_log_set_level(AV_LOG_QUIET) в той же avutil-*.dll, что уже загружена в
# процесс вместе с Qt6Multimedia (ctypes.CDLL находит УЖЕ загруженный модуль
# по пути и просто увеличивает refcount — глобальный уровень логирования общий
# для всего процесса, включая FFmpeg-бэкенд Qt). Не трогает отдельные
# субпроцессы ffmpeg.exe (у них свой -loglevel).
def _quiet_bundled_ffmpeg_logging():
    try:
        import ctypes, glob
        import PyQt6
        bin_dir = _api.os.path.join(_api.os.path.dirname(PyQt6.__file__), "Qt6", "bin")
        dlls = glob.glob(_api.os.path.join(bin_dir, "avutil-*.dll"))
        if not dlls:
            return
        avutil = ctypes.CDLL(dlls[0])
        avutil.av_log_set_level(-8)   # AV_LOG_QUIET
    except Exception:
        pass

_quiet_bundled_ffmpeg_logging.__module__ = _api.__name__
_api._quiet_bundled_ffmpeg_logging = _quiet_bundled_ffmpeg_logging
