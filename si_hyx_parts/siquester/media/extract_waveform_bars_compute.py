# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_extract_waveform_bars_compute. Public namespace: siquester.media."""
import siquester.media as _api


def _extract_waveform_bars_compute(path: str, n: int = 60) -> list:

    # ── Try soundfile (handles MP3/M4A/OGG/FLAC/WAV) ──────────
    try:
        import soundfile as _sf
        data, _sr = _sf.read(path, dtype='float32', always_2d=True)
        mono = data.mean(axis=1)
        chunk = max(1, len(mono) // n)
        bars = []
        for i in range(n):
            seg = mono[i * chunk:(i + 1) * chunk]
            bars.append(float((seg ** 2).mean() ** 0.5) if len(seg) else 0.0)
        mx = max(bars) or 1.0
        return [min(1.0, b / mx) for b in bars]
    except Exception:
        pass

    # ── Try wave + numpy (WAV only, 50x faster than pure Python) ──
    try:
        import wave, numpy as _np
        with wave.open(path, 'rb') as wf:
            nch, sw, nf = wf.getnchannels(), wf.getsampwidth(), wf.getnframes()
            raw = wf.readframes(nf)
        dtype = {1: '<i1', 2: '<i2', 4: '<i4'}.get(sw, '<i2')
        arr = _np.frombuffer(raw, dtype=dtype).astype('float32')
        if nch > 1:
            arr = arr.reshape(-1, nch).mean(axis=1)
        arr /= (2 ** (sw * 8 - 1)) or 1
        chunks = _np.array_split(arr, n)
        bars = [float(_np.sqrt(_np.mean(c ** 2))) if len(c) else 0.0 for c in chunks]
        mx = max(bars) or 1.0
        return [min(1.0, b / mx) for b in bars]
    except Exception:
        pass

    # ── Try wave module pure Python (WAV only, slowest fallback) ──────────────
    try:
        import wave, array
        with wave.open(path, 'rb') as wf:
            nch, sw, nf = wf.getnchannels(), wf.getsampwidth(), wf.getnframes()
            raw = wf.readframes(nf)
        tc = {1: 'b', 2: 'h', 4: 'l'}.get(sw, 'h')
        samples = array.array(tc, raw)
        mono = [sum(samples[i:i + nch]) / nch for i in range(0, len(samples), nch)] if nch > 1 else list(samples)
        mx_v = max((abs(s) for s in mono), default=1) or 1
        chunk = max(1, len(mono) // n)
        bars = []
        for i in range(n):
            seg = mono[i * chunk:(i + 1) * chunk]
            rms = _api.math.sqrt(sum(s * s for s in seg) / len(seg)) / mx_v if seg else 0.0
            bars.append(min(1.0, rms))
        return bars
    except Exception:
        pass

    # ── Pseudo-random fallback ─────────────────────────────────
    rng = _api.random.Random(abs(hash(path)) % 2 ** 31)
    raw = [rng.random() for _ in range(n)]
    smoothed = []
    for i in range(n):
        nb = raw[max(0, i - 2):i + 3]
        v = sum(nb) / len(nb)
        v = v * 0.6 + 0.25 * abs(_api.math.sin(i * 0.25)) + 0.1
        smoothed.append(min(1.0, v))
    return smoothed

_extract_waveform_bars_compute.__module__ = _api.__name__
_api._extract_waveform_bars_compute = _extract_waveform_bars_compute

def _measure_lufs(path: str) -> str:
    """Measure integrated loudness in LUFS (ITU-R BS.1770-4 approximation).
    Returns '-14.2 LUFS' style string, or '' on failure.
    Tries pyloudnorm+soundfile → soundfile-only → wave module → ffmpeg subprocess."""

    def _integrated(mono: list, sr: int) -> float:
        if not mono or sr <= 0: return -999.0
        block = max(1, int(sr * 0.4)); hop = max(1, int(sr * 0.1))
        vals = []
        for s in range(0, max(1, len(mono) - block + 1), hop):
            seg = mono[s:s + block]
            ms = sum(x * x for x in seg) / len(seg) if seg else 0.0
            vals.append((-0.691 + 10 * _api.math.log10(ms + 1e-30), ms))
        p1 = [(l, m) for l, m in vals if l >= -70.0]
        if not p1: return -999.0
        lkg = -0.691 + 10 * _api.math.log10(sum(m for _, m in p1) / len(p1) + 1e-30)
        p2 = [(l, m) for l, m in p1 if l >= lkg - 10.0]
        if not p2: return lkg
        return -0.691 + 10 * _api.math.log10(sum(m for _, m in p2) / len(p2) + 1e-30)

    # Read soundfile once — share the result between pyloudnorm and the pure-Python fallback.
    # Previously the file was read twice when pyloudnorm was unavailable.
    _sf_data = _sf_sr = None
    try:
        import soundfile as _sf
        _sf_data, _sf_sr = _sf.read(path, dtype='float32', always_2d=True)
    except Exception:
        pass

    if _sf_data is not None:
        try:
            import pyloudnorm as _pln
            v = _pln.Meter(_sf_sr).integrated_loudness(_sf_data)
            return f"{v:.1f} LUFS" if v > -70 else ""
        except Exception:
            pass
        try:
            mono = _sf_data.mean(axis=1).tolist()
            v = _integrated(mono, _sf_sr)
            return f"{v:.1f} LUFS" if v > -70 else ""
        except Exception:
            pass


    try:
        import wave, array
        with wave.open(path, 'rb') as wf:
            nch, sw, sr, nf = wf.getnchannels(), wf.getsampwidth(), wf.getframerate(), wf.getnframes()
            raw = wf.readframes(nf)
        norm = float(2 ** (sw * 8 - 1))
        s = array.array({1:'b',2:'h',4:'l'}.get(sw,'h'), raw)
        mono = [sum(s[i:i+nch]) / nch / norm for i in range(0, len(s), nch)] if nch > 1 else [x/norm for x in s]
        v = _integrated(mono, sr)
        return f"{v:.1f} LUFS" if v > -70 else ""
    except Exception as _e: _api._logger.debug(str(_e))

    # ── ffmpeg fallback: works for video + any audio container ──
    # creationflags=CREATE_NO_WINDOW — иначе в собранном (windowed) .exe SI-HYX
    # на каждый замер мелькает окно консоли. ffmpeg берётся из PATH (хост-обёртка
    # добавляет туда свой каталог bin).
    try:
        result = _api._subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", path,
             "-af", "loudnorm=print_format=json", "-f", "null", "-"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8,
            creationflags=getattr(_api._subprocess, "CREATE_NO_WINDOW", 0)
        )
        output = result.stderr
        start = output.rfind('{')
        end   = output.rfind('}')
        if start >= 0 and end > start:
            data = _api.json.loads(output[start:end+1])
            il = float(data.get("input_i", "-999"))
            if il > -70:
                return f"{il:.1f} LUFS"
    except FileNotFoundError: pass
    except Exception as _e: _api._logger.debug(str(_e))

    return ""

_measure_lufs.__module__ = _api.__name__
_api._measure_lufs = _measure_lufs

def _mp4_video_size(path: str):
    """Parse width×height from the first non-zero tkhd box in an mp4/mov file.
    Tries the first 64 KB first (fast path), then falls back to reading the last
    256 KB in case the moov atom is at the end of the file (common for web-optimised MP4).
    """
    def _scan(data):
        # locate moov
        i = 0
        moov = None
        while i + 8 <= len(data):
            size = _api.struct.unpack_from('>I', data, i)[0]
            if size < 8: break
            if data[i+4:i+8] == b'moov':
                moov = data[i+8:i+size]; break
            i += size
        if moov is None: return None, None
        # scan trak boxes inside moov
        i = 0
        while i + 8 <= len(moov):
            size = _api.struct.unpack_from('>I', moov, i)[0]
            if size < 8: break
            if moov[i+4:i+8] == b'trak':
                trak = moov[i+8:i+size]
                j = 0
                while j + 8 <= len(trak):
                    s2 = _api.struct.unpack_from('>I', trak, j)[0]
                    if s2 < 8: break
                    if trak[j+4:j+8] == b'tkhd' and s2 >= 92:
                        p = trak[j+8:j+s2]
                        ver = p[0]
                        off = 76 if ver == 0 else 88
                        if len(p) >= off + 8:
                            w = _api.struct.unpack_from('>I', p, off)[0] >> 16
                            h = _api.struct.unpack_from('>I', p, off+4)[0] >> 16
                            if w > 0 and h > 0:
                                return w, h
                    j += s2
            i += size
        return None, None

    try:
        file_size = _api.os.path.getsize(path)
        with open(path, 'rb') as f:
            data = f.read(65536)
        w, h = _scan(data)
        if w: return w, h
        # moov might be at end — try last 256 KB
        if file_size > 65536:
            tail_size = min(262144, file_size)
            with open(path, 'rb') as f:
                f.seek(file_size - tail_size)
                tail = f.read(tail_size)
            return _scan(tail)
    except Exception:
        pass
    return None, None

_mp4_video_size.__module__ = _api.__name__
_api._mp4_video_size = _mp4_video_size

def _mp3_bitrate_kbps(data: bytes) -> int | None:
    """Extract bitrate from the first valid MPEG1/2 Layer-3 frame header."""
    for i in range(min(len(data) - 4, 32768)):
        b0, b1, b2 = data[i], data[i+1], data[i+2]
        if b0 != 0xFF or (b1 & 0xE0) != 0xE0: continue
        ver   = (b1 >> 3) & 0x3   # 3=MPEG1  2=MPEG2  0=MPEG2.5
        layer = (b1 >> 1) & 0x3   # 1=Layer3
        if layer != 1: continue   # not Layer 3
        br_idx = (b2 >> 4) & 0xF
        if br_idx == 0 or br_idx == 15: continue
        if ver == 3:
            return _api._MP3_BR_V1[br_idx]
        elif ver in (2, 0):
            return _api._MP3_BR_V2[br_idx]
    return None

_mp3_bitrate_kbps.__module__ = _api.__name__
_api._mp3_bitrate_kbps = _mp3_bitrate_kbps

def _m4a_audio_bitrate_kbps(data: bytes) -> int | None:
    """Scan binary data for the esds DecoderConfigDescriptor and return avgBitrate (kbps)."""
    pos = 0
    while True:
        idx = data.find(b'esds', pos)
        if idx < 0: break
        pos = idx + 4
        # After the 4-byte box name: version(1)+flags(3) = 4 bytes, then ES_Descriptor
        p = idx + 4 + 4
        if p + 64 > len(data): continue
        # Scan up to 80 bytes for DecoderConfigDescriptor tag 0x04
        end = min(p + 80, len(data) - 14)
        for j in range(p, end):
            if data[j] != 0x04: continue
            # Skip variable-length descriptor size (up to 4 bytes)
            k = j + 1
            for _ in range(4):
                if k >= len(data): break
                b = data[k]; k += 1
                if not (b & 0x80): break
            # objectTypeIndication(1) + streamType(1) + bufferSizeDB(3)
            # + maxBitrate(4) + avgBitrate(4) = 13 bytes minimum
            if k + 13 > len(data): break
            k += 1   # objectTypeIndication
            k += 4   # streamType + bufferSizeDB
            max_br = _api.struct.unpack_from('>I', data, k)[0]; k += 4
            avg_br = _api.struct.unpack_from('>I', data, k)[0]
            bps = avg_br if avg_br > 0 else max_br
            if 8000 < bps < 5_000_000:   # sanity: 8 kbps – 5 Mbps
                return bps // 1000
    return None

_m4a_audio_bitrate_kbps.__module__ = _api.__name__
_api._m4a_audio_bitrate_kbps = _m4a_audio_bitrate_kbps
