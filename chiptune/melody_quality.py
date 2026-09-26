"""Detect loud missing phrases; pitch-model confidence scales are unrelated.

This complements ``validate_notes``. It cannot establish correct pitches or
recognizability: a wrong note still explains activity here. RMS must come from
the isolated leading part, never from the full mixture with its accompaniment.
"""
from __future__ import annotations

import math
import numpy as np

from .notes import QualityError


def melody_diagnostics(notes, rms, *, hop=.01, window=1.5, step=.25,
                       minimum_active=.75, minimum_coverage=.25):
    """Report sustained active sections which the note sequence leaves silent.

    RMS frame ``i`` corresponds to time ``i * hop``. Short breaths, consonants,
    and isolated energy spikes do not qualify as missing phrases. The robust
    relative threshold tolerates quiet stem leakage and changes in gain.
    """
    values = np.asarray(rms, dtype=float)
    parameters = (hop, window, step, minimum_active, minimum_coverage)
    if (not all(math.isfinite(value) for value in parameters)
            or min(hop, window, step, minimum_active) <= 0
            or minimum_active > window or step > window
            or not 0 < minimum_coverage < 1):
        raise ValueError("Некорректные параметры проверки ведущей партии.")
    if (values.ndim != 1 or not len(values) or not np.all(np.isfinite(values))
            or np.any(values < 0)):
        raise QualityError("Chiptune: повреждены данные громкости ведущей партии.")
    threshold = max(.002, float(np.quantile(values, .9)) * .12)
    active = values > threshold
    explained = np.zeros(len(values), dtype=bool)
    # Centre sampling avoids quantizing event boundaries to a musical grid.
    times = np.arange(len(values)) * hop
    duration = len(values) * hop
    for note in notes:
        start, end = note["start"], note["end"]
        if (not math.isfinite(start) or not math.isfinite(end)
                or start < 0 or end <= start or end > duration + max(2 * hop, .03)):
            raise QualityError("Chiptune: неверные границы нот ведущей партии.")
        explained |= (times >= start) & (times < end)

    width = min(len(values), max(1, round(window / hop)))
    stride = max(1, round(step / hop))
    # Include the last window even when the excerpt is not a multiple of step.
    starts = sorted(set(range(0, len(values) - width + 1, stride))
                    | {len(values) - width})
    missing = []
    worst = 1.
    checked = 0
    for start in starts:
        end = start + width
        sounding = active[start:end]
        count = int(sounding.sum())
        if count * hop + 1e-9 < minimum_active:
            continue
        coverage = float(np.count_nonzero(sounding & explained[start:end]) / count)
        worst = min(worst, coverage)
        checked += 1
        if coverage < minimum_coverage:
            missing.append({"start": round(start * hop, 4),
                            "end": round(end * hop, 4),
                            "active_seconds": round(count * hop, 4),
                            "coverage": round(coverage, 4)})
    active_count = int(active.sum())
    return {"active_seconds": round(active_count * hop, 4),
            "active_note_coverage": round(float(np.count_nonzero(active & explained)
                                               / active_count), 4) if active_count else 1.,
            "worst_window_coverage": round(worst, 4),
            "checked_windows": checked, "rms_threshold": threshold,
            "missing_phrases": missing}


def validate_melody_coverage(notes, rms, **parameters):
    """Return JSON-safe diagnostics or refuse a missing active phrase."""
    diagnostics = melody_diagnostics(notes, rms, **parameters)
    if diagnostics["missing_phrases"]:
        worst = min(diagnostics["missing_phrases"], key=lambda item: item["coverage"])
        raise QualityError(
            "Chiptune: пропущена звучащая фраза ведущей партии "
            f"на {worst['start']:.2f}–{worst['end']:.2f} с "
            f"(распознано {worst['coverage']:.0%}). Нужен другой вариант распознавания.")
    return diagnostics
