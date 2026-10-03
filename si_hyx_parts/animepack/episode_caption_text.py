"""Episode caption parsing and checks, including short WebVTT timestamps."""
from __future__ import annotations

import re

from .dialogue_questions import parse_subtitles, _decode as decode_text
from .dialogue_subdl import _decode as decode_russian


def russian(text):
    letters = re.findall(r"[^\W\d_]", text, re.UNICODE)
    cyrillic = re.findall("[А-Яа-яЁё]", text)
    return bool(cyrillic) and len(cyrillic) >= len(letters) * 0.6


def parse(data, name, *, ru=False):
    data = decode_russian(data) if ru else data
    if str(name).lower().endswith(".vtt") or data.lstrip().startswith(b"WEBVTT"):
        text = decode_text(data)
        # WebVTT allows mm:ss.mmm; SRT/ASS's shared parser requires hours.
        text = re.sub(r"(?<![\d:])(\d{2}:\d{2}\.\d{3})(?![\d:])", r"00:\1", text)
        data = text.encode("utf-8")
        name = "captions.srt"
    return [(left, right, text) for left, right, text in parse_subtitles(data, name)
            if right > left >= 0 and text.strip()]


def cropped(rows, start, duration=15.0):
    end = start + duration
    return [(max(0, left - start), min(duration, right - start), text)
            for left, right, text in rows if left < end and right > start]

