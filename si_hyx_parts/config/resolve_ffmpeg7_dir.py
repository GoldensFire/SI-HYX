# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_resolve_ffmpeg7_dir. Public namespace: config."""
import config as _api


def _resolve_ffmpeg7_dir():
    """Каталог с отдельным ffmpeg 7.x — ИСКЛЮЧИТЕЛЬНО для yt-dlp `--download-sections`.
    Основной ffmpeg в bin — 8.x, а он ломает нарезку по таймингам (внешний баг
    ffmpeg 8.1, yt-dlp issue #16546: битый/audio-only отрезок). ffmpeg 7.x режет
    секцию корректно. Кладём его в подпапку bin/ffmpeg7. Если её нет — возвращаем
    None, и нарезка откатывается на обычный ffmpeg (лучше кривой отрезок, чем краш)."""
    roots = []
    base = getattr(_api.sys, "_MEIPASS", None)
    if base:
        roots.append(base)
    roots.append(_api.os.path.dirname(_api.os.path.abspath(_api.sys.argv[0] or ".")))
    roots.append(_api.os.path.dirname(_api.os.path.abspath(_api.__file__)))
    for r in roots:
        for cand in (_api.os.path.join(r, "ffmpeg7"), _api.os.path.join(r, "bin", "ffmpeg7")):
            if _api.os.path.isfile(_api.os.path.join(cand, "ffmpeg" + (".exe" if _api.IS_WIN else ""))):
                return cand
    return None

_resolve_ffmpeg7_dir.__module__ = _api.__name__
_api._resolve_ffmpeg7_dir = _resolve_ffmpeg7_dir
