# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_resolve_tool. Public namespace: config."""
import config as _api


def _resolve_tool(name):
    """Ищет ffmpeg/ffprobe рядом с программой (для сборки в .exe с bundled-ffmpeg).
    Порядок: _MEIPASS (PyInstaller) → папка exe/скрипта → подпапка bin → PATH.
    Если ничего не найдено — возвращает имя для поиска в системном PATH.
    """
    exe = name + (".exe" if _api.IS_WIN else "")
    roots = []
    base = getattr(_api.sys, "_MEIPASS", None)        # распакованные данные PyInstaller
    if base:
        roots.append(base)
    roots.append(_api.os.path.dirname(_api.os.path.abspath(_api.sys.argv[0] or ".")))  # папка exe
    roots.append(_api.os.path.dirname(_api.os.path.abspath(_api.__file__)))            # папка скрипта
    for r in roots:
        for cand in (_api.os.path.join(r, exe), _api.os.path.join(r, "bin", exe)):
            if _api.os.path.isfile(cand):
                return cand
    return name  # из системного PATH

_resolve_tool.__module__ = _api.__name__
_api._resolve_tool = _resolve_tool
