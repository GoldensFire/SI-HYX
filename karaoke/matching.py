"""Identity of the recording, with independent early/middle/late anchors."""
from __future__ import annotations

from difflib import SequenceMatcher
import math
from pathlib import Path
import re
import tempfile
import wave

import numpy as np
import cover_audio
import cover_fingerprint as fp
from .model import normalize


def title_key(value):
    value = re.sub(r"\s*(?:~|\(|\[)?\s*(?:tv.?size|tv.?ver(?:sion)?|full.?ver(?:sion)?)\s*.*$",
                   "", str(value), flags=re.I)
    return normalize(value)


def metadata_matches(title, artist, duration, track, *, aliases=(), artists=()):
    names = [track.title, *track.aliases]
    if not title_key(title) or not any(title_key(t) == title_key(n)
                                      for t in [title, *aliases] for n in names):
        return False
    singers = [normalize(name) for name in track.artists]
    requested = [normalize(name) for name in [artist, *artists] if normalize(name)]
    if not singers or not any(singer in singers or singer == "".join(singers)
            or any(SequenceMatcher(None, singer, name).ratio() >= .93 for name in singers)
            for singer in requested):
        return False
    if re.search(r"\b(cover|remix|live|instrumental|off.?vocal)\b", track.version, re.I):
        return False
    if track.duration and abs(duration - track.duration) > 2.5:
        return False
    return True


def decode(path, ffmpeg, run):
    with tempfile.TemporaryDirectory(prefix="karaoke-decode-") as directory:
        target = Path(directory) / "audio.wav"
        code, error = run([ffmpeg, "-y", "-v", "error", "-i", str(path),
                           "-vn", "-ac", "1", "-ar", str(cover_audio.SR),
                           "-c:a", "pcm_s16le", str(target)], timeout=180)
        if code:
            raise ValueError("Не удалось прочитать аудио: " + error[-300:])
        with wave.open(str(target), "rb") as audio:
            data = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2").astype(np.float32) / 32768
    if len(data) < cover_audio.SR * 5 or not np.isfinite(data).all():
        raise ValueError("Аудио слишком короткое или повреждено.")
    return data


def anchor(reference, source):
    ref_keys, ref_times = fp.pairs(fp.marks(reference)[0])
    keys, times = fp.pairs(fp.marks(source)[0])
    if not len(keys) or not len(ref_keys):
        return None
    order = np.argsort(ref_keys, kind="stable")
    ref_keys, ref_times = ref_keys[order], ref_times[order]
    low = np.searchsorted(ref_keys, keys, "left")
    high = np.searchsorted(ref_keys, keys, "right")
    count = high - low
    # Very repetitive signals produce unbounded many-to-many pairs.
    count = np.where(count <= 30, count, 0)
    total = int(count.sum())
    if not total or total > 2_000_000:
        return None
    inside = np.arange(total) - np.repeat(np.cumsum(count) - count, count)
    shifts = np.repeat(times, count) - ref_times[np.repeat(low, count) + inside]
    minimum = int(shifts.min())
    histogram = np.bincount(shifts - minimum)
    best = int(histogram.argmax())
    score = int(histogram[best]) / (len(source) / cover_audio.SR)
    return {"offset": (minimum + best) / fp.FPS, "pairs_per_second": round(score, 3)}


def verify_audio(source, reference):
    duration = len(source) / cover_audio.SR
    reference_duration = len(reference) / cover_audio.SR
    if abs(duration - reference_duration) > 2.5:
        raise ValueError("Длительность записи отличается: TV/full-версия.")
    length = min(14.0, duration / 4)
    anchors = []
    for fraction in (.12, .45, .78):
        at = max(0, min(duration - length - 1, duration * fraction))
        start, end = round(at * cover_audio.SR), round((at + length) * cover_audio.SR)
        # Same section, allowing only a bounded constant encoder/intro delay.
        margin = round(2.5 * cover_audio.SR)
        ref_start = max(0, start - margin)
        ref_end = min(len(reference), end + margin)
        found = anchor(reference[ref_start:ref_end], source[start:end])
        if not found or found["pairs_per_second"] < 1.5:
            raise ValueError("Аудиоотпечаток записи не совпал.")
        found["offset"] += (start - ref_start) / cover_audio.SR
        found["at"] = round(at, 3)
        anchors.append(found)
    offsets = [a["offset"] for a in anchors]
    if max(offsets) - min(offsets) > .10:
        raise ValueError("Записи расходятся по времени: монтаж или другой темп.")
    offset = float(np.median(offsets))
    if not math.isfinite(offset) or abs(offset) > 2.5:
        raise ValueError("Недопустимый сдвиг записи.")
    return {"offset": offset, "duration": duration,
            "reference_duration": reference_duration, "anchors": anchors}
