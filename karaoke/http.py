"""Bounded, cancellable downloads with a shared disk cache."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
from urllib.parse import urlparse
import requests
from network_attempt import single_attempt_session
from .availability import TemporaryUnavailable
from .files import KeyedLocks, replace_file

_INFLIGHT = KeyedLocks()


class HostHealth:
    """Short pause for a host after consecutive transient failures.

    Without it each of eight workers spent its own 10-second timeout on a
    source that had just failed for the neighbours."""
    FAILURES, PAUSE = 3, 20.0

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._lock = threading.Lock()
        self._rows = {}

    def check(self, host):
        with self._lock:
            failures, until = self._rows.get(host, (0, 0.0))
        left = until - self.clock()
        if left > 0:
            raise TemporaryUnavailable(f"Источник {host} временно на паузе ({left:.0f} с) после сетевых отказов.")

    def succeeded(self, host):
        with self._lock:
            self._rows.pop(host, None)

    def failed(self, host, status=0):
        with self._lock:
            failures, until = self._rows.get(host, (0, 0.0))
            failures += 1
            if failures >= self.FAILURES or status in (429, 503):
                until, failures = self.clock() + self.PAUSE, 0
            self._rows[host] = (failures, until)


HOSTS = HostHealth()


class MediaUnavailable(RuntimeError):
    """A CDN response cannot be trusted as audio; retry another source."""


def invalid_media(payload):
    prefix = payload.lstrip()[:128].lower()
    return not payload or prefix.startswith((b"<!doctype", b"<html", b"{", b"["))


class Http:
    def __init__(self, session, *, stopped=lambda: False, cache=None):
        self.session = session
        self.stopped = stopped
        self.cache = Path(cache or Path.home() / ".cache/si-hyx-karaoke/sources")

    def bytes(self, url, *, ttl=86400, maximum=160_000_000, media=False):
        return self._download(url, ttl=ttl, maximum=maximum, media=media)

    def invalidate(self, url):
        (self.cache / hashlib.sha256(url.encode()).hexdigest()).unlink(missing_ok=True)

    def post(self, url, data, *, ttl=86400, maximum=8_000_000, headers=None):
        return self._download(url, data=data, headers=headers, ttl=ttl, maximum=maximum)

    def _download(self, url, *, data=None, headers=None, ttl, maximum, media=False):
        from .budget import current_budget
        budget = current_budget()
        if budget is not None:
            budget.check()
        if self.stopped():
            raise RuntimeError("Караоке: остановлено.")
        identity = url if data is None else json.dumps([url, data], sort_keys=True)
        target = self.cache / hashlib.sha256(identity.encode()).hexdigest()
        # One request per URL: neighbours wait and then read the fresh cache
        # instead of downloading the same file and racing on its replacement.
        with _INFLIGHT.hold(str(target), self.stopped):
            cached = self._cached(target, ttl, maximum, media)
            if cached is not None:
                return cached
            host = urlparse(url).hostname or ""
            HOSTS.check(host)
            self.cache.mkdir(parents=True, exist_ok=True)
            options = {} if data is None else {"data": data, "headers": headers or {}}
            deadline = time.monotonic() + 60
            if budget is not None:
                deadline = min(deadline, budget.deadline)
            with single_attempt_session(self.session) as client:
                for number in range(2):
                    try:
                        payload = self._receive(client, url, data, options, maximum, media, deadline, target)
                        HOSTS.succeeded(host)
                        return payload
                    except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as error:
                        status = getattr(getattr(error, 'response', None), 'status_code', 0)
                        transient = not status or status in (408, 429, 500, 502, 503, 504)
                        if transient:
                            HOSTS.failed(host, status)
                        if number or not transient or self.stopped() or time.monotonic() >= deadline:
                            raise

    @staticmethod
    def _cached(target, ttl, maximum, media):
        try:
            stat = target.stat()
        except OSError:
            return None
        if time.time() - stat.st_mtime >= ttl:
            return None
        if stat.st_size <= maximum:
            cached = target.read_bytes()
            if not media or not invalid_media(cached):
                return cached
            target.unlink(missing_ok=True)
        return None

    def _receive(self, client, url, data, options, maximum, media, deadline, target):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Истёк срок проверки музыкального источника.')
        request = client.get if data is None else client.post
        with request(url, timeout=(min(5, remaining), min(10, remaining)), stream=True, **options) as response:
            response.raise_for_status()
            content_type = (getattr(response, "headers", {}) or {}).get("Content-Type", "").lower()
            if media and any(value in content_type for value in ("text/html", "application/json")):
                raise MediaUnavailable("Ссылка на аудио вернула HTML/JSON вместо записи.")
            declared = (getattr(response, "headers", {}) or {}).get("Content-Length", "")
            if str(declared).isdecimal() and int(declared) > maximum:
                failure = MediaUnavailable if media else ValueError
                raise failure("Караоке: источник превышает допустимый размер.")
            size = 0
            with tempfile.NamedTemporaryFile(dir=self.cache, delete=False) as stream:
                temporary = Path(stream.name)
                try:
                    for chunk in response.iter_content(128 * 1024):
                        if self.stopped():
                            raise RuntimeError("Караоке: остановлено.")
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Караоке: истёк общий срок загрузки источника.")
                        size += len(chunk)
                        if size > maximum:
                            failure = MediaUnavailable if media else ValueError
                            raise failure("Караоке: источник превышает допустимый размер.")
                        stream.write(chunk)
                    stream.flush()
                    if media:
                        with temporary.open("rb") as preview:
                            if invalid_media(preview.read(128)):
                                raise MediaUnavailable("Ссылка на аудио вернула пустые данные или страницу ошибки.")
                except Exception:
                    stream.close()
                    temporary.unlink(missing_ok=True)
                    raise
        payload = temporary.read_bytes()
        try:
            replace_file(temporary, target)
        except OSError:
            # The cache is an optimisation: a locked file must not fail the song.
            temporary.unlink(missing_ok=True)
        return payload

    def json(self, url, **options):
        return json.loads(self.bytes(url, **options))
