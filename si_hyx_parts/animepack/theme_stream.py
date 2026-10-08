# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Bounded HTTP reads for a clip; complete-file transfer remains the fallback."""
import math
import re

import animepack as api
from .theme_http import GATE, Stopped

BLOCK = 4 * 1024 * 1024
# Запас копии после конца ролика, чтобы точная резка не упёрлась в конец файла.
FETCH_TAIL = 2


def input_args(generator, executable):
    cached = getattr(generator, "_theme_protocol_args", {})
    if executable in cached:
        return cached[executable]
    options = ["-initial_request_size", "65536", "-request_size", str(BLOCK),
               "-short_seek_size", str(BLOCK), "-multiple_requests", "1",
               "-rw_timeout", "10000000", "-reconnect", "1",
               "-reconnect_on_network_error", "1",
               "-reconnect_on_http_error", "429,5xx", "-reconnect_streamed", "1",
               "-reconnect_delay_max", "8", "-reconnect_max_retries", "4",
               "-reconnect_delay_total_max", "30", "-respect_retry_after", "1"]
    code, output, error = generator._run_capture(
        [executable, "-hide_banner", "-h", "protocol=http"], timeout=10)
    help_text = output + error
    # rw_timeout is a generic AVIO option and is absent from protocol=http help.
    flags = [flag for flag in options[::2] if flag != "-rw_timeout"]
    supported = code == 0 and all(flag in help_text for flag in flags)
    cached[executable] = options if supported else None
    generator._theme_protocol_args = cached
    return cached[executable]


def broken(error):
    return any(text in error.casefold() for text in
               ("file ended prematurely", "stream ends prematurely"))


def recovered(generator, error):
    statuses = sorted(set(re.findall(r"HTTP error (\d{3})", error)))
    if statuses:
        generator.log("AnimeThemes: передача восстановлена после HTTP "
                      + ", ".join(statuses) + ".")


def remote_length(generator, url, args):
    with generator._video_len_lock:
        known = generator._video_len.get(url)
    if known is not None and known > 0:
        return known, ""
    command = [api.FFPROBE, "-v", "error"] + args + [
        "-show_entries", "format=duration", "-of",
        "default=noprint_wrappers=1:nokey=1", url]
    with GATE.slot(generator.stopped):
        code, output, error = generator._run_capture(command, timeout=60)
        try:
            seconds = float(output.strip())
        except (TypeError, ValueError):
            seconds = 0.0
        if code or broken(error) or not math.isfinite(seconds) or seconds <= 0:
            GATE.defer(8)
            return 0.0, error.strip()[:160] or "не получена длительность"
    with generator._video_len_lock:
        generator._video_len[url] = seconds
    recovered(generator, error)
    return seconds, ""


def remote_encode(generator, candidate, url, final, validate):
    """Копия отрезка под общим шлюзом, затем AV1 уже с диска.

    Кодирование прямо из сети держало и шлюз AnimeThemes, и слот AV1 на всё
    время кодирования: ролики шли строго по одному (6 мин 40 с на пак), а
    кодировщик ждал сеть. Копия без перекодирования качается за секунды."""
    ffmpeg_args = input_args(generator, api.FFMPEG)
    probe_args = input_args(generator, api.FFPROBE)
    if ffmpeg_args is None or probe_args is None:
        return False, "FFmpeg не поддерживает ограниченные HTTP-запросы"
    total, error = remote_length(generator, url, probe_args)
    if total <= 0:
        return False, error
    duration = max(3, int(generator.s.video_cut))
    start = generator._video_start(candidate, url, duration)
    expected = min(duration, max(0.0, total - start))
    local = final.with_name(final.stem + ".source.mkv")
    try:
        # Как у отрывков серий: -t до -i, исходные метки сохраняются, поэтому
        # -seek_timestamp ниже режет ровно с start, как прямая резка из сети.
        fetch = ([api.FFMPEG, "-y", "-loglevel", "error"] + ffmpeg_args
                 + ["-ss", str(start), "-t", str(duration + FETCH_TAIL), "-i", url,
                    "-c", "copy", "-sn", "-dn", "-copyts", "-start_at_zero", str(local)])
        with GATE.slot(generator.stopped):
            code, error = generator._run_killable(fetch, timeout=180)
            if code or broken(error):
                GATE.defer(8)
        if generator.stopped():
            raise Stopped("Загрузка AnimeThemes остановлена")
        if code or broken(error) or not local.is_file() or not local.stat().st_size:
            final.unlink(missing_ok=True)
            if broken(error):
                error = "поток AnimeThemes оборвался до конца ролика"
            return False, error.strip()[:160] or "пустая копия отрезка"
        recovered(generator, error)
        command = ([api.FFMPEG, "-y", "-loglevel", "error", "-seek_timestamp", "1",
                    "-ss", str(start), "-i", str(local), "-t", str(duration)]
                   + generator.video_encode_args() + generator.opus_args(duration)
                   + ["-movflags", "+faststart", str(final)])
        code, error = generator._run_killable(command, timeout=600)
    finally:
        local.unlink(missing_ok=True)
    if generator.stopped():
        raise Stopped("Загрузка AnimeThemes остановлена")
    if code == 0 and final.is_file():
        if final.stat().st_size >= api.MIN_VIDEO_BYTES:
            good, reason = validate(generator, final, expected)
            if good:
                return True, ""
            error = reason
    final.unlink(missing_ok=True)
    return False, error.strip()[:160] or "пустой файл"
