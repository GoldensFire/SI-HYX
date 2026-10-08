# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Память пригодности источников отрывков между генерациями.

В живом прогоне отрывки заняли полчаса: одни и те же 360p/720p варианты и
неподходящие дорожки проверялись заново в каждом паке. Здесь по тайтлу,
источнику, выпуску и режиму звука/субтитров хранится вердикт:

* ``ok``    — реальная дорожка проходит порог релиза с японским звуком; проверяется
              первым (и всё равно проверяется — подпись плеера не доказательство);
* ``low``   — дорожка проверена и не подходит; повторно не проверяется неделю;
* ``pause`` — источник не ответил (403, таймаут); пауза на 10 минут, не навсегда.

Если у тайтла все проверенные варианты подтверждённо не подходят, сам тайтл
пропускается на трое суток: генератор сразу берёт другую часть франшизы.

Подписанные ссылки и заголовки в ключ не входят — только устойчивая личность
источника. Вердикты привязаны к версии правил: поменялся порог качества —
старые вердикты не действуют.
"""
from __future__ import annotations

import json
import os
import threading
import time
from urllib.parse import urlsplit, urlunsplit

import animepack as _api
from .episode_stream_quality import MIN_HEIGHT

FILE_NAME = "animepack_episode_sources.json"
RULES = "hd1080-sd480-ja-scene-sub-modes-v4"
# missing — файла нет на конкретном сервере (404/410); соседние серверы и
# релиз от этого не страдают.
TTL = {"ok": 14 * 86400, "low": 7 * 86400, "pause": 10 * 60, "missing": 6 * 3600}
TITLE_TTL = 3 * 86400
SAVE_EVERY = 2.0


def store_path() -> str:
    return os.path.join(os.path.dirname(_api.SHIKI_CACHE_FILE), FILE_NAME)


def identity(stream: dict) -> str:
    """Устойчивая личность варианта: без подписанных ссылок и заголовков."""
    def stable_url(value):
        parsed = urlsplit(str(value or ""))
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))

    parts = (stream.get("provider"), stream.get("player"), stream.get("release"),
             stream.get("audio"), "ru" if stream.get("ru_subtitles") else "",
             stream.get("type"), stable_url(stream.get("source_link")),
             stream.get("episode"), stream.get("server"), stream.get("height"),
             stable_url(stream.get("url")), stream.get("min_height") or MIN_HEIGHT,
             stream.get("manifest_height"))
    return "|".join(str(part or "") for part in parts)


class Suitability:
    def __init__(self, path: str = ""):
        self.path = path or store_path()
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._revision = 0
        self._saved = 0.0
        self._dirty = False
        self.data = self._load()

    def _load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict) or data.get("rules") != RULES:
            return {"rules": RULES, "streams": {}, "titles": {}}
        now = time.time()
        streams = {k: v for k, v in (data.get("streams") or {}).items()
                   if isinstance(v, dict) and now - v.get("time", 0) < TTL.get(v.get("verdict"), 0)}
        titles = {k: v for k, v in (data.get("titles") or {}).items()
                  if isinstance(v, (int, float)) and now - v < TITLE_TTL}
        return {"rules": RULES, "streams": streams, "titles": titles}

    def verdict(self, title, stream) -> str:
        key = f"{title}|{identity(stream)}"
        with self._lock:
            row = self.data["streams"].get(key)
        if not row or time.time() - row.get("time", 0) >= TTL.get(row.get("verdict"), 0):
            return ""
        return row["verdict"]

    def mark(self, title, stream, verdict: str) -> None:
        if not title or verdict not in TTL:
            return
        with self._lock:
            self.data["streams"][f"{title}|{identity(stream)}"] = {
                "verdict": verdict, "time": time.time()}
            self._dirty = True
            self._revision += 1
        self.save(force=False)

    def good_players(self, title) -> set:
        """Плееры, которые у этого тайтла уже давали годную дорожку."""
        prefix = f"{title}|"
        with self._lock:
            rows = list(self.data["streams"].items())
        out = set()
        for key, row in rows:
            if (key.startswith(prefix) and row.get("verdict") == "ok"
                    and time.time() - row.get("time", 0) < TTL["ok"]):
                player = key[len(prefix):].split("|")[1]
                if player:
                    out.add(player)
        return out

    def title_blocked(self, title, min_height=MIN_HEIGHT) -> bool:
        with self._lock:
            when = self.data["titles"].get(str(title) if min_height == MIN_HEIGHT else f"{title}|{min_height}")
        return bool(when) and time.time() - when < TITLE_TTL

    def block_title(self, title) -> None:
        if not title:
            return
        with self._lock:
            self.data["titles"][str(title)] = time.time()
            self._dirty = True
            self._revision += 1
        self.save(force=True)

    def save(self, force: bool = True) -> None:
        # Снимок берётся после получения права записи: старый писатель уже
        # не сможет заменить файл поверх нового. Изменения во время записи
        # остаются грязными и попадут в следующий снимок.
        with self._write_lock:
            with self._lock:
                if not self._dirty or (not force and time.monotonic() - self._saved < SAVE_EVERY):
                    return
                payload = json.dumps(self.data, ensure_ascii=False)
                revision = self._revision
            tmp = f"{self.path}.{threading.get_ident()}.tmp"
            try:
                os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(payload)
                os.replace(tmp, self.path)
            except OSError:
                return
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            with self._lock:
                self._dirty = self._revision != revision
                self._saved = time.monotonic()


_OF_LOCK = threading.Lock()


def of(generator):
    """Память генератора (создаётся при первом обращении)."""
    with _OF_LOCK:
        memory = getattr(generator, "_episode_suitability", None)
        if memory is None:
            memory = generator._episode_suitability = Suitability()
    return memory
