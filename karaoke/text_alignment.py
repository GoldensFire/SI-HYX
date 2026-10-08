"""Monotonic text alignment transfers authored intervals onto external Romaji."""
from difflib import SequenceMatcher

from .model import Line, Unit, normalize, validate
from .romanization import romanize_units
from .phonetic_units import timed_readings
from .identity import identity_key


def mapping(left, right, *, floor, label):
    matcher = SequenceMatcher(None, left, right, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    coverage = matched / max(1, len(left))
    if not left or not right or coverage < floor:
        raise ValueError(f"Text alignment: {label}, покрытие {coverage:.1%} ниже {floor:.0%}.")
    # Match only exact anchors. Insertions/replacements are carried inside a
    # bounded interval only when that entire lyric line is verified below.
    result = {}
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            result[block.a + offset] = block.b + offset
    return result, coverage


def boundaries(left, right):
    """Map text boundaries, retaining substitutions in the external spelling."""
    result = {}
    for tag, a, b, c, d in SequenceMatcher(None, left, right, autojunk=False).get_opcodes():
        if a == b:
            # An inserted word belongs to the following interval.
            result[a] = c
            continue
        for i in range(a, b + 1):
            result[i] = c + round((d - c) * (i - a) / (b - a))
    return result


def transfer(timed, sheet):
    original = "".join(identity_key(line.text) for line in timed.lines)
    native = "".join(identity_key(line) for line in sheet.original)
    native_map, native_coverage = mapping(original, native, floor=.97, label="JP")
    # Kana/kanji readings only locate external Romaji. The displayed text always
    # comes from Uta-Net. Several character intervals within a kanji word are
    # joined into their real word interval rather than inventing syllable times.
    rows = [timed_readings(line.units) if timed.level != "line" else [] for line in timed.lines]
    if timed.level == "line":
        rows = [romanize_units([Unit(line.start, line.end, line.text)]) for line in timed.lines]
    expected = "".join(normalize(u.text) for units in rows for u in units)
    roman = " ".join(sheet.romaji)
    positions = [i for i, char in enumerate(roman) if normalize(char)]
    actual = "".join(normalize(char) for char in roman)
    if len(positions) != len(actual):
        raise ValueError("Text alignment: неоднозначная Unicode-нормализация Romaji.")
    roman_map, roman_coverage = mapping(expected, actual, floor=.90, label="Romaji")
    edges = boundaries(expected, actual)
    output, native_cursor, roman_cursor, last_target = [], 0, 0, -1
    line_scores = []
    for source, units in zip(timed.lines, rows):
        length = len(identity_key(source.text))
        native_hits = [native_map[i] for i in range(native_cursor, native_cursor + length)
                       if i in native_map]
        native_cursor += length
        if len(native_hits) / max(1, length) < .94:
            raise ValueError("Text alignment: строка JP не подтверждена.")
        line_size = sum(len(normalize(u.text)) for u in units)
        hits = [roman_map[i] for i in range(roman_cursor, roman_cursor + line_size) if i in roman_map]
        line_scores.append(len(hits) / max(1, line_size))
        # Large skipped passages signal a different verse/edit, not typography.
        target_size = edges[roman_cursor + line_size] - edges[roman_cursor]
        if target_size <= 0 or target_size > line_size * 1.25 + 4:
            raise ValueError("Text alignment: лишние слова в версии Romaji.")
        mapped = []
        for unit in units:
            size = len(normalize(unit.text))
            first, after = edges[roman_cursor], edges[roman_cursor + size]
            roman_cursor += size
            if not size:
                continue
            if first <= last_target:
                raise ValueError("Text alignment: нарушен порядок повторяющихся фраз.")
            if first == after:
                # Deleted dictionary spelling has no target text. Keep its
                # authored time with its preceding word, not a fabricated cue.
                if mapped:
                    previous = mapped[-1]
                    mapped[-1] = Unit(previous.start, unit.end, previous.text)
                continue
            end = after - 1
            # Adjacent units own spaces/punctuation after the previous word.
            start = positions[first] if not mapped else positions[last_target] + 1
            stop = positions[end] + 1
            text = roman[start:stop]
            mapped.append(Unit(unit.start, unit.end, text))
            last_target = end
        if timed.level == "line":
            mapped = [Unit(source.start, source.end, "".join(u.text for u in mapped))]
        output.append(Line(source.start, source.end, mapped, cutoff=source.cutoff))
    return validate(output), {"jp_coverage": native_coverage, "romaji_coverage": roman_coverage,
                              "minimum_line_reading_coverage": min(line_scores),
                              "timing_level": timed.level, "method": "monotonic-text-alignment"}
