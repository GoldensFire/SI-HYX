"""Centered caption blocks without overlapping preview lines or duet voices."""
from __future__ import annotations


def positions(lines, height, size, *, translations=False):
    windows = []
    previous_end = 0.0
    for index, line in enumerate(lines):
        onset = next((unit.start for unit in line.units
                      if unit.end > unit.start and unit.text.strip()), line.start)
        # ASS often previews the next phrase while the previous one is sung.
        # Delay that preview, keeping every sung syllable on its original clock.
        start = max(line.start, min(previous_end, onset))
        windows.append((start, line.end, index))
        previous_end = max(previous_end, line.end)
    groups = []
    for window in sorted(windows):
        if not groups or window[0] >= max(row[1] for row in groups[-1]):
            groups.append([])
        groups[-1].append(window)
    result = {}
    for group in groups:
        ends, lanes = [], {}
        for start, end, index in group:
            lane = next((i for i, value in enumerate(ends) if value <= start), len(ends))
            if lane == len(ends):
                ends.append(end)
            else:
                ends[lane] = end
            lanes[index] = lane
        step = size * (2.8 if translations and any(lines[i].translation for _, _, i in group) else 1.6)
        for start, _, index in group:
            center = height / 2 + (lanes[index] - (len(ends) - 1) / 2) * step
            separation = size * .6 if translations and lines[index].translation else 0
            result[index] = (start, round(center - separation), round(center + separation))
    return result
