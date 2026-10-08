"""Decode PetitLyrics WSY and LSY; plain text is never a timing source."""
from dataclasses import dataclass
import math
import struct
from xml.etree import ElementTree as ET

from .model import Line, Unit, normalize
from .identity import identity_key


@dataclass
class TimedLyrics:
    lines: list[Line]
    level: str


def word_sync(payload, duration):
    try:
        tree = ET.fromstring(payload)
    except ET.ParseError as error:
        raise ValueError("PetitLyrics: повреждённый WSY XML.") from error
    if tree.tag != "wsy":
        raise ValueError("PetitLyrics: ответ не содержит WSY-тайминги.")
    lines = []
    for row in tree.findall("line"):
        text = row.findtext("linestring") or ""
        if not normalize(text):
            continue
        units = [Unit(float(w.findtext("starttime")) / 1000,
                      float(w.findtext("endtime")) / 1000, w.findtext("wordstring") or "")
                 for w in row.findall("word")]
        if not units or identity_key("".join(u.text for u in units)) != identity_key(text):
            raise ValueError("PetitLyrics: текст строки и символов расходится.")
        lines.append(Line(units[0].start, units[-1].end, units))
    return checked(lines, duration, "character" if all(len(u.text) <= 1
                   for line in lines for u in line.units) else "word")


def line_times(payload):
    if len(payload) < 204 or not payload.startswith(b"MHDROBJT"):
        raise ValueError("PetitLyrics: неизвестный формат синхронизации.")
    count = struct.unpack_from("<I", payload, 56)[0]
    width = struct.unpack_from("<H", payload, 66)[0]
    if not 0 < count <= 10000 or len(payload) != 204 + count * (2 + width):
        raise ValueError("PetitLyrics: повреждённый LSY-контейнер.")
    key = struct.unpack_from("<H", payload, 26)[0]
    if payload[25]:
        # Vendor swaps inner adjacent bit pairs; outer pairs stay in place.
        pairs = [(key >> bit) & 3 for bit in range(0, 16, 2)]
        key = sum(pairs[old] << (2 * new) for new, old in enumerate((0, 2, 1, 4, 3, 6, 5, 7)))
    result, previous, wraps = [], 0, 0
    for raw in struct.unpack_from(f"<{count}H", payload, 204):
        value = raw ^ key
        if value < previous:
            # Only a real 16-bit rollover is allowed, not arbitrary bad ordering.
            if previous < 60000 or value > 5000:
                raise ValueError("PetitLyrics: LSY-тайминги идут назад.")
            wraps += 65536
        result.append((value + wraps) / 100)
        previous = value
    return result


def line_sync(payload, text, duration):
    times = line_times(payload)
    rows = text.replace("\r\n", "\n").split("\n")
    while len(rows) > len(times) and not rows[-1].strip():
        rows.pop()
    if len(times) != len(rows):
        raise ValueError("PetitLyrics: число строк текста и LSY не совпадает.")
    lines = []
    for i, (start, row) in enumerate(zip(times, rows)):
        if not normalize(row):
            continue
        end = times[i + 1] if i + 1 < len(times) else duration
        lines.append(Line(start, end, [Unit(start, end, row)]))
    return checked(lines, duration, "line")


def checked(lines, duration, level):
    previous = -1
    if not lines:
        raise ValueError("PetitLyrics: нет синхронных строк.")
    for line in lines:
        if line.start < previous or not 0 <= line.start < line.end <= duration + .1:
            raise ValueError("PetitLyrics: тайминги не соответствуют длительности версии.")
        previous, cursor = line.start, line.start
        for unit in line.units:
            if (not all(math.isfinite(t) for t in (unit.start, unit.end))
                    or unit.start < cursor - .015 or unit.end < unit.start or unit.end > line.end):
                raise ValueError("PetitLyrics: неверный порядок символов.")
            cursor = unit.end
    return TimedLyrics(lines, level)
