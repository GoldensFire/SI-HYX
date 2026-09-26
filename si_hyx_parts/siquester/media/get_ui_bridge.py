# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_get_ui_bridge. Public namespace: siquester.media."""
import siquester.media as _api


def _get_ui_bridge() -> '_api._ThreadBridge':
    pass  # Shared state is addressed through _api.
    if _api._UI_BRIDGE is None:
        _api._UI_BRIDGE = _api._ThreadBridge()
    return _api._UI_BRIDGE

_get_ui_bridge.__module__ = _api.__name__
_api._get_ui_bridge = _get_ui_bridge
