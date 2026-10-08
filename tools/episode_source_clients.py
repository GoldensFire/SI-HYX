"""Source-isolated clients for the live episode audit; no production routing edits."""
from __future__ import annotations

import asyncio
import copy
import importlib
import time

from si_hyx_parts.kuhi.client import KuhiClient
from si_hyx_parts.kuhi import legacy
from si_hyx_parts.kuhi.provider_policy import ACTIVE_NATIVE, enabled
from si_hyx_parts.animepack.episode_ru_client import RuEpisodeClient
from si_hyx_parts.animepack.episode_generation import error_text

RUSSIAN = {"animego": "animego", "yummy": "yummy", "animelib": "animelib"}
NATIVE = ("anineko", "anizone", "anikoto", "reanime", "aniwaves",
          "kaa", "anibd", "animegg", "mkissa", "animeonsen")
SOURCES = tuple(RUSSIAN) + ACTIVE_NATIVE


class Recorder:
    def __init__(self, write):
        self.write = write
        self.title = 0
        self.mode = ""
        self.catalogues = {}
        self.fresh_catalogues = 0
        self.found_catalogues = 0

    async def measured(self, coro, phase, timeout=60):
        started = time.monotonic()
        try:
            value = await asyncio.wait_for(coro, timeout)
            if phase == "catalogue":
                self.fresh_catalogues += 1
            size = len(value) if isinstance(value, (dict, list)) else 0
            self.write({"phase": phase, "mal": self.title, "mode": self.mode,
                        "seconds": round(time.monotonic() - started, 3),
                        "items": size})
            return value
        except Exception as error:
            if phase == "catalogue":
                self.fresh_catalogues += 1
            self.write({"phase": phase, "mal": self.title, "mode": self.mode,
                        "seconds": round(time.monotonic() - started, 3),
                        "error": error_text(error), "error_type": type(error).__name__})
            return {} if phase == "catalogue" else []

    def cached(self, key):
        if key in self.catalogues:
            return copy.deepcopy(self.catalogues[key])
        return None

    def remember(self, key, value, count):
        self.catalogues[key] = copy.deepcopy(value)
        self.found_catalogues += bool(count)


class SourceKuhi(KuhiClient):
    def __init__(self, source, recorder, stopped, log):
        super().__init__(stopped, log)
        self.source = source
        self.audit = recorder

    def episodes(self, aid, ctx, scope):
        if self.source not in NATIVE or not enabled(self.source, ctx):
            return {}
        key = (self.source, aid)
        hit = self.audit.cached(key)
        if hit is not None:
            return hit
        module = importlib.import_module("si_hyx_parts.kuhi." + self.source)
        data = self.call(self.audit.measured(module.get_episodes(aid, ctx), "catalogue"),
                         scope, 65) or {}
        eps = data.get("episodes") or {}
        count = sum(len(rows) for rows in eps.values() if isinstance(rows, list))
        result = {"providers": {self.source: data}} if count else {}
        self.audit.remember(key, result, count)
        self.log(f"{self.source}: MAL {self.audit.title}, серий {count}.")
        return result

    def episode_batches(self, aid, ctx, scope):
        # A real generator supports close(), retaining production cleanup behavior.
        if self.source in NATIVE:
            yield self.episodes(aid, ctx, scope)

    def stream_batches(self, aid, episode, ctx, providers, scope):
        yield self.streams(aid, episode, ctx, providers, scope)

    def streams(self, aid, episode, ctx, providers, scope):
        if self.source not in NATIVE:
            return []
        module = importlib.import_module("si_hyx_parts.kuhi." + self.source)

        async def collect():
            results = []
            for audio in providers.get(self.source, ()):
                rows = await self.audit.measured(module.watch(aid, audio, episode, ctx),
                                                 "streams", 75)
                results.extend(dict(row, provider=self.source) for row in rows or []
                               if row.get("audio") in ("raw", "sub"))
            return results

        return self.call(collect(), scope, 85) or []

    def legacy_episodes(self, aid, scope):
        if self.source != "miruro":
            return {}
        key = ("miruro", aid)
        value = self.audit.cached(key)
        if value is None:
            value = self.call(self.audit.measured(legacy.episodes(aid), "catalogue"),
                              scope, 65) or {}
            count = len(value.get("providers") or {})
            self.audit.remember(key, value, count)
        self._legacy_catalog[aid] = value
        return value

    def legacy_streams(self, aid, episode, scope):
        return self.call(self.audit.measured(legacy.streams(
            aid, episode, self._legacy_catalog.get(aid, {})), "streams", 75), scope, 80) or []


class SourceRu(RuEpisodeClient):
    def __init__(self, source, recorder, stopped, log):
        super().__init__(stopped, log)
        self.source = source
        self.audit = recorder
        self.no_ru = False

    def catalogue(self, candidate, ctx, scope):
        if self.source not in RUSSIAN:
            return {}
        key = (self.source, candidate.mal_id)
        value = self.audit.cached(key)
        if value is None:
            module = importlib.import_module(
                "si_hyx_parts.animepack.episode_ru_" + RUSSIAN[self.source])
            value = self.call(self.audit.measured(module.catalogue(candidate, ctx), "catalogue"),
                              scope, 65)
            if value is None:
                value = {}
            self.audit.remember(key, value, len(value))
        reason = getattr(value, "reason", "")
        self.log(f"{self.source}: MAL {candidate.mal_id}, серий {len(value)}. {reason}")
        return value

    def streams(self, rows, scope):
        streams = super().streams(rows, scope)
        self.audit.write({"phase": "ru_streams", "mal": self.audit.title,
                          "mode": self.audit.mode, "items": len(streams),
                          "players": sorted({row.get("player", "") for row in streams})})
        if self.no_ru:
            # Native AnimeLIB and some Alloha releases expose detachable captions.
            # Those same Japanese video tracks can be encoded without burning RU.
            from si_hyx_parts.animepack.episode_sources import hard_subbed
            refused = [row for row in streams if row.get("ru_subtitles") and hard_subbed(row)]
            if refused:
                self.log(f"Без RU: исключено {len(refused)} потоков с русскими субтитрами.")
            return [dict(row, ru_subtitles=False) if row.get("ru_subtitles") else row
                    for row in streams if not row.get("ru_subtitles") or not hard_subbed(row)]
        return streams
