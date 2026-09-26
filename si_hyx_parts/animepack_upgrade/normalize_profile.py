# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""normalize_profile. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


def normalize_profile(value) -> str:
    """Имя профиля из настроек (в том числе старое «movie», мусор) → всегда
    PROFILE_ANIME — другого профиля больше нет."""
    key = str(value or "").strip().lower()
    return key if key in _api.PROFILES else _api.PROFILE_ANIME

normalize_profile.__module__ = _api.__name__
_api.normalize_profile = normalize_profile
