# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_is_attached_pic. Public namespace: edit_tab."""
import edit_tab as _api


def _is_attached_pic(stream):
    """True, если поток ffprobe — ОБЛОЖКА (attached_pic), а не видеоряд.

    Обложка альбома в mp3/flac/m4a лежит в контейнере как «видеопоток» (mjpeg
    1000×1000, r_frame_rate 90000/1) из одного кадра. Принимать её за видео
    нельзя: fps 90000 давал сетку кадров на 20 млн кадров, покадровый декодер
    гонял ffmpeg вхолостую (после -ss обложка не выдаётся вовсе), а метка
    времени начинала жить по «часам кадра», которых у такого файла нет. Плюс
    сам QtMultimedia обложку видеорядом НЕ считает (hasVideo=False) — то есть
    вкладка считала иначе, чем её собственный плеер. Такой файл — чистое аудио."""
    try:
        if int((stream.get('disposition') or {}).get('attached_pic', 0) or 0):
            return True
    except Exception:
        pass
    return False

_is_attached_pic.__module__ = _api.__name__
_api._is_attached_pic = _is_attached_pic
