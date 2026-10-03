"""Choose a whole-word onset from authored syllable or word timing."""
from __future__ import annotations

import math


def word_starts(lines, offset=0.0):
    starts = []
    for line in lines:
        boundary = True
        for unit in line.units:
            text = unit.text
            if not text.strip():
                boundary = boundary or bool(text)
                continue
            if (boundary or text[:1].isspace()) and unit.end > unit.start:
                starts.append(unit.start + offset)
            # Adjacent timed syllables such as "ki" + "mi " form one word.
            boundary = text[-1:].isspace()
    return sorted(set(starts))


def aligned_start(lines, requested, duration, total_duration, *, offset=0.0):
    if not all(math.isfinite(x) for x in (requested, duration, total_duration, offset)):
        raise ValueError("Неверные границы караоке-отрезка.")
    if requested < 0 or duration <= 0 or total_duration <= 0:
        raise ValueError("Неверные границы караоке-отрезка.")
    starts = [x for x in word_starts(lines, offset) if 0 <= x < total_duration - 1]
    complete = [x for x in starts if x + duration <= total_duration]
    choices = complete or starts
    if not choices:
        raise ValueError("Нет начала целого слова в пределах записи.")
    # Ties go backwards so the requested word is heard in full.
    return min(choices, key=lambda x: (abs(x - requested), x))
