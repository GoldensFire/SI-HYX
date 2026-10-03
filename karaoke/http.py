"""Bounded, cancellable downloads with a shared disk cache."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import time


class Http:
    def __init__(self, session, *, stopped=lambda: False, cache=None):
        self.session = session
        self.stopped = stopped
        self.cache = Path(cache or Path.home() / ".cache/si-hyx-karaoke/sources")

    def bytes(self, url, *, ttl=86400, maximum=160_000_000):
        if self.stopped():
            raise RuntimeError("Караоке: остановлено.")
        target = self.cache / hashlib.sha256(url.encode()).hexdigest()
        if target.is_file() and time.time() - target.stat().st_mtime < ttl:
            if target.stat().st_size <= maximum:
                return target.read_bytes()
        self.cache.mkdir(parents=True, exist_ok=True)
        with self.session.get(url, timeout=(10, 35), stream=True) as response:
            response.raise_for_status()
            size = 0
            with tempfile.NamedTemporaryFile(dir=self.cache, delete=False) as stream:
                temporary = Path(stream.name)
                try:
                    for chunk in response.iter_content(128 * 1024):
                        if self.stopped():
                            raise RuntimeError("Караоке: остановлено.")
                        size += len(chunk)
                        if size > maximum:
                            raise ValueError("Караоке: источник превышает допустимый размер.")
                        stream.write(chunk)
                except Exception:
                    stream.close()
                    temporary.unlink(missing_ok=True)
                    raise
        temporary.replace(target)
        return target.read_bytes()

    def json(self, url, **options):
        return json.loads(self.bytes(url, **options))
