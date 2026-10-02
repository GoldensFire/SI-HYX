"""A random 20-second Japanese scene from an existing Kuhi episode."""
from __future__ import annotations

from pathlib import Path
import threading
import time

import animepack as api
from si_hyx_parts.kuhi.client import KuhiClient
from si_hyx_parts.kuhi._transport import RequestScope
from .episode_media import cut
from .episode_media import request_headers
from .episode_sources import context, episode_catalog, hard_subbed, playable
from .generation_diagnostics import operation

TITLE_TIMEOUT = 240
EPISODE_ATTEMPTS = 3


def initialize(generator, client=None):
    generator.kuhi = client
    if client is None and generator.s.mix_shares.get(api.EPISODE_KIND):
        generator.kuhi = KuhiClient(generator.stopped, generator.log)
    generator._episode_subtitle_lock = threading.Lock()
    generator._episode_slots = threading.BoundedSemaphore(2)


def _finish(generator, candidate, aid, episode, stream, start, final):
    from .episode_subtitles import find, burn
    burned = False
    try:
        rows = find(generator, candidate, aid, episode, start)
        if rows and not generator.stopped():
            burned = burn(generator, final, rows)
    except Exception as error:
        generator._log_rare("Субтитры отрывка", f"Не удалось вшить субтитры: {error}")
    if generator.stopped():
        Path(final).unlink(missing_ok=True)
        return False
    candidate.has_video = True
    candidate.episode_clip = {"anilist_id": aid, "episode": episode,
                              "provider": stream["provider"], "start": round(start, 3),
                              "duration": 20, "audio": stream["audio"],
                              "hardsub": hard_subbed(stream), "ru_subtitles": burned}
    # Stable source identity excludes signed stream tokens and HTTP headers.
    candidate.source_link = f"https://anilist.co/anime/{aid}"
    generator.log(f"Отрывок «{candidate.title_ru}»: серия {episode}, "
                  f"{start:.1f}–{start + 20:.1f} с, {stream['provider']}"
                  + (", RU-субтитры" if burned else ""))
    return True


@operation("отрывки серий")
def download_episode(self, candidate):
    while not self.stopped():
        if self._episode_slots.acquire(timeout=0.2):
            try:
                return _download(self, candidate)
            finally:
                self._episode_slots.release()
    return False


def _download(self, candidate):
    if self.stopped() or self.kuhi is None:
        return False
    final = Path(self.folder) / "Video" / candidate.video_out
    scope = RequestScope(self.stopped, time.monotonic() + TITLE_TIMEOUT)
    try:
        aid, ctx = context(self, candidate)
        if not aid:
            self._log_rare("Kuhi без AniList ID", f"«{candidate.title_ru}»: нет AniList ID")
            return False
        catalog = episode_catalog(self.kuhi.episodes(aid, ctx, scope))
        episodes = list(catalog)
        self.rng.shuffle(episodes)
        for episode in episodes[:EPISODE_ATTEMPTS]:
            if self.stopped() or time.monotonic() >= scope.deadline:
                break
            sources = playable(self.kuhi.streams(aid, episode, ctx, catalog[episode], scope))
            for stream in sources:
                if time.monotonic() >= scope.deadline or self.stopped():
                    break
                start = _try_cut(self, candidate, stream, final, scope)
                if start is not None:
                    return _finish(self, candidate, aid, episode, stream, start, final)
        if not self.stopped() and time.monotonic() < scope.deadline:
            legacy = episode_catalog(self.kuhi.legacy_episodes(aid, scope))
            numbers = list(legacy)
            self.rng.shuffle(numbers)
            for episode in numbers[:EPISODE_ATTEMPTS]:
                if self.stopped() or time.monotonic() >= scope.deadline:
                    break
                sources = playable(self.kuhi.legacy_streams(aid, episode, scope))
                for stream in sources:
                    if self.stopped() or time.monotonic() >= scope.deadline:
                        break
                    start = _try_cut(self, candidate, stream, final, scope)
                    if start is not None:
                        return _finish(self, candidate, aid, episode, stream, start, final)
        self._log_rare("Kuhi", f"«{candidate.title_ru}»: пригодного 20-секундного отрывка нет")
    except Exception as error:
        if not self.stopped():
            self._log_rare("Kuhi", f"«{candidate.title_ru}»: {str(error)[:180]}")
    finally:
        if isinstance(self.kuhi, KuhiClient):
            self.kuhi.finish_scope(scope)
    final.unlink(missing_ok=True)
    return False


def _try_cut(generator, candidate, stream, final, scope):
    try:
        if (stream["type"] == "mp4" and not generator.kuhi.range_supported(
                stream["url"], request_headers(stream), scope)):
            return None
        if isinstance(generator.kuhi, KuhiClient):
            stream.update(generator.kuhi.timings(stream, request_headers(stream), scope))
        return cut(generator, candidate, stream, final, deadline=scope.deadline)
    except Exception as error:
        generator._log_rare("Поток Kuhi", f"{stream['provider']}: {str(error)[:140]}")
        return None
