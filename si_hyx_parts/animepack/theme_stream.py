# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Bounded HTTP reads for a clip; complete-file transfer remains the fallback."""
from contextlib import nullcontext
import json
import math
import re

import animepack as api
from .generation_diagnostics import measuring
from .theme_http import GATE, WAITING, Stopped

# Запас копии после конца ролика, чтобы точная резка не упёрлась в конец файла.
FETCH_TAIL = 2
# Копию отрезка этим FFmpeg не сделать — повторять её бессмысленно.
UNSUPPORTED = "FFmpeg не поддерживает ограниченные HTTP-запросы"


def input_args(generator, executable):
    cached = getattr(generator, "_theme_protocol_args", {})
    if executable in cached:
        return cached[executable]
    # Один GET на копию: файл читается подряд с начала, а после конца отрезка
    # соединение закрывается. Блоками по 4 МиБ ffmpeg делал 6–10 запросов
    # подряд, и AnimeThemes отвечал на них 503: копия 15 с шла 20–72 с.
    # Замер 2026-10-08 (8 файлов подряд, пауза 3 с): блоки 4 МиБ — медиана
    # 48 с и 3–6 отказов на копию; один GET — 9,5 с и ни одного 503.
    options = ["-seekable", "0",
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


def yielding(generator):
    """Очередь и передача AnimeThemes — без места рабочей задачи (см. GenerationRuntime.yielding)."""
    runtime = getattr(generator, "_runtime", None)
    return runtime.yielding() if runtime is not None else nullcontext()


def brief(error, fallback=""):
    """Одна строка причины из stderr FFmpeg — для журнала.

    Раньше в журнал шли первые 160 символов stderr: баннер SVT-AV1
    («Svt[info]: SVT [version]…»), который печатается и при -loglevel error,
    или начало многострочной ошибки с адресами («[vf#0:0 @ 0000…]»)."""
    lines = [line.strip() for line in str(error or "").splitlines()]
    lines = [line for line in lines if line and not line.startswith("Svt[")]
    if not lines:
        return fallback
    line = re.sub(r"^(?:\[[^\]]*\]\s*)+", "", lines[-1]) or lines[-1]
    return line[:160]


def broken(error):
    return any(text in error.casefold() for text in
               ("file ended prematurely", "stream ends prematurely"))


def recovered(generator, error):
    statuses = sorted(set(re.findall(r"HTTP error (\d{3})", error)))
    if statuses:
        generator.log("AnimeThemes: передача восстановлена после HTTP "
                      + ", ".join(statuses) + ".")


def copy_short(generator, path, start, expected):
    """Секунд отрезка в копии, если она короче нужного; иначе None.

    Оборванную копию раньше сначала кодировали в AV1 (40–80 с у опенинга) и
    только по готовому ролику видели обрыв — после чего качали исходник
    целиком и кодировали заново. ffprobe по локальной копии — доли секунды."""
    code, output, _error = generator._run_capture(
        [api.FFPROBE, "-v", "error", "-show_entries",
         "packet=stream_index,pts_time,duration_time:stream=index,codec_type",
         "-of", "json", str(path)], timeout=30)
    try:
        data = json.loads(output)
        kinds = {row["index"]: row.get("codec_type") for row in data.get("streams", ())}
        first, ends = math.inf, {}
        for packet in data.get("packets", ()):
            kind = kinds.get(packet.get("stream_index"))
            if kind not in ("audio", "video") or "pts_time" not in packet:
                continue
            at = float(packet["pts_time"])
            first = min(first, at)
            ends[kind] = max(ends.get(kind, at), at + float(packet.get("duration_time") or 0))
    except (TypeError, ValueError, KeyError, AttributeError):
        return None
    if code or set(ends) != {"audio", "video"} or not math.isfinite(first):
        return None     # не разобрать — решит проверка готового ролика
    # Копия идёт с начала файла, метки — исходника. Считается кусок от start
    # до конца копии; если копия начинается позже start, кусок короче.
    got = min(ends.values()) - max(start, first)
    return got if got < expected - .3 else None


def remote_length(generator, url, args):
    with generator._video_len_lock:
        known = generator._video_len.get(url)
    if known is not None and known > 0:
        return known, ""
    command = [api.FFPROBE, "-v", "error"] + args + [
        "-show_entries", "format=duration", "-of",
        "default=noprint_wrappers=1:nokey=1", url]
    with yielding(generator), GATE.slot(generator.stopped, measuring(generator, WAITING)):
        code, output, error = generator._run_capture(command, timeout=60)
        try:
            seconds = float(output.strip())
        except (TypeError, ValueError):
            seconds = 0.0
        if code or broken(error) or not math.isfinite(seconds) or seconds <= 0:
            GATE.defer(8)
            return 0.0, brief(error, "не получена длительность")
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
        return False, UNSUPPORTED
    total, error = remote_length(generator, url, probe_args)
    if total <= 0:
        return False, error
    duration = max(3, int(generator.s.video_cut))
    start = generator._video_start(candidate, url, duration)
    expected = min(duration, max(0.0, total - start))
    local = final.with_name(final.stem + ".source.mkv")
    try:
        # Копия с НАЧАЛА файла до start + отрезок. С -seekable 0 ffmpeg не
        # перематывает: -ss до -i заставлял демультиплексор WebM
        # «пересинхронизироваться» вперёд, и копия начиналась на 2–10 с позже
        # start («ролик оборвался: 12.52 с вместо 15», до 19 раз за прогон).
        # Байтов столько же — без перемотки начало файла читалось и так.
        fetch = ([api.FFMPEG, "-y", "-loglevel", "error"] + ffmpeg_args
                 + ["-i", url, "-t", str(start + duration + FETCH_TAIL),
                    "-c", "copy", "-sn", "-dn", str(local)])
        with yielding(generator), GATE.slot(generator.stopped, measuring(generator, WAITING)):
            code, error = generator._run_killable(fetch, timeout=180)
            if code or broken(error):
                GATE.defer(8)
        if generator.stopped():
            raise Stopped("Загрузка AnimeThemes остановлена")
        if code or broken(error) or not local.is_file() or not local.stat().st_size:
            final.unlink(missing_ok=True)
            if broken(error):
                error = "поток AnimeThemes оборвался до конца ролика"
            return False, brief(error, "пустая копия отрезка")
        recovered(generator, error)
        short = copy_short(generator, local, start, expected)
        if short is not None:
            final.unlink(missing_ok=True)
            return False, f"копия отрезка оборвалась: {max(0.0, short):.2f} с вместо {expected:.2f} с"
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
    return False, brief(error, "пустой файл")
