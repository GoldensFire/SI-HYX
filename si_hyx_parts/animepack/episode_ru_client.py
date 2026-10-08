"""Cancellable synchronous facade over Russian source discovery and extraction."""
from __future__ import annotations

import asyncio
import threading
import time

from si_hyx_parts.kuhi.client import KuhiClient, event_loop
from . import episode_ru_animego as animego
from . import episode_ru_animelib as animelib
from . import episode_ru_yummy as yummy
from .episode_ru_catalog import error_detail
from .episode_ru_players import resolve
from .episode_stream_quality import variants
from .episode_collect import collect as collect_partial
from si_hyx_parts.kuhi.provider_health import HEALTH


CATALOGUES = (("AnimeLIB", animelib), ("AnimeGO", animego), ("YummyAnime", yummy))


def _budget(scope, seconds):
    return max(0, min(seconds, scope.deadline - time.monotonic()) - 1)


class RuEpisodeClient(KuhiClient):
    def __init__(self, stopped=lambda: False, log=lambda message: None):
        super().__init__(stopped, log)
        self.resources = {}
        self._pending = {}
        self._pending_lock = threading.Lock()

    def catalogue(self, candidate, ctx, scope):
        """Каталог серий; AnimeLIB отдаётся сразу, остальные дособираются в фоне.

        В живом прогоне объединённый поиск занимал медиану 5.1 с (максимум 15 с),
        хотя AnimeLIB — источник двух третей готовых роликов — отвечает за 1–2 с.
        Не дождавшиеся AnimeGO/YummyAnime остаются резервом: их забирает
        more_catalogue(), когда в уже готовом каталоге годного не нашлось."""
        title = getattr(candidate, "title_ru", None) or candidate.anime.get("russian") or candidate.anime.get("name", "")
        identity = f"«{title}» (MAL {candidate.mal_id})"

        async def collect():
            tasks = [(name, asyncio.create_task(source.catalogue(candidate, ctx)))
                     for name, source in CATALOGUES]
            for _name, task in tasks:
                # Невостребованный резерв может упасть уже без читателя.
                task.add_done_callback(lambda done: done.cancelled() or done.exception())
            with self._pending_lock:
                self._pending[id(scope)] = (tasks, set(), identity)
            lead = tasks[0][1]
            await asyncio.wait([lead], timeout=_budget(scope, 70))
            if lead.done() and not lead.cancelled() and lead.exception() is None and lead.result():
                return self._take(scope, [tasks[0][0]])
            return await self._rest(scope)
        return self.call(collect(), scope, 70) or {}

    def more_catalogue(self, scope):
        """Каталоги, ещё не отданные catalogue(); {} — резерва нет."""
        with self._pending_lock:
            state = self._pending.get(id(scope))
            if not state or len(state[1]) == len(state[0]):
                return {}
        return self.call(self._rest(scope), scope, 70) or {}

    async def _rest(self, scope):
        with self._pending_lock:
            tasks, used, _identity = self._pending.get(id(scope), ([], set(), ""))
            waiting = [task for name, task in tasks if name not in used]
        if waiting:
            await asyncio.wait(waiting, timeout=_budget(scope, 70))
        return self._take(scope, [name for name, _task in tasks if name not in used])

    def _take(self, scope, names):
        with self._pending_lock:
            tasks, used, identity = self._pending.get(id(scope), ([], set(), ""))
            used.update(names)
        catalog = {}
        for name, task in tasks:
            if name not in names:
                continue
            if not task.done():
                task.cancel()
                self.log(f"{name}: {identity}, каталог недоступен: источник превысил бюджет этапа (TimeoutError).")
                continue
            error = None if task.cancelled() else task.exception()
            if task.cancelled() or error is not None:
                error = error or asyncio.CancelledError()
                self.log(f"{name}: {identity}, каталог недоступен: {error_detail(error)} ({type(error).__name__}).")
                continue
            result = task.result()
            for number, releases in result.items():
                catalog.setdefault(number, []).extend(releases)
            reason = getattr(result, "reason", "")
            self.log(f"{name}: найдено серий {len(result)}. {identity}"
                     + (f" — {reason}." if reason else ""))
        return catalog

    def releases(self, rows, scope):
        async def expand(row):
            if row.get("ajax"):
                return await animego.expand(row)
            if row.get("native_episode"):
                return await animelib.expand(row)
            return [row]

        async def collect():
            results = await collect_partial((expand(row) for row in rows), scope, 30)
            releases, seen = [], set()
            for row, result in zip(rows, results):
                if isinstance(result, BaseException):
                    self.log(f"{row['source']}: список плееров недоступен: {error_detail(result)}.")
                    continue
                for row in result:
                    key = (row["source"], row["player"], row["embed"], str(row.get("release_id", "")))
                    if row["embed"] and key not in seen:
                        seen.add(key)
                        releases.append(row)
            return releases
        return self.call(collect(), scope, 30) or []

    def streams(self, rows, scope):
        rows = [row for row in rows if not HEALTH.paused(f"{row['source']}/{row['player']}", "media")]
        resources = self.resources.setdefault(id(scope), [])
        async def collect():
            results = await collect_partial((resolve(row, scope, resources) for row in rows), scope, 55)
            streams = []
            for row, result in zip(rows, results):
                if isinstance(result, BaseException):
                    HEALTH.result(f"{row['source']}/{row['player']}", "media", error=result)
                    self.log(f"{row['source']}/{row['player']}: поток недоступен: "
                             f"{error_detail(result)} ({type(result).__name__}).")
                    continue
                for stream in result:
                    stream.setdefault("intro", row.get("intro"))
                    stream.setdefault("outro", row.get("outro"))
                    streams.append(stream)
            return streams
        return self.call(collect(), scope, 55) or []

    def variants(self, streams, scope):
        async def collect():
            results = await collect_partial((variants(stream) for stream in streams), scope, 25)
            expanded = []
            for stream, result in zip(streams, results):
                # Unreadable manifests may still be understood by ffprobe; require its dimensions.
                expanded.extend([dict(stream)] if isinstance(result, BaseException) else result)
            return expanded
        return self.call(collect(), scope, 25) or []

    def captions(self, stream, scope):
        return super().captions(stream, scope)

    def release_resources(self, scope):
        resources = self.resources.pop(id(scope), [])
        async def close():
            await asyncio.gather(*(resource.close() for resource in resources), return_exceptions=True)
        # Cleanup must run even after Stop or a title deadline has expired.
        future = asyncio.run_coroutine_threadsafe(close(), event_loop())
        try:
            future.result(timeout=8)
        except Exception:
            future.cancel()

    def finish_scope(self, scope):
        with self._pending_lock:
            tasks = self._pending.pop(id(scope), ([], set(), ""))[0]
        for _name, task in tasks:
            event_loop().call_soon_threadsafe(task.cancel)
        self.release_resources(scope)
        super().finish_scope(scope)

    def close(self):
        super().close()
        resources = [resource for group in self.resources.values() for resource in group]
        self.resources.clear()
        async def close():
            from .episode_ru_alloha import close_shared
            await asyncio.gather(*(resource.close() for resource in resources), return_exceptions=True)
            await close_shared()
        asyncio.run_coroutine_threadsafe(close(), event_loop())
