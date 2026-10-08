# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Bounded clip reads with a complete-file fallback and output validation."""
import json
import math
from pathlib import Path
import tempfile

import animepack as api
from .generation_diagnostics import operation
from .theme_http import download, SourceError, Stopped
from .theme_stream import remote_encode


@operation("скачивание")
def source_file(generator, url, path):
    return download(generator.session, url, path, generator.stopped,
                    generator.log, getattr(generator, "_diagnostics", None))


def complete_output(generator, path, expected):
    command = [api.FFPROBE, "-v", "error", "-show_entries",
               "format=duration:stream=codec_type,duration", "-of", "json", str(path)]
    code, output, error = generator._run_capture(command, timeout=30)
    try:
        data = json.loads(output)
        seconds = float(data.get("format", {}).get("duration", 0))
        kinds = {row.get("codec_type") for row in data.get("streams", [])}
        lengths = [float(row.get("duration", seconds)) for row in data.get("streams", [])
                   if row.get("codec_type") in ("audio", "video")]
    except (TypeError, ValueError, AttributeError):
        return False, "не удалось проверить готовый ролик"
    if code or not {"video", "audio"} <= kinds:
        return False, error.strip()[:160] or "в ролике отсутствует видео или звук"
    if not math.isfinite(seconds) or seconds <= 0 or seconds < max(0.0, expected - .3):
        return False, f"ролик оборвался: {seconds:.2f} с вместо {expected:.2f} с"
    if seconds > expected + .6:
        return False, f"неверная длительность ролика: {seconds:.2f} с вместо {expected:.2f} с"
    if any(not math.isfinite(value) or value < expected - .3 for value in lengths):
        return False, "видео или звук короче запрошенного отрывка"
    # A complete container can still contain damaged packets. Decode both tracks.
    code, _, error = generator._run_capture(
        [api.FFMPEG, "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"],
        timeout=90)
    if code or error.strip():
        return False, error.strip()[:160] or "готовый ролик не декодируется"
    return True, ""


def encode(generator, candidate, source, final):
    duration = max(3, int(generator.s.video_cut))
    start = generator._video_start(candidate, str(source), duration)
    total = generator._video_seconds(str(source))
    if not math.isfinite(total) or total <= 0:
        return False, "не удалось определить длительность скачанного ролика"
    error = ""
    for attempt in range(api.VIDEO_RETRIES + 1):
        if generator.stopped():
            return False, "остановлено"
        seek = start if attempt == 0 else 0
        expected = min(duration, max(0.0, total - seek))
        command = ([api.FFMPEG, "-y", "-loglevel", "error", "-ss", str(seek),
                    "-i", str(source), "-t", str(duration)]
                   + generator.video_encode_args() + generator.opus_args(duration)
                   + ["-movflags", "+faststart", str(final)])
        code, error = generator._run_killable(command, timeout=600)
        broken = any(text in error.casefold() for text in
                     ("file ended prematurely", "stream ends prematurely"))
        if code == 0 and final.exists() and final.stat().st_size >= api.MIN_VIDEO_BYTES:
            if not broken:
                good, error = complete_output(generator, final, expected)
                if good:
                    return True, ""
        if broken:
            error = "поток AnimeThemes оборвался до конца ролика"
        final.unlink(missing_ok=True)
    return False, error.strip()[:160] or "пустой файл"


def download_video(generator, candidate):
    candidate.has_video = candidate.theme_video_ready = False
    url = generator._theme_video(candidate)
    if not url:
        if not generator.stopped():
            generator.log(f"Ролик «{candidate.title_ru}» не найден на AnimeThemes "
                          f"для {candidate.tag} — беру аудио песни.")
        return False
    candidate.video_url = url
    final = Path(generator.folder) / "Video" / candidate.video_out
    try:
        good, error = remote_encode(generator, candidate, url, final, complete_output)
        if good:
            candidate.has_video = candidate.theme_video_ready = True
            return True
        if generator.stopped():
            return False
        generator.log(f"AnimeThemes: {error}. Скачиваю исходник целиком "
                      f"для «{candidate.title_ru}».")
        # This directory is created under the generator's own temporary workspace.
        with tempfile.TemporaryDirectory(prefix="theme_", dir=generator.folder) as folder:
            source = Path(folder) / "source.webm"
            source_file(generator, url, source)
            good, error = encode(generator, candidate, source, final)
            if good:
                candidate.has_video = candidate.theme_video_ready = True
                return True
    except Stopped:
        final.unlink(missing_ok=True)
        return False
    except (SourceError, OSError) as failure:
        error = str(failure)
    final.unlink(missing_ok=True)
    if not generator.stopped():
        generator.log(f"Ролик «{candidate.title_ru}» не получен: {error} "
                      "— беру аудио песни.")
    return False
