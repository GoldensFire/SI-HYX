"""Cancellable synchronous facade over Russian source discovery and extraction."""
from __future__ import annotations

import asyncio

from si_hyx_parts.kuhi.client import KuhiClient, event_loop
from . import episode_ru_animego as animego
from . import episode_ru_animelib as animelib
from . import episode_ru_yummy as yummy
from .episode_ru_catalog import error_detail
from .episode_ru_players import resolve
from .episode_stream_quality import variants


class RuEpisodeClient(KuhiClient):
    def __init__(self, stopped=lambda: False, log=lambda message: None):
        super().__init__(stopped, log)
        self.resources = {}

    def catalogue(self, candidate, ctx, scope):
        async def collect():
            results = await asyncio.gather(*(source.catalogue(candidate, ctx)
                                             for source in (animego, yummy, animelib)), return_exceptions=True)
            catalog = {}
            title = getattr(candidate, "title_ru", None) or candidate.anime.get("russian") or candidate.anime.get("name", "")
            identity = f"«{title}» (MAL {candidate.mal_id})"
            for source, result in zip(("AnimeGO", "YummyAnime", "AnimeLIB"), results):
                if isinstance(result, BaseException):
                    self.log(f"{source}: {identity}, каталог недоступен: {error_detail(result)} ({type(result).__name__}).")
                    continue
                for number, releases in result.items():
                    catalog.setdefault(number, []).extend(releases)
                reason = getattr(result, "reason", "")
                self.log(f"{source}: найдено серий {len(result)}. {identity}"
                         + (f" — {reason}." if reason else ""))
            return catalog
        return self.call(collect(), scope, 70) or {}

    def releases(self, rows, scope):
        async def expand(row):
            if row.get("ajax"):
                return await animego.expand(row)
            if row.get("native_episode"):
                return await animelib.expand(row)
            return [row]

        async def collect():
            results = await asyncio.gather(*(expand(row) for row in rows), return_exceptions=True)
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
        resources = self.resources.setdefault(id(scope), [])
        async def collect():
            results = await asyncio.gather(*(resolve(row, scope, resources) for row in rows), return_exceptions=True)
            streams = []
            for row, result in zip(rows, results):
                if isinstance(result, BaseException):
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
            results = await asyncio.gather(*(variants(stream) for stream in streams), return_exceptions=True)
            expanded = []
            for stream, result in zip(streams, results):
                # Unreadable manifests may still be understood by ffprobe; require its dimensions.
                expanded.extend([dict(stream)] if isinstance(result, BaseException) else result)
            return expanded
        return self.call(collect(), scope, 25) or []

    def captions(self, stream, scope):
        return super().captions(stream, scope)

    def finish_scope(self, scope):
        resources = self.resources.pop(id(scope), [])
        async def close():
            await asyncio.gather(*(resource.close() for resource in resources), return_exceptions=True)
        # Cleanup must run even after Stop or a title deadline has expired.
        future = asyncio.run_coroutine_threadsafe(close(), event_loop())
        try:
            future.result(timeout=8)
        except Exception:
            future.cancel()
        super().finish_scope(scope)

    def close(self):
        super().close()
        resources = [resource for group in self.resources.values() for resource in group]
        self.resources.clear()
        async def close():
            await asyncio.gather(*(resource.close() for resource in resources), return_exceptions=True)
        asyncio.run_coroutine_threadsafe(close(), event_loop())
