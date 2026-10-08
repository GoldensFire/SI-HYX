"""Episode caption parsing and checks, including short WebVTT timestamps."""
from __future__ import annotations

import re

from .dialogue_questions import parse_subtitles, _decode as decode_text
from .dialogue_subdl import _decode as decode_russian


class CaptionRows(list):
    """Keep native Russian ASS layout alongside searchable caption text."""

    def __init__(self, rows, *, ass_document="", ass_start=0.0, ass_russian=False):
        super().__init__(rows)
        self.ass_document = ass_document
        self.ass_start = ass_start
        self.ass_russian = ass_russian


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
    rows = [(left, right, text) for left, right, text in parse_subtitles(data, name)
            if right > left >= 0 and text.strip()]
    if str(name).lower().endswith((".ass", ".ssa")):
        return CaptionRows(rows, ass_document=decode_text(data),
                           ass_russian=ru or russian(" ".join(row[2] for row in rows)))
    return rows


def cropped(rows, start, duration=15.0):
    end = start + duration
    selected = [(max(0, left - start), min(duration, right - start), text)
                for left, right, text in rows if left < end and right > start]
    if getattr(rows, "ass_document", ""):
        return CaptionRows(selected, ass_document=rows.ass_document,
                           ass_start=start, ass_russian=rows.ass_russian)
    return selected

