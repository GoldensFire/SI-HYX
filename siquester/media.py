"""Pure-python media probing (durations, bitrates, waveform, LUFS), image cache and the UI thread bridge."""

from .qt import (
    _logger, _subprocess, json, math, os, pyqtSignal, QImage, QImageReader, QObject,
    QPixmap, Qt, random, struct
)

_MP4_PROBE_SIZE = 1 << 15   # 32 KB — enough for moov header at start of well-formed MP4


def _find_mvhd(buf: bytes) -> float | None:
    """Scan a bytes buffer for the mvhd box and return duration in seconds."""
    i = 0
    while i + 8 <= len(buf):
        try:
            size = struct.unpack_from('>I', buf, i)[0]
            box  = buf[i+4:i+8]
            if size < 8: break
            if box == b'mvhd':
                p   = buf[i+8:i+size]
                ver = p[0]
                ts  = struct.unpack_from('>I', p, 12 if ver == 0 else 20)[0]
                dur = struct.unpack_from('>I', p, 16)[0] if ver == 0 \
                      else struct.unpack_from('>Q', p, 24)[0]
                return dur / ts if ts else None
            i += size
        except Exception:
            break
    return None


def mp4_duration(src) -> float:
    """Return MP4 duration in seconds.

    For seekable streams (regular files): probe first+last 32 KB only.
    For non-seekable streams (ZipExtFile — compressed zip entries):
      read the full file into bytes and scan all boxes.
      Files are guaranteed ≤10 MB so this is acceptable.
    """
    if not hasattr(src, 'read'):
        # Already bytes
        return _mp4_scan_bytes(src)

    buf = src.read(_MP4_PROBE_SIZE)
    # Quick check: moov at start?
    result = _mp4_scan_bytes(buf)
    if result > 0.0:
        return result

    # moov not found in first 32 KB — need the rest of the file
    try:
        # Seekable path (regular open file): read last 32 KB
        src.seek(-_MP4_PROBE_SIZE, 2)
        tail = src.read(_MP4_PROBE_SIZE)
        r = _find_mvhd(tail)
        if r: return r
        # Still not found — read everything
        src.seek(0)
        return _mp4_scan_bytes(src.read())
    except (OSError, AttributeError):
        # Non-seekable (ZipExtFile): read the remaining bytes and
        # concatenate with the already-read buf so we have full alignment.
        rest = src.read()          # remainder after the first 32 KB
        return _mp4_scan_bytes(buf + rest)


def _mp4_scan_bytes(data: bytes) -> float:
    """Scan a complete bytes buffer for the moov/mvhd boxes and return duration."""
    i = 0
    while i + 8 <= len(data):
        try:
            size = struct.unpack_from('>I', data, i)[0]
            if size < 8: break
            box = data[i+4:i+8]
            if box == b'moov':
                r = _find_mvhd(data[i+8:i+size])
                return r if r else 0.0
            i += size
        except Exception:
            break
    return 0.0


_MP3_BR_V1 = [0,32,40,48,56,64,80,96,112,128,160,192,224,256,320,0]  # MPEG1 L3 kbps


_MP3_BR_V2 = [0, 8,16,24,32,40,48,56, 64, 80, 96,112,128,144,160,0]  # MPEG2/2.5 L3 kbps


_MP3_PROBE_SIZE = 4096   # sync word is always within the first 4 KB


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
        header = src.read(_MP3_PROBE_SIZE)
        if not total_bytes:
            # Try seek-based size; fall back to reading the rest.
            try:
                src.seek(0, 2)
                total_bytes = src.tell()
            except Exception:
                total_bytes = len(header) + len(src.read())
    else:
        header      = src[:_MP3_PROBE_SIZE]
        total_bytes = total_bytes or len(src)

    i = 0
    while True:
        i = header.find(0xFF, i)
        if i < 0 or i + 3 >= len(header):
            break
        if (header[i+1] & 0xE0) == 0xE0:
            br = _MP3_BR_V1[(header[i+2] >> 4) & 0xF] * 1000
            if br > 0:
                return total_bytes * 8 / br
        i += 1
    return 0.0


def _extract_waveform_bars(path: str, n: int = 60) -> list:
    """Extract real amplitude bars from an audio file (RMS per chunk).
    Tries soundfile → wave module → pseudo-random fallback.
    Results are cached by (path, mtime) so navigating back to the same
    question never re-reads the file from disk."""

    # ── Process-level cache: (path, mtime_ns) → bars ────────────
    # Uses mtime_ns (integer nanoseconds) — no float rounding, and
    # id-based comparison is not needed since path is always a string.
    try:
        mtime_key = (path, os.stat(path).st_mtime_ns)
    except OSError:
        mtime_key = (path, 0)
    cached = _WAVEFORM_CACHE.get(mtime_key)
    if cached is not None:
        return cached

    bars = _extract_waveform_bars_compute(path, n)
    # Evict oldest entry when cache exceeds limit
    if len(_WAVEFORM_CACHE) >= _WAVEFORM_CACHE_MAX:
        try:
            _WAVEFORM_CACHE.pop(next(iter(_WAVEFORM_CACHE)))
        except StopIteration:
            pass
    _WAVEFORM_CACHE[mtime_key] = bars
    return bars


_WAVEFORM_CACHE: dict = {}


_WAVEFORM_CACHE_MAX = 64   # max cached waveforms (~64 unique audio files)


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
            rms = math.sqrt(sum(s * s for s in seg) / len(seg)) / mx_v if seg else 0.0
            bars.append(min(1.0, rms))
        return bars
    except Exception:
        pass

    # ── Pseudo-random fallback ─────────────────────────────────
    rng = random.Random(abs(hash(path)) % 2 ** 31)
    raw = [rng.random() for _ in range(n)]
    smoothed = []
    for i in range(n):
        nb = raw[max(0, i - 2):i + 3]
        v = sum(nb) / len(nb)
        v = v * 0.6 + 0.25 * abs(math.sin(i * 0.25)) + 0.1
        smoothed.append(min(1.0, v))
    return smoothed


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
            vals.append((-0.691 + 10 * math.log10(ms + 1e-30), ms))
        p1 = [(l, m) for l, m in vals if l >= -70.0]
        if not p1: return -999.0
        lkg = -0.691 + 10 * math.log10(sum(m for _, m in p1) / len(p1) + 1e-30)
        p2 = [(l, m) for l, m in p1 if l >= lkg - 10.0]
        if not p2: return lkg
        return -0.691 + 10 * math.log10(sum(m for _, m in p2) / len(p2) + 1e-30)

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
    except Exception as _e: _logger.debug(str(_e))

    # ── ffmpeg fallback: works for video + any audio container ──
    # creationflags=CREATE_NO_WINDOW — иначе в собранном (windowed) .exe SI-HYX
    # на каждый замер мелькает окно консоли. ffmpeg берётся из PATH (хост-обёртка
    # добавляет туда свой каталог bin).
    try:
        result = _subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", path,
             "-af", "loudnorm=print_format=json", "-f", "null", "-"],
            capture_output=True, text=True, timeout=8,
            creationflags=getattr(_subprocess, "CREATE_NO_WINDOW", 0)
        )
        output = result.stderr
        start = output.rfind('{')
        end   = output.rfind('}')
        if start >= 0 and end > start:
            data = json.loads(output[start:end+1])
            il = float(data.get("input_i", "-999"))
            if il > -70:
                return f"{il:.1f} LUFS"
    except FileNotFoundError: pass
    except Exception as _e: _logger.debug(str(_e))

    return ""


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
            size = struct.unpack_from('>I', data, i)[0]
            if size < 8: break
            if data[i+4:i+8] == b'moov':
                moov = data[i+8:i+size]; break
            i += size
        if moov is None: return None, None
        # scan trak boxes inside moov
        i = 0
        while i + 8 <= len(moov):
            size = struct.unpack_from('>I', moov, i)[0]
            if size < 8: break
            if moov[i+4:i+8] == b'trak':
                trak = moov[i+8:i+size]
                j = 0
                while j + 8 <= len(trak):
                    s2 = struct.unpack_from('>I', trak, j)[0]
                    if s2 < 8: break
                    if trak[j+4:j+8] == b'tkhd' and s2 >= 92:
                        p = trak[j+8:j+s2]
                        ver = p[0]
                        off = 76 if ver == 0 else 88
                        if len(p) >= off + 8:
                            w = struct.unpack_from('>I', p, off)[0] >> 16
                            h = struct.unpack_from('>I', p, off+4)[0] >> 16
                            if w > 0 and h > 0:
                                return w, h
                    j += s2
            i += size
        return None, None

    try:
        file_size = os.path.getsize(path)
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
            return _MP3_BR_V1[br_idx]
        elif ver in (2, 0):
            return _MP3_BR_V2[br_idx]
    return None


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
            max_br = struct.unpack_from('>I', data, k)[0]; k += 4
            avg_br = struct.unpack_from('>I', data, k)[0]
            bps = avg_br if avg_br > 0 else max_br
            if 8000 < bps < 5_000_000:   # sanity: 8 kbps – 5 Mbps
                return bps // 1000
    return None


def _get_media_info(path: str, is_video: bool, dur_sec: float = 0.0) -> str:
    """Compact info string: size, bitrate (audio stream accurate), resolution (video)."""
    parts = []
    try:
        size_bytes = os.path.getsize(path)
        parts.append(f"{size_bytes / 1024 / 1024:.1f} МБ" if size_bytes >= 1_048_576
                     else f"{size_bytes // 1024} КБ")

        ext = path.rsplit('.', 1)[-1].lower() if '.' in path else ''

        if is_video:
            if dur_sec > 0:
                kbps = int(size_bytes * 8 / dur_sec / 1000)
                if kbps > 0: parts.append(f"~{kbps} кбит/с")
            # Resolution — try pure-Python parser first; mpv will override after load
            w, h = _mp4_video_size(path)
            if w and h: parts.append(f"{w}×{h}")
        else:
            # ── Audio bitrate ──────────────────────────────────────
            br = None
            read_sz = min(65536, size_bytes)
            with open(path, 'rb') as f:
                head = f.read(read_sz)
            if ext == 'mp3':
                br = _mp3_bitrate_kbps(head)
            elif ext in ('m4a', 'mp4', 'aac', 'mp4a'):
                br = _m4a_audio_bitrate_kbps(head)
                if br is None and size_bytes > read_sz:
                    # moov might be at end of file
                    with open(path, 'rb') as f:
                        f.seek(max(0, size_bytes - 262144))
                        tail = f.read(262144)
                    br = _m4a_audio_bitrate_kbps(tail)
            elif ext in ('ogg', 'opus', 'flac', 'wav', 'wma'):
                pass  # fall through to estimation
            # Any other format or failed parse → estimate from size/duration
            if br:
                parts.append(f"{br} кбит/с")
            elif dur_sec > 0:
                est = int(size_bytes * 8 / dur_sec / 1000)
                if est > 0: parts.append(f"~{est} кбит/с")
    except Exception as e:
        _logger.warning(f"[media_info] {e}")
    return "  ·  ".join(parts)


class _ThreadBridge(QObject):
    """Universal thread-safe bridge: emit from any thread, slots run on main thread.

    Three signal types cover all background→UI update patterns in this app:
      • pixmap_ready(QPixmap|None, QLabel)  — image delivery
      • text_ready(QLabel, str)             — label text update
      • call_ready(object)                  — arbitrary zero-arg callable
    All connections use Qt.QueuedConnection so slots always execute on the
    main (GUI) thread regardless of which thread emits.
    """
    pixmap_ready = pyqtSignal(object, object)   # (QPixmap | None, QLabel)
    text_ready   = pyqtSignal(object, str)       # (QLabel, text)
    call_ready   = pyqtSignal(object)            # (callable,)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap_ready.connect(self._on_pixmap, Qt.ConnectionType.QueuedConnection)
        self.text_ready.connect(self._on_text,     Qt.ConnectionType.QueuedConnection)
        self.call_ready.connect(self._on_call,     Qt.ConnectionType.QueuedConnection)

    def _on_pixmap(self, img, lbl):
        """Runs on main thread. Converts QImage → QPixmap (safe here) and sets on label."""
        try:
            if img and not img.isNull():
                pm = QPixmap.fromImage(img)   # QPixmap creation: main thread only ✓
                lbl.setFixedHeight(pm.height())
                lbl.setPixmap(pm)
            else:
                lbl.setText("🖼  Формат не поддержан")
        except RuntimeError:
            pass

    def _on_text(self, lbl, text):
        try: lbl.setText(text)
        except RuntimeError: pass

    def _on_call(self, fn):
        try: fn()
        except RuntimeError: pass

    # ── Convenience methods called from background threads ──────
    def deliver(self, pm, lbl):
        self.pixmap_ready.emit(pm, lbl)

    def deliver_text(self, lbl, text: str):
        self.text_ready.emit(lbl, text)

    def deliver_call(self, fn):
        """Post a zero-arg callable to run on the main thread."""
        self.call_ready.emit(fn)


_UI_BRIDGE: "_ThreadBridge | None" = None


def _get_ui_bridge() -> "_ThreadBridge":
    global _UI_BRIDGE
    if _UI_BRIDGE is None:
        _UI_BRIDGE = _ThreadBridge()
    return _UI_BRIDGE


_IMAGE_CACHE: dict[tuple, "QImage"] = {}   # (path, width) → scaled QImage


_IMAGE_CACHE_MAX = 64


try:
    from pillow_heif import register_heif_opener as _reg_heif
    _reg_heif()
    _HEIF_AVAILABLE = True
except ImportError:
    _HEIF_AVAILABLE = False


def _load_qimage(path: str, width: int) -> "QImage | None":
    """Decode and scale an image to QImage. SAFE to call from any thread."""
    key = (path, width)
    if key in _IMAGE_CACHE:
        return _IMAGE_CACHE[key]

    img = None

    # ── Attempt 1: QImageReader ───────────────────────────────────
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    if reader.canRead():
        qimg = reader.read()
        if not qimg.isNull():
            img = qimg.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)

    # ── Attempt 2: Pillow (+ pillow-heif for AVIF/HEIC) ──────────
    if img is None or img.isNull():
        try:
            from PIL import Image as _PILImage
            with _PILImage.open(path) as _pil:
                _pil = _pil.convert("RGBA")
                w_px, h_px = _pil.size
                raw = bytes(_pil.tobytes("raw", "RGBA"))
            qimg2 = QImage(raw, w_px, h_px, w_px * 4,
                           QImage.Format.Format_RGBA8888).copy()
            if not qimg2.isNull():
                img = qimg2.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
        except Exception as e:
            _logger.warning(f"[img] failed: {e!r} | {path}")

    if img and not img.isNull():
        if len(_IMAGE_CACHE) >= _IMAGE_CACHE_MAX:
            _IMAGE_CACHE.pop(next(iter(_IMAGE_CACHE)))
        _IMAGE_CACHE[key] = img
        return img
    return None


def _img_size_from_path(path: str) -> tuple[int, int]:
    """Return (width, height) from image header without full decode. (0,0) on failure.
    Tries QImageReader first; falls back to Pillow (+ pillow-heif for AVIF/HEIC).
    """
    reader = QImageReader(path)
    sz = reader.size()
    if sz.isValid() and sz.width() > 0:
        return sz.width(), sz.height()
    # Pillow fallback — pillow-heif registered at import time handles AVIF
    try:
        from PIL import Image as _PILImage
        with _PILImage.open(path) as _pil:
            return _pil.width, _pil.height
    except Exception:
        pass
    return 0, 0

__all__ = [
    '_HEIF_AVAILABLE',
    '_IMAGE_CACHE',
    '_IMAGE_CACHE_MAX',
    '_MP3_BR_V1',
    '_MP3_BR_V2',
    '_MP3_PROBE_SIZE',
    '_MP4_PROBE_SIZE',
    '_ThreadBridge',
    '_UI_BRIDGE',
    '_WAVEFORM_CACHE',
    '_WAVEFORM_CACHE_MAX',
    '_extract_waveform_bars',
    '_extract_waveform_bars_compute',
    '_find_mvhd',
    '_get_media_info',
    '_get_ui_bridge',
    '_img_size_from_path',
    '_load_qimage',
    '_m4a_audio_bitrate_kbps',
    '_measure_lufs',
    '_mp3_bitrate_kbps',
    '_mp4_scan_bytes',
    '_mp4_video_size',
    '_reg_heif',
    'mp3_duration',
    'mp4_duration',
]
