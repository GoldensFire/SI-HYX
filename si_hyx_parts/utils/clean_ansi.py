# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""clean_ansi. Public namespace: utils."""
import utils as _api


def clean_ansi(text: str) -> str:
    return _api._RE_ANSI.sub('', text)

clean_ansi.__module__ = _api.__name__
_api.clean_ansi = clean_ansi
