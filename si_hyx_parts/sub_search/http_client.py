# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""HTTP для «Поиска по сабам»: пауза между запросами к одному хосту, повторы с
Retry-After, предел размера ответа и редиректы, не уносящие ключи на чужой хост.

Один клиент на весь прогон; потоки скачивания делят его (requests.Session),
паузы по хостам — под замком.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import requests

import sub_search as _api

_SENSITIVE = ("authorization", "api-key", "x-api-key")
_SECRET_QS = re.compile(r"(?i)\b(api_key|apikey|token|key)=[^&\s]+")
_RETRY_CODES = (429, 500, 502, 503, 504)


def redact(url: str) -> str:
    """Скрывает ключи API в URL (журнал, тексты ошибок, кэш)."""
    return _SECRET_QS.sub(r"\1=***", str(url or ""))


class HttpError(Exception):
    def __init__(self, status: int, url: str, body: bytes = b"") -> None:
        url = redact(url)
        super().__init__(f"HTTP {status}: {url}" if status else f"нет связи: {url}")
        self.status, self.url, self.body = status, url, body


class Stopped(Exception):
    """Прогон остановлен кнопкой «Стоп»."""


@dataclass
class Response:
    status: int
    headers: dict
    body: bytes
    url: str

    def json(self):
        import json
        return json.loads(self.body.decode("utf-8"))


class Http:
    def __init__(self, stop: threading.Event | None = None, timeout=(10, 60),
                 retries: int = 3, max_bytes: int = 64 * 1024 * 1024) -> None:
        self.stop = stop or threading.Event()
        self.timeout, self.retries, self.max_bytes = timeout, retries, max_bytes
        self.session = requests.Session()
        self.session.headers["User-Agent"] = _api.USER_AGENT
        self._intervals: dict[str, float] = {}
        self._next: dict[str, float] = {}
        self._lock = threading.Lock()

    def set_interval(self, host: str, seconds: float) -> None:
        self._intervals[host] = max(seconds, self._intervals.get(host, 0.0))

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:  # noqa: BLE001
            pass

    def _sleep(self, seconds: float) -> None:
        if seconds > 0 and self.stop.wait(seconds):
            raise Stopped()

    def _wait_turn(self, host: str) -> None:
        gap = self._intervals.get(host, 0.25)
        with self._lock:
            now = time.monotonic()
            at = max(now, self._next.get(host, 0.0))
            self._next[host] = at + gap
        self._sleep(at - time.monotonic())

    @staticmethod
    def _retry_after(headers, attempt: int) -> float:
        value = str(headers.get("retry-after", "") or "").strip()
        if value.isdigit():
            return min(float(value), 120.0)
        return min(2 ** attempt * 3, 60)

    def _send(self, method, url, headers, params, json_body, limit):
        """Один запрос с ручными редиректами: при переходе на другой хост
        заголовки с ключами снимаются."""
        hdrs = dict(headers or {})
        for _hop in range(6):
            if self.stop.is_set():
                raise Stopped()
            self._wait_turn(urlsplit(url).hostname or "")
            with self.session.request(method, url, headers=hdrs, params=params,
                                      json=json_body, timeout=self.timeout,
                                      stream=True, allow_redirects=False) as r:
                if r.is_redirect and r.headers.get("location"):
                    new = urljoin(r.url, r.headers["location"])
                    if urlsplit(new).hostname != urlsplit(url).hostname:
                        hdrs = {k: v for k, v in hdrs.items()
                                if k.lower() not in _SENSITIVE}
                    if r.status_code in (301, 302, 303) and method == "POST":
                        method, json_body = "GET", None
                    url, params = new, None
                    continue
                chunks, size = [], 0
                for chunk in r.iter_content(65536):
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > limit:
                        raise HttpError(413, url, b"response too large")
                    if self.stop.is_set():
                        raise Stopped()
                return Response(r.status_code, {k.lower(): v for k, v in r.headers.items()},
                                b"".join(chunks), r.url)
        raise HttpError(0, url, b"too many redirects")

    def request(self, method: str, url: str, *, headers=None, params=None,
                json_body=None, max_bytes: int | None = None, ok=(200,)) -> Response:
        limit = max_bytes or self.max_bytes
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                resp = self._send(method, url, headers, params, json_body, limit)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last = exc
                if attempt < self.retries:
                    self._sleep(min(2 ** attempt * 2, 30))
                    continue
                raise HttpError(0, url, str(exc).encode("utf-8", "replace")) from None
            if resp.status in ok:
                return resp
            if resp.status in _RETRY_CODES and attempt < self.retries:
                self._sleep(self._retry_after(resp.headers, attempt))
                continue
            raise HttpError(resp.status, url, resp.body[:4000])
        raise HttpError(0, url, str(last).encode("utf-8", "replace"))

    def get(self, url: str, **kw) -> Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw) -> Response:
        return self.request("POST", url, **kw)
