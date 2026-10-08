"""Recover bilingual acoustic anchors without duplicate verses or invented times."""
from difflib import SequenceMatcher

from .asr_phrases import key


def combine(primary, secondary, original, *, normalizer=key):
    """Choose a maximum-coverage monotone chain of existing word anchors."""
    def score(row):
        expected = normalizer(original[row["line_index"]])
        return SequenceMatcher(None, expected, normalizer(row["text"]), autojunk=False).ratio()
    rows = sorted([*primary, *secondary], key=lambda row: (row["line_index"], row["start"]))
    best, previous = [], []
    for i, row in enumerate(rows):
        weight = score(row)
        value, parent = (1, weight), -1
        for j in range(i):
            if rows[j]["line_index"] < row["line_index"] and rows[j]["end"] <= row["start"]:
                candidate = (best[j][0] + 1, best[j][1] + weight)
                if candidate > value:
                    value, parent = candidate, j
        best.append(value)
        previous.append(parent)
    if not rows:
        return []
    index = max(range(len(rows)), key=lambda i: best[i])
    result = []
    while index >= 0:
        result.append(rows[index])
        index = previous[index]
    return result[::-1]
