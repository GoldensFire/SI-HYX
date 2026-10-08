"""Synchronous generator facade over Kuhi's complete native provider race."""
from __future__ import annotations

import asyncio
from concurrent.futures import TimeoutError as FutureTimeout
import threading
import time

from . import _race
from ._transport import RequestScope, scoped
from ._transport import AsyncClient

CAPTION_BYTES = 32 * 1024 * 1024
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
        from .provider_health import HEALTH
        self._health_start = HEALTH.snapshot()
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

    def episode_batches(self, aid, ctx, scope):
        from .batches import ProviderBatches, episode_batches
        return ProviderBatches(self, episode_batches(aid, ctx), scope, event_loop())

    def stream_batches(self, aid, episode, ctx, providers, scope):
        from .batches import ProviderBatches, watch_batches
        return ProviderBatches(self, watch_batches(aid, episode, ctx, providers), scope, event_loop())

    def range_supported(self, url, headers, scope):
        async def check():
            async with AsyncClient(follow_redirects=True) as client:
                response = await client.get(url, headers={**headers, "Range": "bytes=0-0"},
                                            headers_only=True)
            if response.status_code in (404, 410):
                # Нет этого файла (у AnimeLIB — на одном из трёх зеркал), а не
                # сбой провайдера: здоровье плеера от этого не страдает.
                raise FileNotFoundError(f"HTTP {response.status_code}: файла нет на сервере")
            if response.status_code in (403, 429) or response.status_code >= 500:
                raise ConnectionError(f"HTTP {response.status_code}: поток недоступен")
            return response.status_code == 206 and "content-range" in response.headers
        return bool(self.call(check(), scope, 22))

    def legacy_episodes(self, aid, scope):
        # Compatibility entry point: the audited zero-output Miruro relay is disabled.
        return {}

    def legacy_streams(self, aid, episode, scope):
        return []

    def timings(self, stream, headers, scope):
        from . import chapters
        if not stream.get("chapters") or (stream.get("intro") and stream.get("outro")):
            return {}
        return self.call(chapters.timings(stream, headers), scope, 12) or {}

    def captions(self, stream, scope):
        from urllib.parse import urljoin, urlsplit
        from ._http import UA
        async def collect():
            result = []
            async with AsyncClient(follow_redirects=True) as client:
                for row in stream.get("subtitles") or []:
                    url = urljoin(stream.get("referer") or stream["url"], row.get("url", ""))
                    if urlsplit(url).scheme not in ("http", "https"):
                        continue
                    headers = {"User-Agent": UA, **(stream.get("headers") or {})}
                    if stream.get("referer"):
                        headers.setdefault("Referer", stream["referer"])
                        origin = urlsplit(stream["referer"])
                        headers.setdefault("Origin", f"{origin.scheme}://{origin.netloc}")
                    # ASS со встроенными шрифтами бывает больше 4 МиБ общего лимита.
                    response = await client.get(url, headers=headers, max_bytes=CAPTION_BYTES)
                    response.raise_for_status()
                    name = row.get("name") or urlsplit(url).path.rsplit("/", 1)[-1]
                    if not name.lower().endswith((".ass", ".ssa", ".srt", ".vtt")):
                        name = "captions.vtt"
                    result.append((response.content, name))
            return result
        return self.call(collect(), scope, 20) or []

    def close(self):
        if self.closed:
            return
        self.closed = True
        with self._lock:
            for future in self._futures:
                future.cancel()
        if type(self) is KuhiClient:
            from .provider_health import HEALTH
            for (name, kind), counts in sorted(HEALTH.snapshot().items()):
                before = self._health_start.get((name, kind), {})
                delta = {key: value - before.get(key, 0) for key, value in counts.items()}
                if any(delta.values()):
                    stage = {"episodes": "каталог", "watch": "ссылки", "media": "видео", "output": "готовые отрывки"}.get(kind, kind)
                    self.log(f"Источник {name}, {stage}: успешно {delta.get('ok', 0)}, "
                             f"без совпадения {delta.get('missing', 0)}, "
                             f"сетевых сбоев {delta.get('network', 0)}, "
                             f"пропущено на паузе {delta.get('paused', 0)}.")

    def finish_scope(self, scope):
        future = asyncio.run_coroutine_threadsafe(scope.close(), event_loop())
        try:
            future.result(timeout=3)
        except Exception:
            future.cancel()
