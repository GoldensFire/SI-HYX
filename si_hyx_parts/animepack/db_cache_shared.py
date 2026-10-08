# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Одна разобранная база Shikimori на все экземпляры кэша с тем же файлом.

Каждый пак в очереди создаёт свой ShikimoriDbCache, и каждый заново разбирал
файл базы (около 400 МиБ) — секунды работы и паузы GIL на каждом паке. Теперь
экземпляры с одним путём делят замок и уже прочитанное содержимое; файл
перечитывается, только если его отметка (время изменения, размер) сменилась.
"""
from __future__ import annotations

import os
import threading

_LOCK = threading.Lock()
_ENTRIES: dict = {}


def entry(path: str) -> dict:
    """Общая запись для файла: замок, содержимое и его отметка."""
    key = os.path.normcase(os.path.abspath(str(path)))
    with _LOCK:
        found = _ENTRIES.get(key)
        if found is None:
            found = _ENTRIES[key] = {"lock": threading.Lock(), "save_lock": threading.Lock(),
                                     "data": None, "stamp": None}
        return found


def reuse(shared: dict, stamp):
    """Уже разобранное содержимое, если файл с тех пор не менялся (иначе None)."""
    if shared["data"] is not None and stamp is not None and shared["stamp"] == stamp:
        return shared["data"]
    return None


def publish(shared: dict, data, stamp) -> None:
    shared["data"], shared["stamp"] = data, stamp
