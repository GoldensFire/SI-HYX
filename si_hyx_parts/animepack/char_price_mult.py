# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""char_price_mult. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


def char_price_mult(cand) -> float:
    """Во сколько раз вопрос-персонаж дороже вопроса о самом тайтле."""
    if getattr(cand, "kind", "") != _api.CHAR_KIND:
        return 1.0
    main = bool((getattr(cand, "character", None) or {}).get("main"))
    return _api._CHAR_PRICE_MULT[main]

char_price_mult.__module__ = _api.__name__
_api.char_price_mult = char_price_mult
