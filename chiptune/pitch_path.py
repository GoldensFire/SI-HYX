"""Semitone path with tuning correction; timing follows the recording."""
from __future__ import annotations

import numpy as np


def stable_pitches(midi, confidence, valid, *, low=45, high=90, hop=.01):
    """Discourage vibrato retriggers, while retaining sustained semitone steps.

    A transition costs roughly 40 ms of a one-semitone disagreement. This is
    independent of tempo. Unvoiced spans split paths and remain unvoiced.
    """
    result = np.full(len(midi), -1, dtype=int)
    reliable = valid & (confidence >= .65)
    offset = 0.
    if reliable.sum() >= 20:
        tuning = np.mean(np.exp(2j * np.pi * midi[reliable]))
        if abs(tuning) >= .55:
            offset = float(np.angle(tuning) / (2 * np.pi))
    values = midi - offset
    states = np.arange(low, high + 1)
    changes = np.r_[0, np.flatnonzero(np.diff(valid)) + 1, len(valid)]
    for start, end in zip(changes[:-1], changes[1:]):
        if not valid[start]:
            continue
        # Cap the effect of a short gross pitch error or transition glide.
        costs = np.minimum((values[start:end, None] - states) ** 2, 4.)
        accumulated = costs[0].copy()
        previous = np.zeros(costs.shape, dtype=np.int16)
        for i in range(1, len(costs)):
            best = int(accumulated.argmin())
            switched = accumulated[best] + .04 / hop
            stay = accumulated <= switched
            previous[i] = np.where(stay, np.arange(len(states)), best)
            accumulated = costs[i] + np.minimum(accumulated, switched)
        state = int(accumulated.argmin())
        for i in range(len(costs) - 1, -1, -1):
            result[start + i] = states[state]
            state = int(previous[i, state])
    return result
