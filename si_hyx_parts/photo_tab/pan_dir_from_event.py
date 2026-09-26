# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_pan_dir_from_event. Public namespace: photo_tab."""
import photo_tab as _api


def _pan_dir_from_event(ev):
    """(sx, sy) для пана по WASD/стрелкам или None. Стрелки — по ev.key(), WASD — по
    nativeVirtualKey (любая раскладка), с фолбэком по ev.key() для латиницы."""
    d = _api._ARROW_PAN.get(ev.key())
    if d is not None:
        return d
    try:
        d = _api._WASD_VK.get(ev.nativeVirtualKey())
    except Exception:
        d = None
    if d is not None:
        return d
    return _api._WASD_KEY.get(ev.key())

_pan_dir_from_event.__module__ = _api.__name__
_api._pan_dir_from_event = _pan_dir_from_event
