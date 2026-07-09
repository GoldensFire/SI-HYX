# -*- coding: utf-8 -*-
"""Тесты siquester/media.py — чистые парсеры MP4/MP3/M4A, волна, LUFS."""
import io
import math
import struct
import wave

import pytest

from siquester import media as md


# ── синтетические MP4-боксы ──────────────────────────────────────────────────
def _box(name: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + name + payload


def _mvhd_v0(timescale=1000, duration=26000) -> bytes:
    p = bytes([0]) + b"\x00" * 3            # version=0 + flags
    p += b"\x00" * 8                         # creation + modification
    p += struct.pack(">I", timescale)        # offset 12
    p += struct.pack(">I", duration)         # offset 16
    p += b"\x00" * 80
    return _box(b"mvhd", p)


def _mvhd_v1(timescale=600, duration=120_000) -> bytes:
    p = bytes([1]) + b"\x00" * 3
    p += b"\x00" * 16                        # creation + modification (по 8)
    p += struct.pack(">I", timescale)        # offset 20
    p += struct.pack(">Q", duration)         # offset 24
    p += b"\x00" * 80
    return _box(b"mvhd", p)


def _mp4_bytes(mvhd=None, prefix=b"") -> bytes:
    mvhd = mvhd if mvhd is not None else _mvhd_v0()
    return prefix + _box(b"ftyp", b"mp42" + b"\x00" * 8) + _box(b"moov", mvhd)


class TestMp4Duration:
    def test_v0(self):
        data = _mp4_bytes(_mvhd_v0(timescale=1000, duration=26000))
        assert md.mp4_duration(data) == pytest.approx(26.0)

    def test_v1(self):
        data = _mp4_bytes(_mvhd_v1(timescale=600, duration=120_000))
        assert md.mp4_duration(data) == pytest.approx(200.0)

    def test_from_file_like(self):
        data = _mp4_bytes()
        assert md.mp4_duration(io.BytesIO(data)) == pytest.approx(26.0)

    def test_moov_at_end_seekable(self):
        # moov за пределами первых 32 КБ (после большого mdat) → полный скан
        data = _mp4_bytes(prefix=_box(b"mdat", b"\x00" * (md._MP4_PROBE_SIZE + 100)))
        f = io.BytesIO(data)
        assert md.mp4_duration(f) == pytest.approx(26.0)

    def test_garbage(self):
        assert md.mp4_duration("не mp4 вовсе".encode("utf-8")) == 0.0

    def test_empty(self):
        assert md.mp4_duration(b"") == 0.0

    def test_zero_timescale(self):
        data = _mp4_bytes(_mvhd_v0(timescale=0, duration=100))
        assert md.mp4_duration(data) == 0.0

    def test_find_mvhd_direct(self):
        buf = _mvhd_v0(1000, 5000)
        assert md._find_mvhd(buf) == pytest.approx(5.0)

    def test_find_mvhd_missing(self):
        assert md._find_mvhd(_box(b"free", b"\x00" * 16)) is None

    def test_truncated_box(self):
        # size < 8 прерывает разбор без исключения
        assert md._mp4_scan_bytes(struct.pack(">I", 3) + b"abcd") == 0.0


class TestMp3Duration:
    def _frame_header(self, bitrate_idx=9):  # 9 → 128 кбит/с (MPEG1 L3)
        return bytes([0xFF, 0xFB, (bitrate_idx << 4) | 0x00, 0x00])

    def test_bytes_input(self):
        header = self._frame_header() + b"\x00" * 100
        # 128 кбит/с, 16000 байт → 16000*8/128000 = 1.0 c
        assert md.mp3_duration(header, total_bytes=16000) == pytest.approx(1.0)

    def test_file_like_with_total(self):
        header = self._frame_header() + b"\x00" * 100
        assert md.mp3_duration(io.BytesIO(header),
                               total_bytes=32000) == pytest.approx(2.0)

    def test_file_like_seek_size(self):
        data = self._frame_header() + b"\x00" * (16000 - 4)
        assert md.mp3_duration(io.BytesIO(data)) == pytest.approx(1.0)

    def test_no_sync_word(self):
        assert md.mp3_duration(b"\x00" * 1000, total_bytes=1000) == 0.0

    def test_free_bitrate_skipped(self):
        # idx 0 (free) — не считается, дальше валидный фрейм
        data = bytes([0xFF, 0xFB, 0x00, 0x00]) + self._frame_header() + b"\x00" * 50
        assert md.mp3_duration(data, total_bytes=16000) == pytest.approx(1.0)

    def test_empty(self):
        assert md.mp3_duration(b"", total_bytes=0) == 0.0


class TestMp3Bitrate:
    def test_mpeg1(self):
        # нужен «хвост» ≥1 байта: сканер идёт по range(len-4)
        data = bytes([0xFF, 0xFB, 0x90, 0x00]) + b"\x00" * 4  # idx 9 → 128
        assert md._mp3_bitrate_kbps(data) == 128

    def test_mpeg2(self):
        # ver=2 (b1 бит 4-3 = 10): 0xF3 → (0xF3>>3)&3 = 2; layer3
        data = bytes([0xFF, 0xF3, 0x90, 0x00]) + b"\x00" * 4
        assert md._mp3_bitrate_kbps(data) == md._MP3_BR_V2[9]

    def test_not_layer3_skipped(self):
        # layer bits = 3 (Layer 1) → не подходит
        data = bytes([0xFF, 0xFF, 0x90, 0x00]) + b"\x00" * 10
        assert md._mp3_bitrate_kbps(data) is None

    def test_no_header(self):
        assert md._mp3_bitrate_kbps(b"\x00" * 100) is None


class TestM4aBitrate:
    def _esds(self, avg=128000, mx=160000):
        # esds + version/flags + [мусор] + tag 0x04 + size + 13 байт дескриптора
        desc = bytes([0x04, 20])            # DecoderConfigDescriptor, size=20
        desc += bytes([0x40])               # objectTypeIndication (AAC)
        desc += b"\x00" * 4                 # streamType + bufferSizeDB
        desc += struct.pack(">I", mx)       # maxBitrate
        desc += struct.pack(">I", avg)      # avgBitrate
        desc += b"\x00" * 8
        return b"esds" + b"\x00" * 4 + desc + b"\x00" * 64

    def test_avg_bitrate(self):
        assert md._m4a_audio_bitrate_kbps(self._esds(avg=128000)) == 128

    def test_fallback_max_when_avg_zero(self):
        assert md._m4a_audio_bitrate_kbps(self._esds(avg=0, mx=96000)) == 96

    def test_sanity_bounds(self):
        assert md._m4a_audio_bitrate_kbps(self._esds(avg=1000)) is None  # < 8 kbps

    def test_no_esds(self):
        assert md._m4a_audio_bitrate_kbps(b"\x00" * 100) is None


class TestMp4VideoSize:
    def _tkhd(self, w=1280, h=720):
        p = bytes([0]) + b"\x00" * 3
        p += b"\x00" * 72                    # до offset 76
        p += struct.pack(">I", w << 16)      # width 16.16
        p += struct.pack(">I", h << 16)      # height 16.16
        return _box(b"tkhd", p)

    def test_size_parsed(self, tmp_path):
        trak = _box(b"trak", self._tkhd(1920, 1080))
        moov = _box(b"moov", trak)
        f = tmp_path / "v.mp4"
        f.write_bytes(_box(b"ftyp", b"mp42") + moov)
        assert md._mp4_video_size(str(f)) == (1920, 1080)

    def test_moov_at_end(self, tmp_path):
        trak = _box(b"trak", self._tkhd(640, 360))
        moov = _box(b"moov", trak)
        f = tmp_path / "v.mp4"
        f.write_bytes(_box(b"mdat", b"\x00" * 70000) + moov)
        assert md._mp4_video_size(str(f)) == (640, 360)

    def test_no_file(self):
        assert md._mp4_video_size("нет_файла.mp4") == (None, None)

    def test_no_moov(self, tmp_path):
        f = tmp_path / "v.mp4"
        f.write_bytes(b"\x00" * 100)
        assert md._mp4_video_size(str(f)) == (None, None)


# ── волна и LUFS на настоящем WAV ────────────────────────────────────────────
def _write_wav(path, seconds=1.0, freq=440.0, rate=8000, amp=0.5):
    n = int(seconds * rate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(amp * 32767 * math.sin(2 * math.pi * freq * i / rate)))
            for i in range(n))
        wf.writeframes(frames)
    return str(path)


class TestWaveform:
    def test_bars_shape(self, tmp_path):
        p = _write_wav(tmp_path / "a.wav")
        bars = md._extract_waveform_bars_compute(p, n=40)
        assert len(bars) == 40
        assert all(0.0 <= b <= 1.0 for b in bars)
        assert max(bars) == pytest.approx(1.0)  # нормировано к максимуму

    def test_cache_by_mtime(self, tmp_path):
        p = _write_wav(tmp_path / "b.wav")
        b1 = md._extract_waveform_bars(p, n=30)
        b2 = md._extract_waveform_bars(p, n=30)
        assert b1 is b2  # второй вызов — из кеша

    def test_missing_file_pseudo_random(self):
        bars = md._extract_waveform_bars_compute("нет_файла.wav", n=25)
        assert len(bars) == 25
        assert all(0.0 <= b <= 1.0 for b in bars)

    def test_pseudo_random_deterministic(self):
        a = md._extract_waveform_bars_compute("нет.wav", n=10)
        b = md._extract_waveform_bars_compute("нет.wav", n=10)
        assert a == b


class TestMeasureLufs:
    def test_sine_wav(self, tmp_path):
        p = _write_wav(tmp_path / "c.wav", seconds=1.0, amp=0.5)
        out = md._measure_lufs(p)
        assert out.endswith(" LUFS")
        val = float(out.split()[0])
        assert -70 < val < 0

    def test_silence_empty_result(self, tmp_path):
        p = _write_wav(tmp_path / "d.wav", amp=0.0)
        # тишина ниже гейта −70 LUFS → пустая строка
        assert md._measure_lufs(p) == ""


class TestGetMediaInfo:
    def test_video_info(self, tmp_path):
        trak = _box(b"trak", TestMp4VideoSize()._tkhd(1280, 720))
        f = tmp_path / "v.mp4"
        f.write_bytes(_box(b"moov", trak) + b"\x00" * 2_000_000)
        info = md._get_media_info(str(f), is_video=True, dur_sec=10.0)
        assert "МБ" in info
        assert "кбит/с" in info
        assert "1280×720" in info

    def test_audio_mp3_info(self, tmp_path):
        f = tmp_path / "a.mp3"
        f.write_bytes(bytes([0xFF, 0xFB, 0x90, 0x00]) + b"\x00" * 2048)
        info = md._get_media_info(str(f), is_video=False)
        assert "КБ" in info
        assert "128 кбит/с" in info

    def test_audio_estimate(self, tmp_path):
        f = tmp_path / "a.ogg"
        f.write_bytes(b"\x00" * 4000)
        info = md._get_media_info(str(f), is_video=False, dur_sec=2.0)
        assert "~16 кбит/с" in info

    def test_missing_file(self):
        assert md._get_media_info("нет.mp3", is_video=False) == ""
