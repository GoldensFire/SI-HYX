"""A 15-second scene from a verified ≥1080p Japanese stream, encoded at 720p."""
from __future__ import annotations

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import re
import threading
import time

import animepack as api
from si_hyx_parts.kuhi.client import KuhiClient
from si_hyx_parts.kuhi._transport import RequestScope
from .episode_media import cut, inspect_stream, request_headers
from .episode_sources import CUT_SECONDS, context, episode_catalog, hard_subbed, playable
from .episode_ru_catalog import PLAYER_ORDER
from .episode_ru_client import RuEpisodeClient
from .generation_diagnostics import operation
from .episode_captions import allowed, prepare as prepare_captions, write as write_captions, wanted

TITLE_TIMEOUT = 240
EPISODE_ATTEMPTS = 3


def error_text(error):
    return re.sub(r"https?://\S+", "[URL]", str(error))[:180]


def initialize(generator, client=None, ru_client=None):
    generator.kuhi = client
    if client is None and generator.s.mix_shares.get(api.EPISODE_KIND):
        generator.kuhi = KuhiClient(generator.stopped, generator.log)
    generator.episode_ru = ru_client
    if ru_client is None and generator.s.mix_shares.get(api.EPISODE_KIND):
        generator.episode_ru = RuEpisodeClient(generator.stopped, generator.log)
    generator._episode_subtitle_lock = threading.Lock()
    generator._episode_slots = threading.BoundedSemaphore(max(1, min(16, int(generator.s.parallel))))


def _finish(generator, candidate, aid, episode, stream, start, final, scope):
    output_language = stream.get("_caption_output_language") or ("ru" if stream.get("ru_subtitles") else "")
    burned = bool(stream.get("_captions_burned") or
                  (output_language in ("ru", "en") and hard_subbed(stream)))
    if wanted(generator, stream) and not burned:
        Path(final).unlink(missing_ok=True)
        return False
    if generator.stopped():
        Path(final).unlink(missing_ok=True)
        return False
    candidate.has_video = True
    candidate.episode_clip = {"anilist_id": aid, "episode": episode,
                              "provider": stream["provider"], "start": round(start, 3),
                              "duration": int(CUT_SECONDS), "audio": stream["audio"],
                              "hardsub": hard_subbed(stream),
                              "ru_subtitles": burned and output_language == "ru",
                              "source_height": stream.get("source_height"), "output_height": 720,
                              "release": stream.get("release", "")}
    if stream.get("_ru_cues"):
        candidate.episode_clip.update(subtitle_source="video_track",
                                      subtitle_language=output_language,
                                      subtitle_source_language=stream.get("_caption_language"),
                                      subtitle_cues=stream["_ru_cues"])
    elif burned:
        candidate.episode_clip.update(subtitle_source=f"{output_language}_hardsub",
                                      subtitle_language=output_language)
    # Stable source identity excludes signed stream tokens and HTTP headers.
    candidate.source_link = stream.get("source_link") or f"https://anilist.co/anime/{aid}"
    generator.log(f"Отрывок «{candidate.title_ru}»: серия {episode}, "
                  f"{start:.1f}–{start + CUT_SECONDS:.1f} с, {stream['provider']}"
                  + (f", {output_language.upper()}-субтитры" if burned else ""))
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
    if self.stopped() or (self.kuhi is None and self.episode_ru is None):
        return False
    final = Path(self.folder) / "Video" / candidate.video_out
    scope = RequestScope(self.stopped, time.monotonic() + TITLE_TIMEOUT)
    native_batches = None
    try:
        aid, ctx = context(self, candidate)
        ctx["animelib_token"] = str(getattr(self.s, "animelib_token", "") or "").removeprefix("Bearer ").strip()
        if aid and isinstance(self.kuhi, KuhiClient):
            native_batches = self.kuhi.episode_batches(aid, ctx, scope)
        # Russian catalogues can match by MAL id even if AniZip has no AniList mapping.
        if self.episode_ru is not None:
            catalog = self.episode_ru.catalogue(candidate, ctx, scope)
            episodes = list(catalog)
            self.rng.shuffle(episodes)
            for episode in episodes[:EPISODE_ATTEMPTS]:
                releases = self.episode_ru.releases(catalog[episode], scope)
                for player in PLAYER_ORDER:
                    if self.stopped() or time.monotonic() >= scope.deadline:
                        break
                    sources = self.episode_ru.streams([row for row in releases if row["player"] == player], scope)
                    for stream in _verified(self, sources, final, scope):
                        start = _try_cut(self, candidate, stream, final, scope)
                        if start is not None and _finish(self, candidate, aid, episode, stream, start, final, scope):
                            return True
        if not aid or self.kuhi is None:
            self._log_rare("Kuhi без AniList ID", f"«{candidate.title_ru}»: нет AniList ID")
            return False
        if native_batches is not None:
            from .episode_fallback import native
            if native(self, candidate, aid, ctx, final, scope, native_batches):
                return True
            catalog = {}
        else:
            catalog = episode_catalog(self.kuhi.episodes(aid, ctx, scope))
        episodes = list(catalog)
        self.rng.shuffle(episodes)
        for episode in episodes[:EPISODE_ATTEMPTS]:
            if self.stopped() or time.monotonic() >= scope.deadline:
                break
            sources = _verified(self, playable(self.kuhi.streams(aid, episode, ctx, catalog[episode], scope)), final, scope)
            for stream in sources:
                if time.monotonic() >= scope.deadline or self.stopped():
                    break
                start = _try_cut(self, candidate, stream, final, scope)
                if start is not None and _finish(self, candidate, aid, episode, stream, start, final, scope):
                    return True
        if not self.stopped() and time.monotonic() < scope.deadline:
            legacy = episode_catalog(self.kuhi.legacy_episodes(aid, scope))
            numbers = list(legacy)
            self.rng.shuffle(numbers)
            for episode in numbers[:EPISODE_ATTEMPTS]:
                if self.stopped() or time.monotonic() >= scope.deadline:
                    break
                sources = _verified(self, playable(self.kuhi.legacy_streams(aid, episode, scope)), final, scope)
                for stream in sources:
                    if self.stopped() or time.monotonic() >= scope.deadline:
                        break
                    start = _try_cut(self, candidate, stream, final, scope)
                    if start is not None and _finish(self, candidate, aid, episode, stream, start, final, scope):
                        return True
        self._log_rare("Отрывки серий", f"«{candidate.title_ru}»: пригодного 15-секундного отрывка ≥1080p нет")
    except Exception as error:
        if not self.stopped():
            self._log_rare("Отрывки серий", f"«{candidate.title_ru}»: {error_text(error)}")
    finally:
        if native_batches is not None:
            native_batches.close()
        if isinstance(self.episode_ru, RuEpisodeClient):
            self.episode_ru.finish_scope(scope)
        if isinstance(self.kuhi, KuhiClient):
            self.kuhi.finish_scope(scope)
    final.unlink(missing_ok=True)
    return False


def _verified(generator, streams, final, scope):
    streams = [stream for stream in streams if allowed(generator, stream)]
    sources = generator.episode_ru.variants(streams, scope) if generator.episode_ru is not None else streams
    unique = []
    seen = set()
    for stream in sources:
        if generator.stopped() or time.monotonic() >= scope.deadline:
            break
        key = (stream["url"], str(request_headers(stream)), stream.get("manifest"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(stream)

    def inspect(stream):
        if generator.stopped() or time.monotonic() >= scope.deadline:
            return None
        tracker = getattr(generator, "_diagnostics", None)
        stage = "Отрывок серии"
        if tracker:
            tracker.local.stage = stage
        try:
            if stream["type"] == "mp4":
                transport = generator.episode_ru if stream.get("ru_subtitles") else generator.kuhi
                if not transport.range_supported(stream["url"], request_headers(stream), scope):
                    return None
                stream["_range_checked"] = True
            info = inspect_stream(generator, stream, final, scope.deadline)
            if info:
                stream["_probe_info"] = info
                return stream
        except Exception as error:
            generator._log_rare("Проверка потока", f"{stream.get('provider', 'Kuhi')}: {error_text(error)}")
        return None
    with ThreadPoolExecutor(max_workers=min(3, len(unique) or 1), thread_name_prefix="Episode probe") as pool:
        verified = [stream for stream in pool.map(inspect, unique) if stream is not None]
    # Preserve Kuhi's raw/soft/hard preference; choose highest real quality within a mode.
    return sorted(verified, key=lambda s: (False if s.get("ru_subtitles") else hard_subbed(s),
                  s.get("audio") != "raw" and not s.get("ru_subtitles"),
                  -s.get("source_height", 0), -float(s.get("bandwidth") or 0)))


def _try_cut(generator, candidate, stream, final, scope):
    captions = None
    try:
        transport = generator.episode_ru if stream.get("ru_subtitles") else generator.kuhi
        if (stream["type"] == "mp4" and not stream.get("_range_checked") and not transport.range_supported(
                stream["url"], request_headers(stream), scope)):
            return None
        if not stream.get("ru_subtitles") and isinstance(generator.kuhi, KuhiClient):
            stream.update(generator.kuhi.timings(stream, request_headers(stream), scope))
        selected = prepare_captions(generator, stream, stream["_probe_info"], scope)
        if selected is None:
            return None
        start, rows = selected
        captions = write_captions(final, rows)
        result = cut(generator, candidate, stream, final, deadline=scope.deadline,
                     start=start, subtitles=captions)
        if result is not None:
            stream["_captions_burned"] = bool(rows)
        return result
    except Exception as error:
        generator._log_rare("Поток отрывка", f"{stream['provider']}: {error_text(error)}")
        return None
    finally:
        if captions:
            captions.unlink(missing_ok=True)
