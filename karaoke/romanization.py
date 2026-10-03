"""Dictionary readings preserve the authored timing of a complete word."""
from __future__ import annotations

import re
import threading
from .model import Unit

_context = threading.local()


def readings(text):
    try:
        from pykakasi import kakasi
        from sudachipy import dictionary, tokenizer
    except ImportError as error:
        raise ValueError("Для японских ASS/TTML без romaji нужны Sudachi и pykakasi.") from error
    if not hasattr(_context, "tokenizer"):
        _context.tokenizer = dictionary.Dictionary().create()
        _context.romanizer = kakasi()
    result = []
    for token in _context.tokenizer.tokenize(text, tokenizer.Tokenizer.SplitMode.C):
        surface = token.surface()
        reading = token.reading_form() or surface
        if token.part_of_speech()[0] == "助詞":
            reading = {"は": "ワ", "へ": "エ", "を": "オ"}.get(surface, reading)
        if not re.search(r"[\u3040-\u30ff\u3400-\u9fff]", surface):
            roman = surface
        else:
            roman = "".join(item["hepburn"] for item in _context.romanizer.convert(reading))
        result.append({"orig": surface, "hepburn": roman})
    return result


def romanize_units(units):
    text = "".join(unit.text for unit in units)
    if not re.search(r"[\u3040-\u30ff\u3400-\u9fff]", text):
        return units
    result, position = [], 0
    spans = []
    for unit in units:
        spans.append((position, position + len(unit.text), unit))
        position += len(unit.text)
    cursor = 0
    for word in readings(text):
        original, reading = word["orig"], word["hepburn"]
        end = cursor + len(original)
        covered = [unit for start, stop, unit in spans if stop > cursor and start < end]
        if covered:
            new = Unit(covered[0].start, covered[-1].end, reading + " ")
            # A provider's single word may have several dictionary readings.
            # Keep that authored interval as one sweep rather than overlapping
            # independently interpolated pronunciation fragments.
            if result and new.start < result[-1].end - .015:
                previous = result[-1]
                result[-1] = Unit(previous.start, max(previous.end, new.end), previous.text + new.text)
            else:
                result.append(new)
        cursor = end
    if cursor != len(text):
        raise ValueError("Не удалось сопоставить чтение со строкой караоке.")
    return result
