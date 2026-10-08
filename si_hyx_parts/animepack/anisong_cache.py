# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Сырые ответы AnisongDB по MAL id между генерациями.

В живом прогоне поиск кандидатов спросил AnisongDB 42 раза о 12 414 MAL id:
каждый пак заново перебирал одну и ту же базу ради последних песенных мест.
Ответы хранятся СЫРЫМИ — фильтры пака (типы песен, AMQ-сложность, «без
инструменталов») применяются при чтении, и смена фильтров кэш не портит.

Успешный пустой ответ («у тайтла песен нет») тоже ответ и запоминается;
сетевая ошибка — нет. Хранилище — SQLite рядом с кэшем каталога: десятки
мегабайт JSON переписывать целиком на каждую пачку было бы дорого.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time

import animepack as _api

FILE_NAME = "animepack_anisong.sqlite"
TTL = 3 * 86400


def _mal(song) -> int:
    try:
        return int((song.get("linked_ids") or {})["myanimelist"])
    except (KeyError, TypeError, ValueError, AttributeError):
        return 0


class CachedAnisong:
    """Обёртка над AnisongApi: songs_by_mal_ids через кэш, остальное — как есть."""

    def __init__(self, api, path: str = "", ttl: float = TTL):
        self._api = api
        self._path = path or os.path.join(os.path.dirname(_api.SHIKI_CACHE_FILE), FILE_NAME)
        self._ttl = ttl
        self._lock = threading.Lock()
        self._db = None
        # Сколько id последний вызов этого потока спросил по сети: журнал
        # пишет о запросе к AnisongDB, только когда он был на самом деле.
        self._calls = threading.local()

    def __getattr__(self, name):
        # Только для отсутствующих атрибутов; без _api (copy/pickle) — не рекурсия.
        if name.startswith("__") or name in ("_api", "_calls"):
            raise AttributeError(name)
        return getattr(self._api, name)

    def _connect(self):
        if self._db is None:
            self._db = sqlite3.connect(self._path, check_same_thread=False)
            self._db.execute("CREATE TABLE IF NOT EXISTS songs (mal INTEGER PRIMARY KEY, "
                             "fetched REAL NOT NULL, payload TEXT NOT NULL)")
        return self._db

    def _cached(self, ids: list) -> dict:
        fresh = time.time() - self._ttl
        out = {}
        try:
            with self._lock:
                db = self._connect()
                for at in range(0, len(ids), 500):
                    chunk = ids[at:at + 500]
                    marks = ",".join("?" * len(chunk))
                    rows = db.execute(f"SELECT mal, payload FROM songs WHERE fetched >= ? "
                                      f"AND mal IN ({marks})", [fresh, *chunk]).fetchall()
                    for mal, payload in rows:
                        out[int(mal)] = json.loads(payload)
        except (sqlite3.Error, ValueError):
            return {}
        return out

    def _store(self, asked: list, songs: list) -> None:
        by_mal = {mal: [] for mal in asked}
        for song in songs:
            mal = _mal(song)
            if mal in by_mal:
                by_mal[mal].append(song)
        now = time.time()
        try:
            with self._lock:
                db = self._connect()
                db.executemany("INSERT OR REPLACE INTO songs (mal, fetched, payload) VALUES (?, ?, ?)",
                               [(mal, now, json.dumps(rows, ensure_ascii=False))
                                for mal, rows in by_mal.items()])
                db.commit()
        except sqlite3.Error:
            pass

    def songs_by_mal_ids(self, ids) -> list[dict]:
        ids = [int(i) for i in ids]
        if not ids:
            return []
        known = self._cached(ids)
        missing = [mal for mal in ids if mal not in known]
        self._calls.fetched = len(missing)
        fetched = self._api.songs_by_mal_ids(missing) if missing else []
        if missing:
            self._store(missing, fetched)
        out = [song for mal in ids if mal in known for song in known[mal]]
        return out + list(fetched)

    def last_fetched(self) -> int:
        """Сколько id прошлый songs_by_mal_ids этого потока спросил по сети."""
        return int(getattr(self._calls, "fetched", 0))

    def songs_by_name_artist_snapshot(self, name: str) -> list[dict]:
        """Сохранённые строки с тем же названием песни (любого возраста).

        Ответ, когда поиск AnisongDB отвечает 503: точное совпадение
        исполнителя проверяет вызывающий."""
        # SQLite lower() folds only ASCII — same rule on both sides.
        needle = json.dumps(str(name), ensure_ascii=False)
        try:
            with self._lock:
                rows = self._connect().execute(
                    "SELECT payload FROM songs WHERE instr(lower(payload), lower(?)) > 0",
                    [needle]).fetchall()
        except sqlite3.Error:
            return []
        wanted = str(name).casefold()
        out = []
        for (payload,) in rows:
            try:
                songs = json.loads(payload)
            except ValueError:
                continue
            out += [song for song in songs if isinstance(song, dict)
                    and str(song.get("songName") or "").casefold() == wanted]
        return out

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None
