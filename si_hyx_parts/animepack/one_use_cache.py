# -*- coding: utf-8 -*-
"""Убирает старые копии песен и кадров из прежнего медиа-кэша."""
from __future__ import annotations

import os
import threading

_LOCK = threading.Lock()
_DONE = False
_OLD_MEDIA = {"amq-audio", "anime-frame", "cover-audio", "avif"}


def purge():
    global _DONE
    with _LOCK:
        if _DONE:
            return
        import media_cache
        import cover_cache
        import poster_cache

        for row in media_cache.entries():
            if row["namespace"] in _OLD_MEDIA:
                media_cache.remove(row["path"])
        for row in poster_cache.entries():
            if row["name"].startswith("character_"):
                poster_cache.remove(row["path"])
        # .npy — отпечатки звука для каверов; JSON хранит лишь поиск,
        # оценки и историю использованных отрывков.
        try:
            for row in os.scandir(cover_cache.CACHE_DIR):
                if row.is_file() and row.name.endswith(".npy"):
                    os.remove(row.path)
        except OSError:
            pass
        _DONE = True
