# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Complete AnimeThemes transfers, shared pacing and interruptible cooldown."""
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
import math
import threading
import time

import requests

INTERVAL = 3.0
ATTEMPTS = 5
MAX_BYTES = 256 * 1024 * 1024
MAGIC = b"\x1a\x45\xdf\xa3"


class SourceError(RuntimeError):
    pass


class Stopped(SourceError):
    pass


class RequestGate:
    """One active transfer across generators, with a gap after closing it."""
    def __init__(self, interval=INTERVAL, clock=time.monotonic, sleep=time.sleep):
        self.interval, self.clock, self.sleep = interval, clock, sleep
        self.lock = threading.Lock()
        self.next_request = 0.0

    def defer(self, seconds):
        # Called while holding slot(), so other generators share the cooldown.
        self.next_request = max(self.next_request, self.clock() + seconds)

    def wait(self, stopped):
        while self.clock() < self.next_request:
            if stopped():
                raise Stopped("Загрузка AnimeThemes остановлена")
            self.sleep(min(.1, self.next_request - self.clock()))
        if stopped():
            raise Stopped("Загрузка AnimeThemes остановлена")

    @contextmanager
    def slot(self, stopped):
        while not self.lock.acquire(timeout=.1):
            if stopped():
                raise Stopped("Загрузка AnimeThemes остановлена")
        try:
            self.wait(stopped)
            yield
        finally:
            self.defer(self.interval)
            self.lock.release()


GATE = RequestGate()


def retry_after(value):
    try:
        seconds = float(value)
        return max(0.0, seconds) if math.isfinite(seconds) else 0.0
    except (TypeError, ValueError):
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return max(0.0, (date - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return 0.0


def copy_response(response, part, stopped, tracker):
    try:
        expected = int(response.headers.get("Content-Length") or 0)
    except (TypeError, ValueError) as error:
        raise SourceError("Некорректный размер ответа AnimeThemes") from error
    if expected < 0:
        raise SourceError("Некорректный размер ответа AnimeThemes")
    if expected > MAX_BYTES:
        raise SourceError("Ролик AnimeThemes превышает 256 МиБ")
    size = 0
    with part.open("wb") as stream:
        for chunk in response.iter_content(64 * 1024):
            if stopped():
                raise Stopped("Загрузка AnimeThemes остановлена")
            if not chunk:
                continue
            size += len(chunk)
            if size > MAX_BYTES:
                raise SourceError("Ролик AnimeThemes превышает 256 МиБ")
            stream.write(chunk)
            if tracker:
                tracker.transfer(len(chunk))
    if expected and size != expected:
        raise SourceError(f"Обрыв AnimeThemes: получено {size} из {expected} байт")
    with part.open("rb") as stream:
        head = stream.read(4)
    if size < 1024 or head != MAGIC:
        raise SourceError("AnimeThemes вернул пустой файл или ответ вместо WebM")
    return size


@contextmanager
def transport(session):
    """Keep proxy/TLS settings, but avoid API adapter retries inside our gate."""
    if not isinstance(session, requests.Session):
        yield session
        return
    with requests.Session() as client:
        client.headers.update(session.headers)
        client.proxies.update(session.proxies)
        client.cookies.update(session.cookies)
        client.verify, client.cert, client.trust_env = session.verify, session.cert, session.trust_env
        yield client


def download(session, url, target, stopped, log, tracker=None, *, gate=GATE):
    with transport(session) as client:
        return _download(client, url, target, stopped, log, tracker, gate)


def _download(session, url, target, stopped, log, tracker, gate):
    """No remote seeks: fully consume and close one GET before local probing."""
    target = Path(target)
    part = target.with_suffix(target.suffix + ".part")
    last = ""
    try:
        for attempt in range(ATTEMPTS):
            with gate.slot(stopped):
                delay = 0.0
                try:
                    if tracker:
                        tracker.transfer()
                    with session.get(url, stream=True, timeout=(10, 10),
                                     headers={"Accept-Encoding": "identity", "Accept": "*/*"}) as response:
                        status = response.status_code
                        if status in (408, 429) or 500 <= status <= 599:
                            delay = retry_after(response.headers.get("Retry-After"))
                            raise SourceError(f"HTTP {status}")
                        response.raise_for_status()
                        if status != 200:
                            raise SourceError(f"Неполный ответ AnimeThemes: HTTP {status}")
                        size = copy_response(response, part, stopped, tracker)
                    part.replace(target)
                    return size
                except Stopped:
                    raise
                except requests.HTTPError as error:
                    # Missing/deleted videos and access denials need no repeated GETs.
                    raise SourceError(str(error)) from error
                except (requests.RequestException, SourceError) as error:
                    last = str(error)
                    if attempt + 1 < ATTEMPTS:
                        delay = max(delay, min(60, 8 * 2 ** attempt))
                        gate.defer(delay)
                        log(f"AnimeThemes: {last}; повтор через {delay:g} с "
                            f"({attempt + 2}/{ATTEMPTS}).")
        raise SourceError(f"{last}; исчерпаны {ATTEMPTS} попыток загрузки")
    finally:
        part.unlink(missing_ok=True)
