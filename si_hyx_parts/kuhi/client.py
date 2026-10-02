"""Synchronous generator facade over Kuhi's complete native provider race."""
from __future__ import annotations

import asyncio
from concurrent.futures import TimeoutError as FutureTimeout
import threading
import time

from . import _race
from ._transport import RequestScope, scoped
from ._transport import AsyncClient

_loop = None
_loop_lock = threading.Lock()


def event_loop():
    global _loop
    with _loop_lock:
        if _loop is None:
            _loop = asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, name="Kuhi native providers",
                             daemon=True).start()
        return _loop


class KuhiClient:
    def __init__(self, stopped=lambda: False, log=lambda message: None):
        self.stopped = stopped
        self.log = log
        self._futures = set()
        self._lock = threading.Lock()
        self.closed = False
        self._legacy_catalog = {}

    def call(self, coro, scope, timeout):
        if self.closed or self.stopped():
            coro.close()
            return None
        future = asyncio.run_coroutine_threadsafe(scoped(coro, scope), event_loop())
        with self._lock:
            self._futures.add(future)
        deadline = min(scope.deadline, time.monotonic() + timeout)
        try:
            while not self.closed and not self.stopped():
                if time.monotonic() >= deadline:
                    return None
                try:
                    return future.result(timeout=0.2)
                except FutureTimeout:
                    continue
            return None
        finally:
            if not future.done():
                future.cancel()
            with self._lock:
                self._futures.discard(future)

    def episodes(self, anilist_id, ctx, scope):
        result = self.call(_race.merged_episodes(anilist_id, ctx), scope, 65) or {}
        names = ", ".join((result.get("providers") or {}).keys()) or "нет источников"
        self.log(f"Kuhi / AniList {anilist_id}: серии — {names}.")
        return result

    def streams(self, anilist_id, episode, ctx, providers, scope):
        result = self.call(_race.all_watch(anilist_id, episode, ctx, providers), scope, 80) or []
        self.log(f"Kuhi / AniList {anilist_id}, серия {episode}: потоков {len(result)}.")
        return result

    def range_supported(self, url, headers, scope):
        async def check():
            async with AsyncClient(follow_redirects=True) as client:
                response = await client.get(url, headers={**headers, "Range": "bytes=0-0"},
                                            headers_only=True)
            return response.status_code == 206 and "content-range" in response.headers
        return bool(self.call(check(), scope, 22))

    def legacy_episodes(self, aid, scope):
        from . import legacy
        data = self.call(legacy.episodes(aid), scope, 50) or {}
        self._legacy_catalog[aid] = data
        return data

    def legacy_streams(self, aid, episode, scope):
        from . import legacy
        return self.call(legacy.streams(aid, episode, self._legacy_catalog.get(aid, {})), scope, 55) or []

    def timings(self, stream, headers, scope):
        from . import chapters
        if not stream.get("chapters") or (stream.get("intro") and stream.get("outro")):
            return {}
        return self.call(chapters.timings(stream, headers), scope, 12) or {}

    def close(self):
        self.closed = True
        with self._lock:
            for future in self._futures:
                future.cancel()

    def finish_scope(self, scope):
        future = asyncio.run_coroutine_threadsafe(scope.close(), event_loop())
        try:
            future.result(timeout=3)
        except Exception:
            future.cancel()
