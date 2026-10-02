# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Общий темп рабочих клиентов, минутная квота и прерываемый Retry-After."""
from collections import deque
from email.utils import parsedate_to_datetime
from math import isfinite
import threading
import time
from httpx import TransportError
from requests.exceptions import ConnectionError as RequestsConnectionError, Timeout

RETRYABLE_STATUSES = frozenset((429, 500, 502, 503, 504))


def retry_seconds(headers, fallback, wall_clock):
    value = str(headers.get("Retry-After") or "").strip()
    try:
        delay = float(value)
    except ValueError:
        try:
            delay = parsedate_to_datetime(value).timestamp() - wall_clock()
        except (ValueError, TypeError, OverflowError):
            return fallback
    return max(0, delay) if isfinite(delay) else fallback


class PopulationRateLimiter:
    def __init__(self, per_second, per_minute=0, *, clock=None, sleep=None,
                 wall_clock=None):
        self._base_interval = self.interval = 1 / per_second
        self.per_minute = per_minute
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._wall_clock = wall_clock or time.time
        self._lock = threading.Lock()
        self._recent = deque()
        self._next = self._blocked_until = self._recover_at = 0.0
        self._failures = 0
        self._busy_failures = 0
        self._requests = self._transport_errors = 0
        self._retry_responses = {}

    def acquire(self, stopped=None):
        while True:
            if stopped and stopped():
                raise InterruptedError("population refresh stopped")
            with self._lock:
                now = self._clock()
                while self._recent and now - self._recent[0] >= 60:
                    self._recent.popleft()
                delay = max(self._next, self._blocked_until) - now
                if self.per_minute and len(self._recent) >= self.per_minute:
                    delay = max(delay, self._recent[0] + 60 - now)
                if delay <= 0:
                    self._next = now + self.interval
                    self._requests += 1
                    if self.per_minute:
                        self._recent.append(now)
                    return
            # Кнопка «Остановить» действует и во время минутной квоты/Retry-After.
            self._sleep(min(delay, .25))

    def observe(self, response):
        with self._lock:
            now = self._clock()
            headers = response.headers
            if self.per_minute:
                try:
                    quota = int(headers.get("X-RateLimit-Limit", ""))
                except (TypeError, ValueError):
                    quota = 0
                if quota > 0:
                    self.per_minute = min(self.per_minute, quota)
                    self._base_interval = max(self._base_interval, 60 / quota)
                    self.interval = max(self.interval, self._base_interval)
            self._busy_failures = (self._busy_failures + 1
                                   if response.status_code == 503 else 0)
            if response.status_code in RETRYABLE_STATUSES:
                code = response.status_code
                self._retry_responses[code] = self._retry_responses.get(code, 0) + 1
                self._failures += 1
                delay = retry_seconds(headers, min(60, 2 ** self._failures),
                                      self._wall_clock)
                self._blocked_until = max(self._blocked_until, now + delay)
                # Известная минутная квота требует паузы, а не понижения темпа.
                # Разовый 503 тоже не доказывает, что частота запросов чрезмерна.
                quota_hit = response.status_code == 429 and self.per_minute and (
                    headers.get("X-RateLimit-Remaining") == "0")
                if ((response.status_code == 429 and not quota_hit)
                        or (response.status_code == 503 and self._busy_failures > 1)):
                    self.interval = min(10, max(self._base_interval, self.interval * 2))
                self._recover_at = self._blocked_until + 60
            elif response.status_code < 400 and now >= self._blocked_until:
                self._failures = 0
                self._busy_failures = 0
                if now >= self._recover_at and self.interval > self._base_interval:
                    self.interval = max(self._base_interval, self.interval / 1.2)
                    self._recover_at = now + 60

    def transport_failed(self):
        """A disconnected GET can be retried with the same shared, cancellable pause."""
        with self._lock:
            self._failures += 1
            self._transport_errors += 1
            self._busy_failures = 0
            self._blocked_until = max(self._blocked_until,
                self._clock() + min(60, 2 ** self._failures))

    def diagnostics(self):
        with self._lock:
            return {"requests": self._requests, "per_second": 1 / self.interval,
                    "retry_responses": dict(self._retry_responses),
                    "transport_errors": self._transport_errors}


def request_with_backoff(limiter, send, stopped=None):
    for attempt in range(4):
        limiter.acquire(stopped)
        try:
            response = send()
        except (TransportError, RequestsConnectionError, Timeout):
            if attempt == 3:
                raise
            limiter.transport_failed()
            continue
        limiter.observe(response)
        if response.status_code not in RETRYABLE_STATUSES or attempt == 3:
            return response
        response.close()
    raise AssertionError("unreachable")
