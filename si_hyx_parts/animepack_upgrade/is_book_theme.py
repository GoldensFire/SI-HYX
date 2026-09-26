# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""is_book_theme. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


def is_book_theme(name) -> bool:
    """Спрашивают ли в этой теме мангу, манхву или ранобэ."""
    return bool(_api._RE_BOOK_THEME.search(str(name or "")))

is_book_theme.__module__ = _api.__name__
_api.is_book_theme = is_book_theme
