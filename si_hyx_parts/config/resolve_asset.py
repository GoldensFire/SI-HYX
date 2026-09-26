# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_resolve_asset. Public namespace: config."""
import config as _api


def _resolve_asset(name):
    """Ищет файл-ресурс (иконку и т.п.) рядом с программой.
    Порядок: _MEIPASS (PyInstaller) → папка exe/скрипта → их подпапка bin.
    Возвращает абсолютный путь или None, если не найден."""
    roots = []
    base = getattr(_api.sys, "_MEIPASS", None)
    if base:
        roots.append(base)
    roots.append(_api.os.path.dirname(_api.os.path.abspath(_api.sys.argv[0] or ".")))
    roots.append(_api.os.path.dirname(_api.os.path.abspath(_api.__file__)))
    for r in roots:
        for cand in (_api.os.path.join(r, name), _api.os.path.join(r, "bin", name)):
            if _api.os.path.isfile(cand):
                return cand
    return None

_resolve_asset.__module__ = _api.__name__
_api._resolve_asset = _resolve_asset
