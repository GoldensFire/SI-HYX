"""Clean continuous pitch without forcing a beat grid."""
from __future__ import annotations

import math
import numpy as np

from .pitch_path import stable_pitches


class QualityError(ValueError):
    """The excerpt cannot safely become a musical question."""


def pitch_notes(frequencies, confidence, loudness, *, hop=0.01, threshold=0.55,
                min_note=0.09, midi_low=45, midi_high=90, stabilize=False):
    frequency = np.asarray(frequencies, dtype=float)
    confidence = np.asarray(confidence, dtype=float)
    loudness = np.asarray(loudness, dtype=float)
    size = min(len(frequency), len(confidence), len(loudness))
    if not size:
        return []
    frequency, confidence, loudness = frequency[:size], confidence[:size], loudness[:size]
    valid = (np.isfinite(frequency) & (frequency > 0) & np.isfinite(confidence)
             & (confidence >= threshold)
             & np.isfinite(loudness) & (loudness > max(0.002, loudness.max(initial=0) * .035)))
    midi = 69 + 12 * np.log2(np.maximum(np.nan_to_num(frequency), 1) / 440)
    valid &= (midi >= midi_low - .5) & (midi <= midi_high + .5)
    # 50 ms median removes vibrato crossings and isolated semitone flicker.
    smoothed = np.median(np.lib.stride_tricks.sliding_window_view(
        np.pad(midi, (2, 2), mode="edge"), 5), axis=1) if size else midi
    pitches = (stable_pitches(smoothed, confidence, valid, low=midi_low, high=midi_high, hop=hop)
               if stabilize else np.rint(smoothed).astype(int))
    valid &= (pitches >= midi_low) & (pitches <= midi_high)
    pitches[~valid] = -1
    # Bridge only very short dropouts between the SAME pitch.
    for i in range(1, size - 1):
        if pitches[i] < 0:
            end = i
            while end < size and pitches[end] < 0 and end - i < 4:
                end += 1
            if end < size and pitches[i - 1] == pitches[end] and pitches[end] >= 0:
                pitches[i:end] = pitches[end]
    changes = np.r_[0, np.flatnonzero(np.diff(pitches)) + 1, size]
    notes = []
    for start, end in zip(changes[:-1], changes[1:]):
        if pitches[start] < 0 or (end - start) * hop < min_note:
            continue
        note = {"start": round(float(start * hop), 4), "end": round(float(end * hop), 4),
                "pitch": int(pitches[start]),
                "confidence": round(float(np.mean(confidence[start:end])), 4)}
        if (notes and notes[-1]["pitch"] == note["pitch"]
                and note["start"] - notes[-1]["end"] <= .05):
            notes[-1]["end"] = note["end"]
        else:
            notes.append(note)
    return notes


def validate_notes(notes, duration, *, minimum_coverage=.5):
    if not math.isfinite(duration) or not 4 <= duration <= 61:
        raise QualityError("Chiptune: нужен фрагмент длиной 4–60 секунд.")
    previous = 0.0
    for note in notes:
        start, end, pitch = note["start"], note["end"], note["pitch"]
        if (not all(math.isfinite(x) for x in (start, end, pitch, note["confidence"]))
                or start < previous - .001 or end <= start or end > duration + .03
                or not 24 <= pitch <= 100 or not 0 <= note["confidence"] <= 1):
            raise QualityError("Chiptune: повреждённая или перекрывающаяся нотная последовательность.")
        previous = end
    coverage = sum(n["end"] - n["start"] for n in notes) / duration
    confidence = float(np.mean([n["confidence"] for n in notes])) if notes else 0
    if len(notes) < 5 or len({n["pitch"] for n in notes}) < 3:
        raise QualityError("Chiptune: слишком мало разных нот для узнаваемой мелодии.")
    if coverage < minimum_coverage or confidence < .6 or len(notes) / duration > 9:
        raise QualityError("Chiptune: ведущая мелодия распознана ненадёжно или содержит слишком много пауз.")
    jumps = sum(abs(a["pitch"] - b["pitch"]) > 14 for a, b in zip(notes, notes[1:]))
    if jumps > max(2, len(notes) * .22):
        raise QualityError("Chiptune: слишком много неправдоподобных скачков мелодии.")
    return {"notes": len(notes), "coverage": round(coverage, 3),
            "confidence": round(confidence, 3), "large_jumps": jumps}
