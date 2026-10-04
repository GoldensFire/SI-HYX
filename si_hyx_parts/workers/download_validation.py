# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Verify actual media tracks rather than trusting the container duration."""
import math


class DownloadValidationError(RuntimeError):
    def __init__(self, message, *, incomplete=False):
        super().__init__(message)
        self.incomplete = incomplete


def positive_seconds(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError):
        return None


def track_duration(stream):
    duration = positive_seconds(stream.get("duration"))
    if duration is not None:
        return duration
    try:
        numerator, denominator = stream["time_base"].split("/")
        duration = positive_seconds(
            float(stream["duration_ts"]) * float(numerator) / float(denominator))
        if duration is not None:
            return duration
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        pass
    try:
        h, m, s = stream.get("tags", {}).get("DURATION", "").split(":")
        return positive_seconds(int(h) * 3600 + int(m) * 60 + float(s))
    except (TypeError, ValueError):
        return None


def expected_duration(source_duration, start=None, end=None):
    source = positive_seconds(source_duration)
    stop = positive_seconds(end)
    if source is not None:
        stop = min(source, stop) if stop is not None else source
    if stop is None:
        return None
    return positive_seconds(stop - (positive_seconds(start) or 0))


def validate_streams(info, *, audio_only=False, expect_audio=None, duration=None):
    streams = info.get("streams") or []
    video = [s for s in streams if s.get("codec_type") == "video"
             and not s.get("disposition", {}).get("attached_pic")]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    if not audio_only and not video:
        raise DownloadValidationError(
            "Скачанный файл не содержит видеодорожку.", incomplete=True)
    if (audio_only or expect_audio) and not audio:
        raise DownloadValidationError(
            "Скачанный файл не содержит ожидаемую аудиодорожку.", incomplete=True)
    selected = audio if audio_only else video + audio
    if not selected:
        raise DownloadValidationError("Скачанный файл не содержит медиа.", incomplete=True)
    durations = [(s["codec_type"], track_duration(s)) for s in selected]
    actual = positive_seconds(info.get("format", {}).get("duration"))
    required = positive_seconds(duration) or actual
    if required is None:
        if not any(d for _, d in durations):
            raise DownloadValidationError(
                "Не удалось проверить длительность скачанного файла.")
        required = max(d for _, d in durations if d is not None)
    tolerance = max(2.0, min(5.0, required * 0.02))
    for kind, length in durations:
        if length is not None and length + tolerance < required:
            name = "Звук" if kind == "audio" else "Видео"
            raise DownloadValidationError(
                f"{name} скачан не полностью: {length:.1f} из {required:.1f} сек.",
                incomplete=True)
    if actual is not None and actual + tolerance < required:
        raise DownloadValidationError(
            f"Файл скачан не полностью: {actual:.1f} из {required:.1f} сек.",
            incomplete=True)
