# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_probe_video_codec. Public namespace: widgets."""
import widgets as _api


def _probe_video_codec(path):
    """codec_name первой видеодорожки (в нижнем регистре) через ffprobe, либо
    "" при ошибке/отсутствии ffprobe."""
    try:
        r = _api.subprocess.run(
            [_api.FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name", "-of", "csv=p=0", path],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10, creationflags=_api.CREATE_NO_WINDOW)
        # csv_first, а не strip(): ffprobe оставляет хвостовой разделитель
        # («h264,»), и сравнение с 'av1' переставало срабатывать.
        return _api.csv_first(r.stdout).lower()
    except Exception:
        return ""

_probe_video_codec.__module__ = _api.__name__
_api._probe_video_codec = _probe_video_codec
