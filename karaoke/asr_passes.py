"""Recover bilingual acoustic anchors without duplicate verses or invented times."""
from difflib import SequenceMatcher

from .asr_phrases import key


def combine(primary, secondary, original):
    chosen = {}
    def score(row):
        expected = key(original[row["line_index"]])
        return SequenceMatcher(None, expected, key(row["text"]), autojunk=False).ratio()
    for row in [*primary, *secondary]:
        index = row["line_index"]
        if index not in chosen or score(row) > score(chosen[index]):
            chosen[index] = row
    result, previous = [], -1
    for index in sorted(chosen):
        row = chosen[index]
        if row["start"] < previous:
            continue
        result.append(row)
        previous = row["end"]
    return result
