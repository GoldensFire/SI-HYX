"""Portable lyric intervals on the unmodified recording's clock."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import re


@dataclass(frozen=True)
class Unit:
    start: float
    end: float
    text: str


@dataclass
class Line:
    start: float
    end: float
    units: list[Unit]
    translations: dict[str, str] = field(default_factory=dict)
    cutoff: float | None = None

    @property
    def visible_end(self):
        return self.end if self.cutoff is None else min(self.end, self.cutoff)

    @property
    def text(self):
        return "".join(unit.text for unit in self.units)

    @property
    def translation(self):
        return self.translations.get("ru") or self.translations.get("en") or ""


@dataclass
class Track:
    title: str
    artists: list[str]
    duration: float
    source: str
    lyrics_url: str
    audio_url: str
    format: str = "ass"
    aliases: list[str] = field(default_factory=list)
    version: str = ""
    payload: bytes = b""


def validate(lines):
    if not lines:
        raise ValueError("Нет строк с пословными или послоговыми таймингами.")
    previous = -1.0
    for line in lines:
        if (not all(math.isfinite(t) for t in (line.start, line.end))
                or line.start < 0 or line.end <= line.start or line.start < previous):
            raise ValueError("Неверный порядок строк караоке.")
        previous = line.start
        if ((line.cutoff is not None and not math.isfinite(line.cutoff))
                or not math.isfinite(line.visible_end) or line.visible_end <= line.start):
            raise ValueError("Неверная граница показа строки караоке.")
        cursor = line.start
        if not line.units or not line.text.strip():
            raise ValueError("Пустая строка караоке.")
        for unit in line.units:
            if (not all(math.isfinite(t) for t in (unit.start, unit.end))
                    or unit.start < cursor - .015 or unit.end < unit.start
                    or unit.end > line.end + .015):
                raise ValueError("Тайминги слогов выходят за границы строки.")
            cursor = unit.end
        if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", line.text):
            raise ValueError("Основная строка должна быть romaji.")
    return lines


def normalize(text):
    import unicodedata
    text = unicodedata.normalize("NFKD", str(text)).casefold()
    return "".join(c for c in text if c.isalnum() and not unicodedata.combining(c))
