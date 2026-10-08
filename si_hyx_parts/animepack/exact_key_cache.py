# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Отпечатки вопросов прежних паков без повторного разбора архивов.

Каждая генерация читала все 85 выбранных .siq заново (14 603 отпечатка).
Ключ записи — путь, размер, время изменения и версия алгоритма (хеш исходников
разбора): изменился архив или правила — он читается снова, остальные берутся
из кэша. Пустой результат не запоминается: им же кончается и сбой чтения.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import animepack as _api

FILE_NAME = "animepack_exact_keys.json"
_VERSION = None


def version() -> str:
    """Меняется вместе с исходниками разбора отпечатков."""
    global _VERSION
    if _VERSION is None:
        sha = hashlib.sha256(b"exact-keys-v1")
        here = Path(__file__).resolve().parent
        for name in ("exact_repeat.py", "character_repeat.py"):
            try:
                sha.update((here / name).read_bytes())
            except OSError:
                sha.update(name.encode())
        _VERSION = sha.hexdigest()[:16]
    return _VERSION


def _tuple(value):
    return tuple(_tuple(item) for item in value) if isinstance(value, list) else value


def _path() -> str:
    return os.path.join(os.path.dirname(_api.SHIKI_CACHE_FILE), FILE_NAME)


def _stamp(path: str):
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return [stat.st_size, stat.st_mtime_ns]


def read_all(paths, reader, skip=lambda path: False, stopped=lambda: False):
    """{путь: отпечатки} выбранных паков; новые и изменённые читает reader."""
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    files = data.get("files") if data.get("version") == version() else None
    files = files if isinstance(files, dict) else {}
    out, fresh, changed = {}, {}, False
    for path in paths:
        if stopped():
            break
        if skip(path):
            continue
        key = os.path.normcase(os.path.abspath(path))
        stamp = _stamp(path)
        row = files.get(key)
        if stamp and isinstance(row, dict) and row.get("stamp") == stamp:
            keys = {_tuple(item) for item in row.get("keys") or ()}
        else:
            keys = reader(path)
            changed = True
        out[path] = keys
        if stamp and keys:
            fresh[key] = {"stamp": stamp, "keys": [list(k) for k in keys]}
    if not stopped() and (changed or set(fresh) != set(files)):
        tmp = _path() + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"version": version(), "files": fresh}, f, ensure_ascii=False)
            os.replace(tmp, _path())
        except (OSError, TypeError):
            pass
    return out
