# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# gemini_quota.py — всё про пределы бесплатного тарифа Gemini: разбор ошибок
# сервера и общая на несколько клиентов «доска» (троттлинг + исчерпанные
# модели). Ни Qt, ни requests здесь нет.
#
# Зачем доска. Генератор держит ДВА клиента на одном ключе (сюжет и загадки по
# названию), а квота Google общая на проект. С раздельным состоянием они вдвое
# превышали RPM и продолжали слать запросы в модель, про которую сосед уже
# узнал, что она кончилась (в логе — 503 по 3.8-flash через пять секунд после
# перехода на 3.7-flash). Поэтому слоты RPM и список мёртвых моделей общие.
from __future__ import annotations

import re
import threading
import time
from typing import Any, Optional

# Признаки того, что 429 — это исчерпанная квота, а не разовый всплеск.
_QUOTA_MARKS = ("quota", "resource_exhausted")
# Явный суточный признак в ответе. Без него метка «модель кончилась» считается
# мягкой: под тем же 429 прячется и минутный предел.
_DAY_MARKS = ("perday", "per day")
_MINUTE_MARKS = ("perminute", "per minute", "requests per minute")
SERVER_FAILURE_LIMIT = 2
# «… limit: 20 …» — сам сервер называет потолок, гадать не нужно.
_LIMIT = re.compile(r"limit[:=]?\s*'?\"?(\d{1,6})", re.IGNORECASE)


def is_quota(text: str) -> bool:
    """429 про исчерпанную квоту (а не разовый rate-limit)."""
    low = str(text or "").casefold()
    return any(mark in low for mark in _QUOTA_MARKS)


def is_daily(text: str) -> bool:
    """Назван ли в ответе именно СУТОЧНЫЙ предел."""
    low = str(text or "").casefold()
    if any(mark in low for mark in _MINUTE_MARKS):
        return False
    return any(mark in low for mark in _DAY_MARKS)


def is_minute(text: str) -> bool:
    """Явный минутный предел: его пережидаем, не записываем как суточный."""
    return any(mark in str(text or "").casefold() for mark in _MINUTE_MARKS)


def daily_cap(text: str) -> int:
    """Суточный потолок из текста ошибки (0 — сервер его не назвал)."""
    if not is_daily(text):
        return 0
    match = _LIMIT.search(str(text or ""))
    try:
        return int(match.group(1)) if match else 0
    except (TypeError, ValueError):
        return 0


class QuotaBoard:
    """Общая память о пределах ОДНОГО ключа Gemini.

    Клиент без доски заводит себе собственную — тогда поведение ровно прежнее,
    как у одиночного клиента в тестах и в мелких задачах.

    api_key нужен только для памяти между прогонами (gemini_usage хранит счёт
    по хэшу ключа, сам ключ на диск не попадает). limits — потолки, выставленные
    пользователем на вкладке; 0 значит «не знаю, спроси у сервера».
    """

    def __init__(self, api_key: str = "", limits: Optional[dict] = None):
        self.api_key = str(api_key or "").strip()
        self.limits = {str(name): int(value or 0)
                       for name, value in dict(limits or {}).items()}
        self._lock = threading.Lock()
        self._next_at: dict[str, float] = {}
        self._dead: set[str] = set()
        self._server_failures: dict[str, int] = {}
        self._unavailable: set[str] = set()

    def unavailable(self, model: str) -> bool:
        """Перегрузка помнится только этой доской, не переносится на завтра."""
        with self._lock:
            return model in self._unavailable

    def note_server_failure(self, model: str) -> bool:
        with self._lock:
            count = self._server_failures.get(model, 0) + 1
            self._server_failures[model] = count
            if count >= SERVER_FAILURE_LIMIT:
                self._unavailable.add(model)
            return model in self._unavailable

    def note_response(self, model: str) -> None:
        with self._lock:
            self._server_failures.pop(model, None)

    def defer(self, model: str, seconds: float) -> None:
        """Retry-After действует и на соседние клиенты той же модели."""
        with self._lock:
            self._next_at[model] = max(self._next_at.get(model, 0),
                                       time.monotonic() + seconds)

    # ── троттлинг ────────────────────────────────────────────────────────
    def reserve(self, model: str, interval: float) -> float:
        """Занимает следующий слот модели; возвращает, сколько ждать до него.

        Слоты раздельны по моделям: перейдя с исчерпанной 3.8 на 3.7, новая
        модель не должна отстаивать очередь старой."""
        with self._lock:
            now = time.monotonic()
            next_at = self._next_at.get(model, 0.0)
            wait = next_at - now
            self._next_at[model] = max(next_at, now) + interval
        return wait

    # ── исчерпанные модели ───────────────────────────────────────────────
    def exhausted(self, model: str) -> bool:
        """Кончилась ли модель — в этом прогоне или уже сегодня до него."""
        with self._lock:
            if model in self._dead:
                return True
        if not self.api_key:
            return False
        import gemini_usage

        if gemini_usage.exhausted_today(self.api_key, model):
            with self._lock:
                self._dead.add(model)
            return True
        cap = self.limits.get(model, 0) or gemini_usage.daily_cap(self.api_key, model)
        if cap > 0 and gemini_usage.requests_today(self.api_key, model) >= cap:
            return True
        return False

    def mark(self, model: str, text: str = "") -> None:
        """Запоминает исчерпанную модель — и на прогон, и на сегодня."""
        with self._lock:
            self._dead.add(model)
        if self.api_key:
            import gemini_usage

            gemini_usage.mark_exhausted(self.api_key, model,
                                        hard=is_daily(text),
                                        cap=daily_cap(text))

    def spend(self, model: str) -> None:
        """Локальная оценка: ошибки сервера тоже могут расходовать квоту."""
        if self.api_key:
            import gemini_usage

            gemini_usage.record_request(self.api_key, model)

    def left(self, model: str) -> int:
        """Сколько запросов до известного потолка (-1 — потолок неизвестен)."""
        if not self.api_key:
            return -1
        import gemini_usage

        cap = self.limits.get(model, 0) or gemini_usage.daily_cap(self.api_key, model)
        if cap <= 0:
            return -1
        return max(0, cap - gemini_usage.requests_today(self.api_key, model))


def error_message(text: str, code: int) -> str:
    """Человеческое сообщение из тела ошибки Gemini (или просто код)."""
    import json

    try:
        data = json.loads(text or "")
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict):
            msg = str(err.get("message") or "").strip()
            status = str(err.get("status") or "").strip()
            if msg:
                return f"Gemini {code}: {msg}" + (f" [{status}]" if status else "")
    except (ValueError, AttributeError):
        pass
    snippet = (text or "").strip().replace("\n", " ")[:200]
    return f"Gemini {code}" + (f": {snippet}" if snippet else "")


_RETRY_DELAY = re.compile(r'"retryDelay"\s*:\s*"?(\d+(?:\.\d+)?)s')


def retry_after(resp: Any, text: str, default: float = 2.0) -> float:
    """Сколько ждать после 429: сервер называет срок сам.

    Сначала заголовок Retry-After, потом RetryInfo.retryDelay в теле ошибки
    («21s»). Верхняя граница — минута: дольше ждать в интерактивной вкладке
    бессмысленно, лучше отдать пользователю сообщение о квоте.
    """
    try:
        raw = (getattr(resp, "headers", None) or {}).get("Retry-After")
        if raw:
            return max(1.0, min(60.0, float(str(raw).strip())))
    except (TypeError, ValueError, AttributeError):
        pass
    match = _RETRY_DELAY.search(text or "")
    if match:
        try:
            return max(1.0, min(60.0, float(match.group(1))))
        except ValueError:
            pass
    return max(1.0, min(60.0, default))
