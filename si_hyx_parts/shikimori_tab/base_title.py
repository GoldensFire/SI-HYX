# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_base_title. Public namespace: shikimori_tab."""
import shikimori_tab as _api


def _base_title(s: str) -> str:
    """«Базовое» название без хвостовых сезонных маркеров (для сопоставления
    разных сезонов одного тайтла). Применяет _SEASON_TAIL_RX многократно:
    «ванпанчмен 3» → «ванпанчмен», «attack on titan final season» → «attack on
    titan». Пустой результат не отдаём (возвращаем последнюю непустую форму)."""
    s = _api._norm_title(s)
    prev = None
    while s and s != prev:
        prev = s
        stripped = _api._SEASON_TAIL_RX.sub("", s).strip(" :.-–—")
        if not stripped:
            break
        s = stripped
    return s

_base_title.__module__ = _api.__name__
_api._base_title = _base_title
