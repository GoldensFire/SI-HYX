"""A verified Japanese scene, with an SD fallback for older releases."""
from __future__ import annotations

from pathlib import Path
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import re
import threading
from urllib.parse import parse_qs, urlsplit
import time

import animepack as api
from si_hyx_parts.kuhi.client import KuhiClient
from si_hyx_parts.kuhi._transport import RequestScope
from .episode_media import cut, inspect_stream, request_headers
from .episode_sources import CUT_SECONDS, context, episode_catalog, hard_subbed, playable
from .episode_ru_catalog import PLAYER_ORDER
from .episode_ru_client import RuEpisodeClient
from .generation_diagnostics import measuring, operation
from .episode_captions import allowed, prepare as prepare_captions, write as write_captions
from . import episode_suitability
from .episode_quality_policy import ReleaseQuality, minimum, output_height
from .episode_caption_policy import mode
from .episode_scene_check import check as check_scene, initialize as initialize_scene
from si_hyx_parts.kuhi.provider_policy import enabled
from si_hyx_parts.kuhi.provider_health import HEALTH

TITLE_TIMEOUT = 240
EPISODE_ATTEMPTS = 3
# Сколько непроверенных вариантов проверять разом: следующие — только если
# среди этих годного не нашлось.
PROBE_BATCH = 3


def error_text(error):
    # httpx дописывает к ошибке строку «For more information check: …» —
    # в журнале это вторая строка без смысла.
    text = re.split(r"\s*For more information check:", str(error))[0]
    return " ".join(re.sub(r"https?://\S+", "[URL]", text).split())[:180]


def missing_file(text):
    """ffprobe сообщил об отсутствии файла (404/410), а не о сбое сети."""
    return bool(re.search(r"\b(?:404|410)\b|Not Found|Gone", str(text or "")))


def initialize(generator, client=None, ru_client=None):
    generator.kuhi = client
    if client is None and generator.s.mix_shares.get(api.EPISODE_KIND):
        generator.kuhi = KuhiClient(generator.stopped, generator.log)
    generator.episode_ru = ru_client
    if ru_client is None and generator.s.mix_shares.get(api.EPISODE_KIND):
        generator.episode_ru = RuEpisodeClient(generator.stopped, generator.log)
    generator._episode_subtitle_lock = threading.Lock()
    generator._episode_slots = threading.BoundedSemaphore(max(1, min(16, int(generator.s.parallel))))
    initialize_scene(generator)


def _finish(generator, candidate, aid, episode, stream, start, final, scope):
    output_language = stream.get("_caption_output_language") or ("ru" if stream.get("ru_subtitles") else "")
    burned = bool(stream.get("_captions_burned") or
                  stream.get("_captions_confirmed") or
                  (output_language in ("ru", "en") and hard_subbed(stream)))
    requested = mode(generator.s)
    if ((requested == "required" and not (burned and output_language == "ru"))
            or (requested == "preferred" and not (burned and output_language in ("ru", "en")))
            or (requested == "none" and burned and output_language == "ru")):
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
                              "source_height": stream.get("source_height"), "output_height": output_height(stream),
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
    if stream.get("_scene_check"):
        candidate.episode_clip["scene_check"] = stream["_scene_check"]
    elif stream.get("_scene_sampled_out"):
        # Модель ролик не смотрела: проверка выборочная (episode_scene_check).
        candidate.episode_clip["scene_check_skipped"] = "sync_track_sample"
    episode_suitability.of(generator).mark(candidate.mal_id, stream, "ok")
    HEALTH.result(stream["provider"], "output", ok=True)
    generator.log(f"Отрывок «{candidate.title_ru}»: серия {episode}, "
                  f"{start:.1f}–{start + CUT_SECONDS:.1f} с, {stream['provider']}"
                  + (f", {output_language.upper()}-субтитры" if burned else ""))
    return True


class EpisodeClipMixin:
    """Генератор: отрывок серии."""

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
    memory = episode_suitability.of(self)
    title = candidate.mal_id
    min_height = minimum(candidate)
    if memory.title_blocked(title, min_height):
        self._log_rare("Отрывки серий", f"«{candidate.title_ru}»: недавно проверено — "
                       f"источника ≥{min_height}p с японским звуком нет")
        return False
    scope = RequestScope(self.stopped, time.monotonic() + TITLE_TIMEOUT)
    tally = Counter()
    native_batches = None
    try:
        aid, ctx = context(self, candidate)
        ctx["subtitle_mode"] = mode(self.s)
        ctx["animelib_token"] = str(getattr(self.s, "animelib_token", "") or "").removeprefix("Bearer ").strip()
        if aid and isinstance(self.kuhi, KuhiClient):
            native_batches = self.kuhi.episode_batches(aid, ctx, scope)
        # Russian catalogues can match by MAL id even if AniZip has no AniList mapping.
        quality = ReleaseQuality()
        if self.episode_ru is not None and _russian(self, candidate, aid, ctx, final, scope,
                                                     tally, min_height, quality):
            return True
        if not aid or self.kuhi is None:
            self._log_rare("Kuhi без AniList ID", f"«{candidate.title_ru}»: нет AniList ID")
            return False
        if native_batches is not None:
            from .episode_fallback import native
            if native(self, candidate, aid, ctx, final, scope, native_batches, tally):
                return True
            catalog = {}
        else:
            catalog = episode_catalog(self.kuhi.episodes(aid, ctx, scope))
        episodes = list(catalog)
        self.rng.shuffle(episodes)
        for episode in episodes[:EPISODE_ATTEMPTS]:
            if self.stopped() or time.monotonic() >= scope.deadline:
                break
            sources = _verified(self, playable(self.kuhi.streams(aid, episode, ctx, catalog[episode], scope), episode),
                                final, scope, title, tally, min_height)
            for stream in sources:
                if time.monotonic() >= scope.deadline or self.stopped():
                    break
                start = _try_cut(self, candidate, stream, final, scope)
                if start is not None and _finish(self, candidate, aid, episode, stream, start, final, scope):
                    return True
        skipped = quality.skipped
        self._log_rare("Отрывки серий", f"«{candidate.title_ru}»: пригодного 15-секундного отрывка ≥{min_height}p нет"
                       + (f" (релизов ниже {min_height}p пропущено в других сериях: {skipped})"
                          if skipped else ""))
        # Три случайные серии не доказывают непригодность всего тайтла.
        # Память исключает только конкретные проверенные варианты.
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
        memory.save()
    final.unlink(missing_ok=True)
    return False


def _alloha_groups(rows):
    """Один поток Alloha (фильм, сезон, серия, перевод) — одна попытка браузера.

    AnimeGO и YummyAnime встраивают тот же плеер с разными партнёрскими
    токенами; раньше каждая ссылка открывала свой браузер. Остальные
    родительские страницы остаются запасными на случай сбоя первой."""
    groups = {}
    for row in rows:
        query = parse_qs(urlsplit(row["embed"]).query)
        key = tuple((query.get(name) or [""])[0] for name in ("token_movie", "season", "episode", "translation"))
        groups.setdefault(key if key[0] else (row["embed"],), []).append(row)
    return list(groups.values())


def _russian(self, candidate, aid, ctx, final, scope, tally, min_height, quality):
    """RU-каталоги: готовый AnimeLIB сразу, остальные каталоги — резервом."""
    title = candidate.mal_id
    memory = episode_suitability.of(self)
    # Плееры, уже дававшие этому тайтлу годную дорожку, — первыми.
    good = memory.good_players(title)
    players = sorted(PLAYER_ORDER, key=lambda name: name not in good)
    with measuring(self, "поиск источников"):
        catalog = self.episode_ru.catalogue(candidate, ctx, scope)
    more = getattr(self.episode_ru, "more_catalogue", None)
    chosen, expanded = [], set()
    while True:
        # Те же три случайные серии сохраняются, когда подоспел резервный каталог.
        episodes = [number for number in chosen if number in catalog]
        extra = [number for number in catalog if number not in chosen]
        self.rng.shuffle(extra)
        episodes += extra[:max(0, EPISODE_ATTEMPTS - len(episodes))]
        chosen.extend(number for number in episodes if number not in chosen)
        for episode in episodes:
            rows = [row for row in catalog[episode] if id(row) not in expanded]
            expanded.update(id(row) for row in rows)
            if not rows:
                continue
            with measuring(self, "поиск источников"):
                releases = self.episode_ru.releases(rows, scope)
            for player in players:
                if self.stopped() or time.monotonic() >= scope.deadline:
                    return False
                found = [row for row in releases if row["player"] == player and not quality.low(row)]
                groups = _alloha_groups(found) if player == "alloha" else [[found]] if found else []
                for group in groups:
                    for batch in (([row] for row in group) if player == "alloha" else group):
                        if self.stopped() or time.monotonic() >= scope.deadline:
                            return False
                        try:
                            with measuring(self, "поиск источников"):
                                sources = self.episode_ru.streams(batch, scope)
                            sources = [dict(stream, episode=episode) for stream in sources]
                            for stream in _verified(self, sources, final, scope, title, tally, min_height,
                                                    quality):
                                start = _try_cut(self, candidate, stream, final, scope)
                                if start is not None and _finish(self, candidate, aid, episode, stream, start, final, scope):
                                    return True
                                if stream.get("_scene_switch"):
                                    # Чужой язык или тайтл: этот релиз не годится
                                    # и в других сериях — переходим к другому источнику.
                                    quality.record(stream, "low")
                                    break
                        finally:
                            if isinstance(self.episode_ru, RuEpisodeClient):
                                self.episode_ru.release_resources(scope)
                        if sources or batch[0].get("_alloha_final"):
                            break  # Запасная ссылка дала бы тот же поток.
        if more is None or self.stopped() or time.monotonic() >= scope.deadline:
            return False
        with measuring(self, "поиск источников"):
            extra_catalog = more(scope)
        if not extra_catalog:
            return False
        for number, rows in extra_catalog.items():
            catalog.setdefault(number, []).extend(rows)


def _rank(stream):
    """Kuhi's raw/soft/hard preference, then the best known quality."""
    height = stream.get("source_height") or stream.get("manifest_height") or 0
    return (0 < height < 1080,
            False if stream.get("ru_subtitles") else hard_subbed(stream),
            stream.get("audio") != "raw" and not stream.get("ru_subtitles"),
            -(stream.get("source_height") or stream.get("manifest_height") or 0),
            -float(stream.get("bandwidth") or 0))


def _verified(generator, streams, final, scope, title=None, tally=None, min_height=1080,
              quality=None):
    """Проверенные потоки по одному, в порядке предпочтения — лениво.

    Ранее годный вариант тайтла проверяется первым и один; остальные — пачками
    по PROBE_BATCH и только если вызывающему понадобился следующий. Варианты,
    недавно проверенные как негодные или молчавшие, не проверяются вовсе."""
    tally = Counter() if tally is None else tally
    streams = [stream for stream in streams if allowed(generator, stream)
               and enabled(stream.get("provider"), {"subtitle_mode": mode(generator.s)})]
    for stream in streams:
        stream["min_height"] = min_height
    sources = generator.episode_ru.variants(streams, scope) if generator.episode_ru is not None else streams
    memory = episode_suitability.of(generator) if title else None
    known, fresh = [], []
    seen = set()
    for stream in sources:
        if generator.stopped() or time.monotonic() >= scope.deadline:
            break
        key = (stream["url"], str(request_headers(stream)), stream.get("manifest"))
        if key in seen:
            continue
        seen.add(key)
        verdict = memory.verdict(title, stream) if memory else ""
        if verdict in ("low", "pause", "missing"):
            tally[verdict] += 1
            continue
        (known if verdict == "ok" else fresh).append(stream)

    def inspect(stream):
        if generator.stopped() or time.monotonic() >= scope.deadline:
            return None
        if not HEALTH.allow(stream["provider"], "media"):
            tally["paused"] += 1
            return None
        tracker = getattr(generator, "_diagnostics", None)
        stage = "Отрывок серии"
        if tracker:
            tracker.local.stage = stage
        verdict = "pause"
        failure = None
        try:
            if stream["type"] == "mp4":
                transport = generator.episode_ru if stream.get("ru_subtitles") else generator.kuhi
                if not transport.range_supported(stream["url"], request_headers(stream), scope):
                    verdict = "low"
                    return None
                stream["_range_checked"] = True
            info = inspect_stream(generator, stream, final, scope.deadline)
            if info:
                stream["_probe_info"] = info
                verdict = "ok"
                return stream
            verdict = stream.get("_reject") or "pause"
            if verdict == "pause" and missing_file(stream.get("_probe_error")):
                verdict = "missing"
        except FileNotFoundError as error:
            verdict, failure = "missing", error
        except Exception as error:
            failure = error
            generator._log_rare("Проверка потока", f"{stream.get('provider', 'Kuhi')}: {error_text(error)}")
        finally:
            if not generator.stopped():
                tally[verdict] += 1
                if quality is not None:
                    quality.record(stream, verdict)
                if memory:
                    if verdict != "ok":
                        memory.mark(title, stream, verdict)
                # Отказ одного файла (404) не ставит на паузу весь плеер:
                # провайдеру засчитываются только сетевые сбои.
                if verdict == "pause" and failure is None:
                    failure = ConnectionError(stream.get("_probe_error") or "поток недоступен")
                HEALTH.result(stream["provider"], "media", ok=verdict == "ok",
                              error=failure if verdict == "pause" else None)
        return None

    # An SD cache hit must not outrank a newly discovered HD rendition.
    sd = [s for s in known + fresh if 0 < (s.get("source_height") or s.get("manifest_height") or 0) < 1080]
    known = [s for s in known if s not in sd]
    fresh = [s for s in fresh if s not in sd]
    for stream in sorted(known, key=_rank):
        if inspect(stream) is not None:
            yield stream
    fresh.sort(key=_rank)
    fresh += sorted(sd, key=_rank)
    for at in range(0, len(fresh), PROBE_BATCH):
        if generator.stopped() or time.monotonic() >= scope.deadline:
            return
        batch = fresh[at:at + PROBE_BATCH]
        with ThreadPoolExecutor(max_workers=len(batch), thread_name_prefix="Episode probe") as pool:
            verified = [stream for stream in pool.map(inspect, batch) if stream is not None]
        yield from sorted(verified, key=_rank)


def _try_cut(generator, candidate, stream, final, scope):
    captions = None
    try:
        transport = generator.episode_ru if stream.get("ru_subtitles") else generator.kuhi
        if (stream["type"] == "mp4" and not stream.get("_range_checked") and not transport.range_supported(
                stream["url"], request_headers(stream), scope)):
            return None
        if not stream.get("ru_subtitles") and isinstance(generator.kuhi, KuhiClient):
            stream.update(generator.kuhi.timings(stream, request_headers(stream), scope))
        for _ in range(3):
            if generator.stopped() or time.monotonic() >= scope.deadline:
                return None
            selected = prepare_captions(generator, stream, stream["_probe_info"], scope)
            if selected is None:
                return None
            start, rows = selected
            captions = write_captions(final, rows)
            result = cut(generator, candidate, stream, final, deadline=scope.deadline,
                         start=start, subtitles=captions)
            if captions:
                captions.unlink(missing_ok=True)
                captions = None
            if result is None:
                return None
            stream["_captions_burned"] = bool(rows)
            if check_scene(generator, candidate, stream, final, scope):
                return result
            Path(final).unlink(missing_ok=True)
            if not stream.get("_scene_retry"):
                return None
        return None
    except Exception as error:
        generator._log_rare("Поток отрывка", f"{stream['provider']}: {error_text(error)}")
        return None
    finally:
        if captions:
            captions.unlink(missing_ok=True)
