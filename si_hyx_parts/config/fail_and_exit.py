# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""fail_and_exit. Public namespace: config."""
import config as _api


# Аппаратное декодирование видео в QtMultimedia (бэкенд ffmpeg) настраивается
# ниже, ПОСЛЕ определения SETTINGS_FILE (нужно прочитать настройку
# video_hw_decode). См. блок «Аппаратное декодирование видео».


# PyQt6 imports
def fail_and_exit(msg, exc=None):
    print(msg)
    if exc is not None:
        _api.traceback.print_exception(type(exc), exc, exc.__traceback__)
    _api.sys.exit(1)

fail_and_exit.__module__ = _api.__name__
_api.fail_and_exit = fail_and_exit
