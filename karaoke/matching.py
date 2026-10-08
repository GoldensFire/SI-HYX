"""Identity of the recording, with independent early/middle/late anchors."""
from __future__ import annotations

import math
from pathlib import Path
import re
import tempfile
import wave

import numpy as np
import cover_audio
import cover_fingerprint as fp
from storage_guard import require_space, raise_if_full, WORK_RESERVE
from .input_audio import MAX_SECONDS
from .model import normalize
from .performers import performers_match


def title_key(value):
    value = re.sub(r"\s*(?:~|\(|\[)?\s*(?:tv.?size|tv.?ver(?:sion)?|full.?ver(?:sion)?)\s*.*$",
                   "", str(value), flags=re.I)
    return normalize(value)


# The same TV-size song is often published with a longer intro or tail
# (AMQ 89.5 s against a 92.1 s karaoke video). Three agreeing fingerprints
# decide such editions; TV against full (89 s against 217 s) never passes.
SAME_EDITION = 2.5
EDITION_SLACK = 8.0
# Catalogue lengths are often whole seconds of the karaoke video.
METADATA_SLACK = EDITION_SLACK + 1.0


def metadata_mismatch(title, artist, duration, track, *, aliases=(), artists=(), lineup=()):
    """Why an authored edition cannot belong to this song ('' when it can)."""
    names = [track.title, *track.aliases]
    if not title_key(title) or not any(title_key(t) == title_key(n)
                                      for t in [title, *aliases] for n in names):
        return "другое название"
    if not performers_match([artist, *artists], track.artists,
                            groups=track.artist_groups, lineup=lineup):
        return "другой исполнитель"
    version = re.search(r"\b(cover|remix|live|instrumental|off.?vocal)\b", track.version, re.I)
    if version:
        return "версия: " + version.group(1).lower()
    if track.duration and duration and abs(duration - track.duration) > METADATA_SLACK:
        return f"длительность {track.duration:g} с против {duration:.1f} с"
    return ""


def metadata_matches(title, artist, duration, track, **options):
    return not metadata_mismatch(title, artist, duration, track, **options)


def decode(path, ffmpeg, run):
    require_space(Path(path).parent, WORK_RESERVE + (MAX_SECONDS + 1) * cover_audio.SR * 2)
    with tempfile.TemporaryDirectory(prefix="karaoke-decode-", dir=Path(path).parent) as directory:
        target = Path(directory) / "audio.wav"
        code, error = run([ffmpeg, "-y", "-v", "error", "-i", str(path),
                           "-t", str(MAX_SECONDS + 1), "-vn", "-ac", "1", "-ar", str(cover_audio.SR),
                           "-c:a", "pcm_s16le", str(target)], timeout=180)
        if code:
            raise_if_full(error, directory)
            raise ValueError("Не удалось прочитать аудио: " + error[-300:])
        with wave.open(str(target), "rb") as audio:
            if audio.getnframes() > cover_audio.SR * MAX_SECONDS:
                raise ValueError("Исходная песня длиннее 20 минут: проверьте версию записи.")
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
    difference = abs(duration - reference_duration)
    if difference > EDITION_SLACK:
        raise ValueError(f"Длительность записи отличается на {difference:.1f} с: TV/full-версия.")
    # A longer intro shifts every anchor by up to the length difference.
    slack = SAME_EDITION + difference
    length = min(14.0, duration / 4)
    anchors = []
    for fraction in (.12, .45, .78):
        at = max(0, min(duration - length - 1, duration * fraction))
        start, end = round(at * cover_audio.SR), round((at + length) * cover_audio.SR)
        # Same section, allowing only a bounded constant encoder/intro delay.
        margin = round(slack * cover_audio.SR)
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
    if not math.isfinite(offset) or abs(offset) > slack:
        raise ValueError("Недопустимый сдвиг записи.")
    verdict = {"offset": offset, "duration": duration, "reference_duration": reference_duration,
               "duration_difference": round(difference, 3), "anchors": anchors}
    if difference > SAME_EDITION:
        # Intro and tail differ: only the fingerprinted span is known to be
        # the same recording, so the clip must stay inside it.
        verdict["verified_span"] = [anchors[0]["at"], round(anchors[-1]["at"] + length, 3)]
    return verdict
