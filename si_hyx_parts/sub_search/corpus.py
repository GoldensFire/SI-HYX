# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Кэш «Поиска по сабам» (SQLite в папке настроек).

* downloads — скачанные файлы/архивы источников: итог разбора и время.
  Содержимое субтитров почти не меняется, поэтому живёт SUBS_TTL; ошибка
  сети — ERROR_TTL, после чего файл спросят снова.
* subs — реплики каждого английского файла (zlib-сжатый JSON). Хранится
  только текст диалогов: эпизод — ~5–10 КБ вместо сотен КБ исходного ASS.
  Любая новая фраза ищется по ним без сети.
* title_files — какие файлы относятся к тайтлу Shikimori (файл может
  относиться к нескольким частям, если источник не различает сезоны).
* kv — ответы API со сроком (списки файлов, сопоставления каталогов).
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import zlib

import sub_search as _api

_SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads(
  key TEXT PRIMARY KEY, source TEXT NOT NULL, url TEXT DEFAULT '', name TEXT DEFAULT '',
  status TEXT NOT NULL, note TEXT DEFAULT '', fetched REAL NOT NULL);
CREATE TABLE IF NOT EXISTS subs(
  id INTEGER PRIMARY KEY, dl_key TEXT NOT NULL, member TEXT DEFAULT '',
  episode TEXT DEFAULT '', fmt TEXT DEFAULT '', sha TEXT DEFAULT '', cues BLOB);
CREATE INDEX IF NOT EXISTS idx_subs_dl ON subs(dl_key);
CREATE TABLE IF NOT EXISTS title_files(
  shiki_id INTEGER NOT NULL, dl_key TEXT NOT NULL, PRIMARY KEY(shiki_id, dl_key));
CREATE INDEX IF NOT EXISTS idx_tf_key ON title_files(dl_key);
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT, t REAL);
"""

# Статусы файла в downloads.
OK = "ok"                 # есть английские реплики
NOT_ENGLISH = "not_en"    # разобран, но не английский/пустой
ERROR = "error"           # не скачался — спросим снова через ERROR_TTL


def pack_cues(cues) -> bytes:
    rows = [[round(c.start, 3), round(c.end, 3), c.text] for c in cues]
    return zlib.compress(json.dumps(rows, ensure_ascii=False).encode("utf-8"), 6)


def unpack_text(blob: bytes) -> str:
    """Распакованный JSON реплик — для быстрой предпроверки фразы."""
    return zlib.decompress(blob).decode("utf-8")


def cues_from_text(text: str):
    from .matcher import Cue
    return [Cue(float(s), float(e), str(t)) for s, e, t in json.loads(text)]


class Corpus:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or _api.CORPUS_FILE
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(_SCHEMA)
        self.db.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self.db.commit()
                self.db.close()
            except sqlite3.Error:
                pass

    # ── файлы ───────────────────────────────────────────────────────────────
    def fresh_download(self, key: str) -> bool:
        """Файл уже скачан и ещё не устарел (ошибка — до ERROR_TTL)."""
        with self._lock:
            row = self.db.execute("SELECT status, fetched FROM downloads WHERE key=?",
                                  (key,)).fetchone()
        if row is None:
            return False
        ttl = _api.ERROR_TTL if row[0] == ERROR else _api.SUBS_TTL
        return time.time() - float(row[1]) < ttl

    def link(self, shiki_id: int, keys) -> None:
        with self._lock:
            self.db.executemany("INSERT OR IGNORE INTO title_files VALUES(?,?)",
                                [(int(shiki_id), k) for k in keys])
            self.db.commit()

    def store(self, key: str, source: str, url: str, name: str, status: str,
              note: str, members, shiki_id: int) -> None:
        """Итог скачивания файла: members — [(member, episode, fmt, sha, cues_blob)]."""
        with self._lock:
            self.db.execute("DELETE FROM subs WHERE dl_key=?", (key,))
            self.db.execute(
                "INSERT OR REPLACE INTO downloads VALUES(?,?,?,?,?,?,?)",
                (key, source, url, name, status, note[:500], time.time()))
            self.db.executemany(
                "INSERT INTO subs(dl_key, member, episode, fmt, sha, cues) VALUES(?,?,?,?,?,?)",
                [(key, m, ep, fmt, sha, blob) for m, ep, fmt, sha, blob in members])
            self.db.execute("INSERT OR IGNORE INTO title_files VALUES(?,?)",
                            (int(shiki_id), key))
            self.db.commit()

    def subs_for(self, shiki_id: int, keys=None) -> list[tuple]:
        """[(dl_key, source, url, member, episode, sha, cues_blob)] тайтла.
        keys — только эти файлы (свежие для текущего прогона)."""
        sql = ("SELECT s.dl_key, d.source, d.url, s.member, s.episode, s.sha, s.cues "
               "FROM title_files t JOIN downloads d ON d.key = t.dl_key "
               "JOIN subs s ON s.dl_key = t.dl_key WHERE t.shiki_id=? AND d.status=? "
               "ORDER BY s.id")
        with self._lock:
            rows = self.db.execute(sql, (int(shiki_id), OK)).fetchall()
        if keys is not None:
            keys = set(keys)
            rows = [r for r in rows if r[0] in keys]
        return rows

    def subs_of_download(self, key: str) -> list[tuple]:
        sql = ("SELECT s.dl_key, d.source, d.url, s.member, s.episode, s.sha, s.cues "
               "FROM downloads d JOIN subs s ON s.dl_key = d.key WHERE d.key=? ORDER BY s.id")
        with self._lock:
            return self.db.execute(sql, (key,)).fetchall()

    def cached_titles(self) -> set[int]:
        """Тайтлы, у которых в кэше есть хоть один английский файл."""
        sql = ("SELECT DISTINCT t.shiki_id FROM title_files t JOIN downloads d "
               "ON d.key = t.dl_key WHERE d.status=?")
        with self._lock:
            return {int(r[0]) for r in self.db.execute(sql, (OK,))}

    # ── ответы API со сроком ─────────────────────────────────────────────────
    def kv_get(self, k: str, ttl: float):
        with self._lock:
            row = self.db.execute("SELECT v, t FROM kv WHERE k=?", (k,)).fetchone()
        if row is None or time.time() - float(row[1] or 0) > ttl:
            return None
        try:
            return json.loads(row[0])
        except (TypeError, ValueError):
            return None

    def kv_set(self, k: str, value) -> None:
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO kv VALUES(?,?,?)",
                            (k, json.dumps(value, ensure_ascii=False), time.time()))
            self.db.commit()

    # ── обслуживание ─────────────────────────────────────────────────────────
    def stats(self) -> dict:
        with self._lock:
            files = self.db.execute("SELECT COUNT(*) FROM subs").fetchone()[0]
            titles = self.db.execute(
                "SELECT COUNT(DISTINCT t.shiki_id) FROM title_files t JOIN downloads d "
                "ON d.key=t.dl_key WHERE d.status=?", (OK,)).fetchone()[0]
        size = 0
        for suffix in ("", "-wal"):
            try:
                size += os.path.getsize(self.path + suffix)
            except OSError:
                pass
        return {"files": int(files), "titles": int(titles), "bytes": size}

    def prune(self) -> int:
        """Удаляет устаревшие файлы и ответы API (зовётся в начале прогона)."""
        now = time.time()
        with self._lock:
            marks = ",".join("?" * len(_api.SOURCES))
            old = [r[0] for r in self.db.execute(
                f"SELECT key FROM downloads WHERE fetched < ? OR source NOT IN ({marks})",
                (now - _api.SUBS_TTL, *_api.SOURCES))]
            for i in range(0, len(old), 500):
                chunk = old[i:i + 500]
                marks = ",".join("?" * len(chunk))
                self.db.execute(f"DELETE FROM subs WHERE dl_key IN ({marks})", chunk)
                self.db.execute(f"DELETE FROM title_files WHERE dl_key IN ({marks})", chunk)
                self.db.execute(f"DELETE FROM downloads WHERE key IN ({marks})", chunk)
            self.db.execute("DELETE FROM kv WHERE t < ? OR k LIKE 'github:%'",
                            (now - _api.KV_MAX_AGE,))
            self.db.commit()
        # Деревья убранного GitHub-архива.
        import shutil
        shutil.rmtree(os.path.join(_api.CACHE_DIR, "github_trees"), ignore_errors=True)
        return len(old)

    def clear(self) -> None:
        with self._lock:
            for table in ("subs", "title_files", "downloads", "kv"):
                self.db.execute(f"DELETE FROM {table}")
            self.db.commit()
            self.db.execute("VACUUM")
