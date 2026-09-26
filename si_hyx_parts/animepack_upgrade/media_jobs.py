# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""media_jobs. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


def media_jobs(want: int) -> int:
    """Сколько кодирований гнать разом на ЭТОЙ машине: на двухъядерном ноутбуке
    шесть параллельных ffmpeg только толкались бы локтями."""
    return max(1, min(int(want), _api.os.cpu_count() or 1))

media_jobs.__module__ = _api.__name__
_api.media_jobs = media_jobs
