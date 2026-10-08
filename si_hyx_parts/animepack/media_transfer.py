# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Bounded media transfers: a single retry owner and cancellable chunk reads."""
from __future__ import annotations

import time
import threading
from urllib.parse import urlsplit

import requests

import animepack as api
from network_attempt import single_attempt_session

MAX_BYTES = 256 << 20
TRANSFER_SECONDS = 60
CHUNK_BYTES = 64 << 10
HOST_PAUSE_SECONDS = 60
_HEALTH_LOCK = threading.Lock()
# Был ли у текущей задачи сбой сети (хост на паузе, таймаут, 5xx). Такой
# срыв — не приговор тайтлу: кандидат откладывается на повтор, а не теряет
# род вопросов до конца прогона. Раньше пауза хоста роняла все шесть кадров
# за миллисекунды, и тайтл навсегда уходил в «доступных кадров нет».
_TROUBLE = threading.local()


def trouble_reset():
    _TROUBLE.seen = False


def trouble_mark():
    _TROUBLE.seen = True


def trouble_seen():
    return getattr(_TROUBLE, "seen", False)


def host_state(generator, url, failed=None):
    host = urlsplit(url).netloc.lower()
    if not host:
        return
    with _HEALTH_LOCK:
        states = getattr(generator, "_media_host_health", None)
        if states is None:
            states = generator._media_host_health = {}
        count, until = states.get(host, (0, 0))
        if failed is None:
            if time.monotonic() < until:
                _TROUBLE.seen = True
                raise api.AnimePackError(f"Источник {host} временно на паузе после сетевых сбоев")
            if until:
                states[host] = (0, 0)
        elif failed:
            count += 1
            states[host] = (count, time.monotonic() + HOST_PAUSE_SECONDS if count >= 3 else 0)
        else:
            states[host] = (0, 0)


def download(generator, url, timeout):
    deadline = time.monotonic() + TRANSFER_SECONDS
    tracker = getattr(generator, "_diagnostics", None)
    last = None
    with single_attempt_session(generator.session) as session:
        for attempt in range(api._DOWNLOAD_RETRIES + 1):
            check(generator, deadline)
            host_state(generator, url)
            remaining = max(0.1, deadline - time.monotonic())
            bounded = (min(float(timeout[0]), 5, remaining),
                       min(float(timeout[1]), 10, remaining))
            response = None
            try:
                if tracker is not None:
                    tracker.transfer()
                # Fake legacy sessions retain their small API; real HTTP is streamed.
                kwargs = {"timeout": bounded}
                if isinstance(session, requests.Session):
                    kwargs["stream"] = True
                response = session.get(url, **kwargs)
                response.raise_for_status()
                data = read(generator, response, deadline, tracker)
                host_state(generator, url, failed=False)
                return data
            except Exception as error:  # noqa: BLE001 — preserve the public error type
                last = error
                status = getattr(getattr(error, "response", None), "status_code", 0)
                if (isinstance(error, (requests.Timeout, requests.ConnectionError))
                        or status == 429 or (isinstance(status, int) and 500 <= status < 600)):
                    host_state(generator, url, failed=True)
                if isinstance(error, api.AnimePackError) or status in (400, 401, 403, 404, 410):
                    failure = api.AnimePackError(str(error))
                    failure.http_status = status
                    raise failure from error
                if attempt < api._DOWNLOAD_RETRIES:
                    generator._download_retry_pause(0.8 * (attempt + 1))
            finally:
                if response is not None and callable(getattr(response, "close", None)):
                    response.close()
    from karaoke.availability import temporary
    if temporary(last):
        _TROUBLE.seen = True
    raise api.AnimePackError(str(last)) from last


def check(generator, deadline):
    if generator.stopped():
        raise api.AnimePackError("Остановлено")
    if time.monotonic() >= deadline:
        raise api.AnimePackError("Скачивание превысило общий лимит времени")


def read(generator, response, deadline, tracker):
    try:
        expected = int((getattr(response, "headers", {}) or {}).get("Content-Length", 0))
    except (TypeError, ValueError):
        expected = 0
    if expected > MAX_BYTES:
        raise api.AnimePackError("Медиафайл превышает допустимый размер 256 МиБ")
    chunks = (response.iter_content(CHUNK_BYTES)
              if callable(getattr(response, "iter_content", None)) else [response.content])
    output = bytearray()
    for chunk in chunks:
        check(generator, deadline)
        if not chunk:
            continue
        if len(output) + len(chunk) > MAX_BYTES:
            raise api.AnimePackError("Медиафайл превышает допустимый размер 256 МиБ")
        output.extend(chunk)
        if tracker is not None:
            tracker.transfer(len(chunk))
    return bytes(output)
