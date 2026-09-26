# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""has_cjk. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


def has_cjk(text) -> bool:
    """Есть ли в строке иероглифы/кана/хангыль."""
    return bool(_api._RE_CJK.search(str(text or "")))

has_cjk.__module__ = _api.__name__
_api.has_cjk = has_cjk
