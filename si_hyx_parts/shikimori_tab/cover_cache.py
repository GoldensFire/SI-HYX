# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Дисковый кэш обложек. Public namespace: shikimori_tab."""
import shikimori_tab as _api


def _cover_cache_path(anime_id: int) -> str:
    return _api.os.path.join(_api._COVERS_CACHE_DIR, f"{int(anime_id)}.jpg") if _api._COVERS_CACHE_DIR else ""

_cover_cache_path.__module__ = _api.__name__
_api._cover_cache_path = _cover_cache_path


def _load_cover_from_disk(anime_id: int) -> '_api.Optional[_api.QPixmap]':
    """Синхронно читает обложку из дискового кеша (маленький файл, уже
    уменьшенный до _THUMB_W×_THUMB_H — читать быстро, сети не требует)."""
    path = _api._cover_cache_path(anime_id)
    if not path or not _api.os.path.isfile(path):
        return None
    pm = _api.QPixmap(path)
    return pm if not pm.isNull() else None

_load_cover_from_disk.__module__ = _api.__name__
_api._load_cover_from_disk = _load_cover_from_disk


def _save_cover_to_disk(anime_id: int, pm: '_api.QPixmap'):
    """Атомарно сохраняет уже уменьшенную обложку на диск (JPEG — постеры без
    альфы, компактнее PNG)."""
    if not _api._COVERS_CACHE_DIR:
        return
    try:
        _api.os.makedirs(_api._COVERS_CACHE_DIR, exist_ok=True)
        path = _api._cover_cache_path(anime_id)
        tmp = path + ".tmp"
        if not pm.save(tmp, "JPG", 85):
            return
        _api.os.replace(tmp, path)
    except Exception:
        pass

_save_cover_to_disk.__module__ = _api.__name__
_api._save_cover_to_disk = _save_cover_to_disk


def _prune_covers_cache():
    """Если файлов накопилось больше _COVERS_CACHE_MAX — удаляет самые старые
    (по времени изменения), чтобы кеш обложек не рос бесконечно."""
    if not _api._COVERS_CACHE_DIR or not _api.os.path.isdir(_api._COVERS_CACHE_DIR):
        return
    try:
        names = [f for f in _api.os.listdir(_api._COVERS_CACHE_DIR) if f.endswith(".jpg")]
        if len(names) <= _api._COVERS_CACHE_MAX:
            return
        paths = [_api.os.path.join(_api._COVERS_CACHE_DIR, n) for n in names]
        paths.sort(key=lambda p: _api.os.path.getmtime(p))
        for p in paths[:len(paths) - _api._COVERS_CACHE_MAX]:
            try:
                _api.os.remove(p)
            except OSError:
                pass
    except Exception:
        pass

_prune_covers_cache.__module__ = _api.__name__
_api._prune_covers_cache = _prune_covers_cache
