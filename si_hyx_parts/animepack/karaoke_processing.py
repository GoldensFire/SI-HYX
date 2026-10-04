"""Karaoke presentation of opening/ending/insert song slots."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile

import animepack as ap
from karaoke.crop import aligned_start
from karaoke.render import render, reverse_audio, tempo
from karaoke.resolver import Resolver
from karaoke.timeline import transform
from karaoke.style import choose_colour, font_size, FONT_NAME
from karaoke.rejections import Rejected, SourceRejected, cache_key, AI_POLICY
from karaoke.search import context, SEARCH_POLICY
from .song_downloads import source_bytes


def rejection_key(generator, candidate, *, source=False):
    values = ["candidate-source" if source else "candidate", candidate.audio_file,
              candidate.song_name, candidate.artist, bool(generator.s.karaoke_ai_fallback),
              SEARCH_POLICY, context(candidate.song, candidate.anime, candidate.kind)]
    if generator.s.karaoke_ai_fallback:
        values.append(AI_POLICY)
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
    try:
        rejected = known_rejection(generator, candidate)
        if rejected:
            generator.log(f"Караоке «{candidate.song_name}»: недельный кэш отказов — {rejected}")
            return False
        if not candidate.audio_file:
            return False
        with tempfile.TemporaryDirectory(prefix="karaoke-", dir=generator.folder) as directory:
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
            start = aligned_start(lines, requested, float(generator.s.audio_cut),
                                  metadata["duration"], offset=metadata["offset"])
            duration = min(float(generator.s.audio_cut), metadata["duration"] - start)
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
            generator.log(f"Караоке «{candidate.song_name}»: {metadata['source']}, "
                          f"{len(cropped)} строк, версия аудио подтверждена.")
            return True
    except Exception as error:
        if isinstance(error, Rejected) and not generator.stopped():
            key = rejection_key(generator, candidate, source=isinstance(error, SourceRejected))
            generator.karaoke_resolver.rejections.put(key, error)
        final.unlink(missing_ok=True)
        generator.log(f"Караоке «{candidate.song_name}»: {error} — беру следующую песню.")
        return False


def init_service(generator):
    if generator.s.karaoke_enabled:
        generator.karaoke_resolver = Resolver(
            generator.session, generator.s, ap.FFMPEG, generator._run_killable,
            stopped=generator.stopped, log=generator.log)


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
