# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""strip_default_tag. Public namespace: config."""
import config as _api


def strip_default_tag(s):
    """Убирает пометку ' (по умолчанию)' из текста пункта списка."""
    if isinstance(s, str):
        return s.replace(_api.DEFAULT_TAG, "").strip()
    return s

strip_default_tag.__module__ = _api.__name__
_api.strip_default_tag = strip_default_tag
