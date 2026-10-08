"""Retain authored kana mora intervals; group ambiguous kanji into words."""
import re

from .model import Unit, normalize
from .romanization import readings

_KANA = re.compile(r"^[\u3040-\u30ffー]+$")
_SMALL = "ぁぃぅぇぉゃゅょァィゥェォャュョー"


def timed_readings(units):
    text = "".join(unit.text for unit in units)
    spans, cursor = [], 0
    for unit in units:
        spans.append((cursor, cursor + len(unit.text), unit))
        cursor += len(unit.text)
    result, cursor = [], 0
    for word in readings(text):
        surface, roman = word["orig"], word["hepburn"]
        fragments = [(surface, roman)]
        if len(surface) > 1 and _KANA.fullmatch(surface):
            morae = []
            for character in surface:
                if character in _SMALL and morae:
                    morae[-1] += character
                else:
                    morae.append(character)
            candidates = [(mora, "".join(item["hepburn"] for item in readings(mora)))
                          for mora in morae]
            if normalize("".join(roman for _, roman in candidates)) == normalize(roman):
                fragments = candidates
        for original, pronunciation in fragments:
            end = cursor + len(original)
            covered = [unit for start, stop, unit in spans if stop > cursor and start < end]
            if covered:
                new = Unit(covered[0].start, covered[-1].end, pronunciation)
                if result and new.start < result[-1].end - .015:
                    previous = result[-1]
                    result[-1] = Unit(previous.start, max(previous.end, new.end), previous.text + new.text)
                else:
                    result.append(new)
            cursor = end
    if cursor != len(text):
        raise ValueError("PetitLyrics: чтение не покрывает японскую строку.")
    return result
