"""Karaoke presentation of opening/ending/insert song slots."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time

import animepack as ap
from karaoke.crop import aligned_start
from karaoke.render import render, reverse_audio, tempo
from karaoke.resolver import Resolver
from karaoke.timeline import transform
from karaoke.style import choose_colour, font_size, FONT_NAME
from karaoke.rejections import Rejected, SourceRejected, cache_key, AI_POLICY, REFERENCE_POLICY
from karaoke.search import context, SEARCH_POLICY
from karaoke.paired_lyrics import POLICY
from .song_downloads import source_bytes
from karaoke.availability import TemporaryUnavailable, temporary
from storage_guard import require_space, raise_if_full


def rejection_key(generator, candidate, *, source=False):
    values = ["candidate-source" if source else "candidate", candidate.audio_file,
              candidate.song_name, candidate.artist, bool(generator.s.karaoke_ai_fallback),
              SEARCH_POLICY, POLICY, REFERENCE_POLICY,
              context(candidate.song, candidate.anime, candidate.kind)]
    if generator.s.karaoke_ai_fallback:
        values.append(AI_POLICY)
    excerpt = getattr(generator.karaoke_resolver, "excerpt_duration", 0)
    if excerpt:
        values.extend(("confirmed-excerpt-v1", excerpt))
    if not source:
        values.extend((candidate.trim_start, generator.s.audio_cut))
    return cache_key(*values)


def known_rejection(generator, candidate):
    if generator.s.karaoke_effect == "reverse":
        return ""
    cache = generator.karaoke_resolver.rejections
    return (cache.get(rejection_key(generator, candidate, source=True))
            or cache.get(rejection_key(generator, candidate)))


def download_karaoke(generator, candidate):
    final = Path(generator.folder) / "Video" / candidate.video_out
    candidate.has_video = False
    candidate.karaoke = {}
    candidate._music_temporary = False
    try:
        rejected = known_rejection(generator, candidate)
        if rejected:
            generator.log(f"Караоке «{candidate.song_name}»: недельный кэш отказов — {rejected}")
            return False
        if not candidate.audio_file:
            return False
        if not authored_timings_possible(generator, candidate):
            return False
        with tempfile.TemporaryDirectory(prefix="karaoke-", dir=generator.folder) as directory:
            require_space(directory)
            source = Path(directory) / "source.audio"
            with generator._timed("караоке: загрузка аудио"):
                data = source_bytes(generator, candidate)
            if len(data) < ap._MIN_AUDIO_BYTES:
                raise ValueError("Исходный файл подозрительно мал.")
            source.write_bytes(data)
            if generator.s.karaoke_effect == "reverse":
                return reverse_audio(generator, candidate, source)
            resolver = generator.karaoke_resolver
            with generator._timed("караоке: тайминги и проверка записи"):
                lines, metadata = resolver.resolve(source, candidate.song_name, candidate.artist,
                                                   context(candidate.song, candidate.anime, candidate.kind))
            metadata = dict(metadata)
            requested = float(candidate.trim_start)
            end = min(metadata["duration"], metadata.get("confirmed_excerpt", [0, metadata["duration"]])[1])
            # Another intro/tail: only the fingerprinted span is the same recording.
            span = (metadata.get("recording") or {}).get("verified_span") or [0.0, end]
            end = min(end, span[1])
            start = aligned_start(lines, max(requested, span[0]), float(generator.s.audio_cut),
                                  end, offset=metadata["offset"], minimum=span[0])
            duration = min(float(generator.s.audio_cut), end - start)
            if duration < 1:
                raise ValueError("Отрезок песни выходит за её длительность.")
            cropped = transform(lines, crop_start=start, crop_end=start + duration,
                                tempo=tempo(generator.s), offset=metadata["offset"])
            if not cropped or not any(unit.end > unit.start and unit.text.strip()
                                      and unit.start < line.visible_end and unit.end > line.start
                                      for line in cropped for unit in line.units):
                raise Rejected("В выбранном отрезке нет вокала с таймингами.")
            highlight = choose_colour(generator.rng)
            with generator._timed("караоке: кодирование"):
                subtitle, seconds = render(generator, source, final, cropped, start=start,
                                           duration=duration, highlight=highlight)
            metadata.update(requested_crop_start=requested, crop_start=start,
                            crop_alignment="word", crop_duration=duration, output_duration=seconds,
                            crf=generator.s.karaoke_crf, preset=generator.s.karaoke_preset,
                            tempo=tempo(generator.s), effect=generator.s.karaoke_effect,
                            romaji_lines=len(cropped),
                            highlight_colour="#" + highlight,
                            font=FONT_NAME, font_size=font_size(720),
                            translation_languages=sorted({("ru" if line.translations.get("ru") else "en")
                                                          for line in cropped if line.translation})
                            if generator.s.karaoke_translations else [])
            candidate.karaoke = metadata
            candidate.trim_start = start
            candidate.has_video = True
            (final.parent / (final.stem + ".ass")).write_text(subtitle, encoding="utf-8-sig")
            verdict = ("непрерывный отрезок подтверждён распознаванием вокала."
                       if metadata.get("confirmed_excerpt") else
                       "текст сопоставлен с вокалом исходной записи." if metadata.get("ai_used") else
                       "совпали название, исполнитель и длительность." if metadata.get("alignment") else
                       "версия аудио подтверждена.")
            generator.log(f"Караоке «{candidate.song_name}»: {metadata['source']}, "
                          f"{len(cropped)} строк, {verdict}")
            return True
    except Exception as error:
        raise_if_full(error, generator.folder)
        candidate._music_temporary = temporary(error)
        if isinstance(error, Rejected) and not generator.stopped():
            key = rejection_key(generator, candidate, source=isinstance(error, SourceRejected))
            generator.karaoke_resolver.rejections.put(key, error)
        final.unlink(missing_ok=True)
        action = "откладываю повторную попытку" if candidate._music_temporary else "беру следующую песню"
        generator.log(f"Караоке «{candidate.song_name}»: {error} — {action}.")
        return False


def catalog_duration(candidate):
    """Длина записи по каталогу AnisongDB (0 — неизвестна)."""
    try:
        return max(0.0, float((candidate.song or {}).get("songLength") or 0))
    except (TypeError, ValueError):
        return 0.0


def instrumental(candidate) -> bool:
    return str((candidate.song or {}).get("songCategory") or "").casefold() == "instrumental"


def authored_timings_possible(generator, candidate) -> bool:
    """Без AI караоке возможно только по готовым таймингам: их наличие по
    названию, исполнителю и длительности проверяется ДО загрузки записи.
    С AI до загрузки проверяется хотя бы наличие оригинального текста."""
    if generator.s.karaoke_effect == "reverse":
        return True
    resolver = generator.karaoke_resolver
    if instrumental(candidate):
        return _skip(generator, candidate, "Инструментальная версия: текста для караоке нет.",
                     remember=True)
    wait_for_sources(generator)
    # «Неизвестно» из предварительной проверки — не ответ: тогда не ответил
    # источник, а не песня. Спрашиваем заново (удачные поиски уже лежат в
    # кэше Http), иначе устаревшее «неизвестно» сразу шло в отказ.
    available = getattr(candidate, '_authored_available', None)
    info = context(candidate.song, candidate.anime, candidate.kind)
    if available is None:
        with generator._timed("караоке: поиск готовых таймингов"):
            available = resolver.authored_available(
                candidate.song_name, candidate.artist, info, duration=catalog_duration(candidate))
        candidate._authored_available = available
    if generator.s.karaoke_ai_fallback:
        if available is True:
            return True
        with generator._timed("караоке: поиск текста песни"):
            lyrics = resolver.lyrics.available(candidate.song_name, candidate.artist,
                                               duration=catalog_duration(candidate) or 90.0,
                                               context=info)
        if lyrics is not False:
            return True
        return _skip(generator, candidate, "Нет готовых таймингов и проверенного оригинального текста.")
    if available is None:
        raise TemporaryUnavailable("Источники готовых таймингов временно недоступны.")
    if available is not False:
        return True
    return _skip(generator, candidate,
                 "Готовых таймингов этой песни нет ни в одном источнике; AI fallback выключен.",
                 remember=True)


def _skip(generator, candidate, reason, *, remember=False):
    if remember:
        generator.karaoke_resolver.rejections.put(
            rejection_key(generator, candidate, source=True), reason)
    pending = getattr(candidate, "_audio_download", None)
    if pending is not None:
        pending.cancel()
        candidate._audio_download = None
    generator.log(f"Караоке «{candidate.song_name}»: {reason} — беру следующую песню.")
    return False


def wait_for_sources(generator):
    """Пока караоке на паузе после череды сетевых отказов, задача ждёт.

    Слот караоке на паузе достаётся песне, только когда других свободных нет
    (см. EffectSlots.reserve), поэтому ждут лишь последние вопросы пака."""
    slots = getattr(generator, "_effect_slots", None)
    while slots is not None and slots.paused("karaoke") and not generator.stopped():
        time.sleep(min(1.0, slots.paused("karaoke")))


def init_service(generator):
    if generator.s.karaoke_enabled:
        generator.karaoke_resolver = Resolver(
            generator.session, generator.s, ap.FFMPEG, generator._run_killable,
            stopped=generator.stopped, log=generator.log, timed=generator._timed)


def manifest(songs):
    rows = []
    for candidate in songs:
        if candidate.music_effect != "karaoke":
            continue
        metadata = candidate.karaoke
        if not metadata:
            raise ValueError("Нельзя упаковать караоке без подтверждённых таймингов.")
        if not metadata.get("disabled") and not candidate.has_video:
            raise ValueError("Караоке не отрендерено.")
        rows.append({"file": candidate.video_out if candidate.has_video else candidate.audio_out,
                     "kind": candidate.base_kind, **metadata})
    return json.dumps({"version": 1, "questions": rows}, ensure_ascii=False, indent=2) if rows else ""
