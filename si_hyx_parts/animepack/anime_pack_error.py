# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackError. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


class AnimePackError(Exception):
    """Ошибка генерации, которую не стыдно показать пользователю."""

AnimePackError.__module__ = _api.__name__
_api.AnimePackError = AnimePackError
