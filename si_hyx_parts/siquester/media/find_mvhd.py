# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_find_mvhd. Public namespace: siquester.media."""
import siquester.media as _api


def _find_mvhd(buf: bytes) -> float | None:
    """Scan a bytes buffer for the mvhd box and return duration in seconds."""
    i = 0
    while i + 8 <= len(buf):
        try:
            size = _api.struct.unpack_from('>I', buf, i)[0]
            box  = buf[i+4:i+8]
            if size < 8: break
            if box == b'mvhd':
                p   = buf[i+8:i+size]
                ver = p[0]
                ts  = _api.struct.unpack_from('>I', p, 12 if ver == 0 else 20)[0]
                dur = _api.struct.unpack_from('>I', p, 16)[0] if ver == 0 \
                      else _api.struct.unpack_from('>Q', p, 24)[0]
                return dur / ts if ts else None
            i += size
        except Exception:
            break
    return None

_find_mvhd.__module__ = _api.__name__
_api._find_mvhd = _find_mvhd

def mp4_duration(src) -> float:
    """Return MP4 duration in seconds.

    For seekable streams (regular files): probe first+last 32 KB only.
    For non-seekable streams (ZipExtFile — compressed zip entries):
      read the full file into bytes and scan all boxes.
      Files are guaranteed ≤10 MB so this is acceptable.
    """
    if not hasattr(src, 'read'):
        # Already bytes
        return _api._mp4_scan_bytes(src)

    buf = src.read(_api._MP4_PROBE_SIZE)
    # Quick check: moov at start?
    result = _api._mp4_scan_bytes(buf)
    if result > 0.0:
        return result

    # moov not found in first 32 KB — need the rest of the file
    try:
        # Seekable path (regular open file): read last 32 KB
        src.seek(-_api._MP4_PROBE_SIZE, 2)
        tail = src.read(_api._MP4_PROBE_SIZE)
        r = _api._find_mvhd(tail)
        if r: return r
        # Still not found — read everything
        src.seek(0)
        return _api._mp4_scan_bytes(src.read())
    except (OSError, AttributeError):
        # Non-seekable (ZipExtFile): read the remaining bytes and
        # concatenate with the already-read buf so we have full alignment.
        rest = src.read()          # remainder after the first 32 KB
        return _api._mp4_scan_bytes(buf + rest)

mp4_duration.__module__ = _api.__name__
_api.mp4_duration = mp4_duration

def _mp4_scan_bytes(data: bytes) -> float:
    """Scan a complete bytes buffer for the moov/mvhd boxes and return duration."""
    i = 0
    while i + 8 <= len(data):
        try:
            size = _api.struct.unpack_from('>I', data, i)[0]
            if size < 8: break
            box = data[i+4:i+8]
            if box == b'moov':
                r = _api._find_mvhd(data[i+8:i+size])
                return r if r else 0.0
            i += size
        except Exception:
            break
    return 0.0

_mp4_scan_bytes.__module__ = _api.__name__
_api._mp4_scan_bytes = _mp4_scan_bytes
