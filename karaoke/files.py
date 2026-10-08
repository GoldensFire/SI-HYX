"""Atomic cache writes that survive a briefly open target on Windows."""
from __future__ import annotations

from contextlib import contextmanager
import threading
import time


def replace_file(temporary, target, *, attempts=6):
    """os.replace with a short bounded retry.

    Windows refuses to replace a file another thread is still reading
    (WinError 5/32); the reader finishes within milliseconds."""
    for number in range(attempts):
        try:
            temporary.replace(target)
            return
        except PermissionError:
            if number == attempts - 1:
                raise
            time.sleep(.05 * 2 ** number)


class KeyedLocks:
    """One lock per key while somebody holds or waits for it."""

    def __init__(self):
        self._guard = threading.Lock()
        self._locks = {}

    @contextmanager
    def hold(self, key, stopped=lambda: False):
        with self._guard:
            lock, users = self._locks.get(key, (None, 0))
            lock = lock or threading.Lock()
            self._locks[key] = (lock, users + 1)
        try:
            while not lock.acquire(timeout=.2):
                if stopped():
                    raise RuntimeError("Караоке: остановлено.")
            try:
                yield
            finally:
                lock.release()
        finally:
            with self._guard:
                lock, users = self._locks[key]
                if users <= 1:
                    del self._locks[key]
                else:
                    self._locks[key] = (lock, users - 1)
