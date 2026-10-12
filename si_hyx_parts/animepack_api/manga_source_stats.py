# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Успешность источников страниц манги на этом компьютере, между прогонами.

Порядок источников внутри языка — по доле тайтлов, давших скачанную
страницу. Отказ API (HTTP 403) и геоблок сервера картинок запоминаются на
сутки: раньше каждый прогон узнавал о них заново, через таймауты в середине
генерации."""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time

BLOCK_HOURS = 24
# Окно статистики: старые прогоны постепенно перестают решать порядок.
WINDOW = 200
# Стартовые значения — замер 2026-10-08 с компьютера пользователя (IP вне
# СНГ): 40 тайтлов уровня пака (20 манги, 12 манхвы, 8 маньхуа), каждый
# источник отдельно — поиск, глава, скачивание страницы.
PRIORS = {
    "mangalib": {"tries": 40, "found": 23, "pages": 23},
    "mangadex": {"tries": 40, "found": 22, "pages": 22},
    "mangafire": {"tries": 40, "found": 33, "pages": 33},
    "weebcentral": {"tries": 40, "found": 9, "pages": 9},
    "remanga": {"tries": 40, "found": 14, "pages": 4},
    "comix": {"tries": 40, "found": 0, "pages": 0},
}


class SourceStats:
    def __init__(self, path, *, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self.lock = threading.Lock()
        self.sources = {key: dict(row) for key, row in PRIORS.items()}
        self.blocked, self.hosts = {}, {}
        self._load()

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        for key, row in (data.get("sources") or {}).items():
            if key in self.sources and isinstance(row, dict):
                self.sources[key] = {name: float(row.get(name) or 0)
                                     for name in ("tries", "found", "pages")}
        now = self.clock()
        for name, target in (("blocked", self.blocked), ("hosts", self.hosts)):
            for key, row in (data.get(name) or {}).items():
                if isinstance(row, dict) and float(row.get("until") or 0) > now:
                    target[key] = {"until": float(row["until"]),
                                   "reason": str(row.get("reason") or "")}

    def save(self):
        with self.lock:
            data = {"version": 1, "sources": self.sources,
                    "blocked": self.blocked, "hosts": self.hosts}
            text = json.dumps(data, ensure_ascii=False, indent=1)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            part = self.path.with_suffix(".part")
            part.write_text(text, encoding="utf-8")
            os.replace(part, self.path)
        except OSError:
            pass    # статистика — подсказка порядка, не данные пака

    def _add(self, key, **values):
        with self.lock:
            row = self.sources.setdefault(key, {"tries": 0, "found": 0, "pages": 0})
            for name, value in values.items():
                row[name] = row.get(name, 0) + value
            if row["tries"] > WINDOW:
                scale = WINDOW / row["tries"]
                for name in row:
                    row[name] *= scale

    def tried(self, key, found, page=False):
        """Попытка тайтла; page — страница уже скачана (MangaDex качает генератор)."""
        self._add(key, tries=1, found=int(bool(found)), pages=int(bool(page)))

    def page(self, key, ok):
        """Итог скачивания страницы, найденной этим источником."""
        if not ok:
            return
        with self.lock:
            row = self.sources.get(key)
            if row is not None:
                row["pages"] = min(row["found"], row.get("pages", 0) + 1)

    def score(self, key):
        with self.lock:
            row = self.sources.get(key) or {}
            return (row.get("pages", 0) + 1) / (row.get("tries", 0) + 2)

    def _active(self, table, key):
        with self.lock:
            row = table.get(key)
            if row and row["until"] > self.clock():
                return row["reason"]
            table.pop(key, None)
            return ""

    def block_reason(self, key):
        return self._active(self.blocked, key)

    def host_reason(self, host):
        return self._active(self.hosts, host)

    def block(self, key, reason):
        with self.lock:
            self.blocked[key] = {"until": self.clock() + BLOCK_HOURS * 3600,
                                 "reason": str(reason)[:200]}

    def block_host(self, host, reason):
        with self.lock:
            self.hosts[host] = {"until": self.clock() + BLOCK_HOURS * 3600,
                                "reason": str(reason)[:200]}

    def summary(self, keys, labels):
        """«MangaLib 57%, MangaDex 54%; пропускаю Comix.to (…)» для журнала."""
        ranked = sorted(keys, key=self.score, reverse=True)
        parts = [f"{labels[key]} {self.score(key):.0%}" for key in ranked
                 if not self.block_reason(key)]
        text = "Источники манги по успешности на этом компьютере: " + ", ".join(parts)
        skipped = [f"{labels[key]} ({self.block_reason(key)}; до "
                   f"{time.strftime('%d.%m %H:%M', time.localtime(self.blocked[key]['until']))})"
                   for key in ranked if self.block_reason(key)]
        if skipped:
            text += "; пропускаю " + ", ".join(skipped)
        with self.lock:
            hosts = sorted(self.hosts)
        if hosts:
            text += "; закрытые серверы картинок: " + ", ".join(hosts)
        return text + "."


def attach(source, path):
    """Подключить сохранённую статистику к MangaPageSources генератора."""
    stats = SourceStats(path)
    source._health.stats = stats
    return stats
