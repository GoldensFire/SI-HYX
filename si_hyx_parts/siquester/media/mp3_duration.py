# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""mp3_duration. Public namespace: siquester.media."""
import siquester.media as _api


def mp3_duration(src, total_bytes: int = 0) -> float:
    """Return MP3 duration in seconds via bitrate estimation.

    *src* can be a ``bytes`` object or a binary file-like object.
    Only the first ``_MP3_PROBE_SIZE`` bytes are read — the sync word is
    always near the start, so we never need the full file (up to 10 MB).

    *total_bytes* — pass the known uncompressed file size (e.g. from
    ``ZipInfo.file_size``) to avoid a seek/read-to-end when *src* is a
    non-seekable ``ZipExtFile``.
    """
    if hasattr(src, 'read'):
        header = src.read(_api._MP3_PROBE_SIZE)
        if not total_bytes:
            # Try seek-based size; fall back to reading the rest.
            try:
                src.seek(0, 2)
                total_bytes = src.tell()
            except Exception:
                total_bytes = len(header) + len(src.read())
    else:
        header      = src[:_api._MP3_PROBE_SIZE]
        total_bytes = total_bytes or len(src)

    i = 0
    while True:
        i = header.find(0xFF, i)
        if i < 0 or i + 3 >= len(header):
            break
        if (header[i+1] & 0xE0) == 0xE0:
            br = _api._MP3_BR_V1[(header[i+2] >> 4) & 0xF] * 1000
            if br > 0:
                return total_bytes * 8 / br
        i += 1
    return 0.0

mp3_duration.__module__ = _api.__name__
_api.mp3_duration = mp3_duration

def _extract_waveform_bars(path: str, n: int = 60) -> list:
    """Extract real amplitude bars from an audio file (RMS per chunk).
    Tries soundfile → wave module → pseudo-random fallback.
    Results are cached by (path, mtime) so navigating back to the same
    question never re-reads the file from disk."""

    # ── Process-level cache: (path, mtime_ns) → bars ────────────
    # Uses mtime_ns (integer nanoseconds) — no float rounding, and
    # id-based comparison is not needed since path is always a string.
    try:
        mtime_key = (path, _api.os.stat(path).st_mtime_ns)
    except OSError:
        mtime_key = (path, 0)
    cached = _api._WAVEFORM_CACHE.get(mtime_key)
    if cached is not None:
        return cached

    bars = _api._extract_waveform_bars_compute(path, n)
    # Evict oldest entry when cache exceeds limit
    if len(_api._WAVEFORM_CACHE) >= _api._WAVEFORM_CACHE_MAX:
        try:
            _api._WAVEFORM_CACHE.pop(next(iter(_api._WAVEFORM_CACHE)))
        except StopIteration:
            pass
    _api._WAVEFORM_CACHE[mtime_key] = bars
    return bars

_extract_waveform_bars.__module__ = _api.__name__
_api._extract_waveform_bars = _extract_waveform_bars
