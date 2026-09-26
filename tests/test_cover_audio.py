# -*- coding: utf-8 -*-
"""Ядро CSI: хрома, транспозиция, локальное выравнивание, перенос окна.

Синтетика, а не файлы: в тестах нет ни сети, ни ffmpeg. Числовые ожидания
калиброваны на настоящих каверах (см. tools/cover_probe.py), здесь проверяются
свойства, от которых эти числа зависят.
"""
import math
import wave

import numpy as np
import pytest

import cover_audio as audio


def _chord(root, seconds, sr=audio.SR, detune=1.0, decay=0.0):
    """Мажорное трезвучие с обертонами: не синус, иначе хрома вырождается."""
    t = np.arange(int(seconds * sr)) / sr
    wave_out = np.zeros_like(t)
    for semitone in (0, 4, 7):
        freq = 440.0 * 2 ** ((root + semitone - 69) / 12.0) * detune
        for harmonic, gain in ((1, 1.0), (2, 0.4), (3, 0.2)):
            wave_out += gain * np.sin(2 * np.pi * freq * harmonic * t)
    if decay:
        wave_out = wave_out * np.exp(-decay * t)
    return (wave_out / (np.max(np.abs(wave_out)) + 1e-9)).astype(np.float32)


def _tune(roots, seconds=1.5, detune=1.0):
    return np.concatenate([_chord(r, seconds, detune=detune) for r in roots])


def _played(roots, seconds=1.5, decay=1.5):
    """Та же последовательность, но СЫГРАННАЯ: у каждой ноты затухание.

    Нужна тестам кавера. Ровная громкость синтезатора даёт кандидату тот же
    отпечаток записи, что и у эталона (cover_fingerprint видит ~180 совпадений
    в секунду при пороге 1.5), и такой «кавер» справедливо отвергается как
    игра под оригинал — ни один живой инструмент так не звучит. С затуханием
    отпечаток расходится (0.11), а хрома по-прежнему узнаёт ту же
    композицию."""
    return np.concatenate([_chord(r, seconds, decay=decay) for r in roots])


ROOTS = [60, 65, 67, 60, 62, 64, 65, 67, 69, 67, 65, 60]


# ── хрома ────────────────────────────────────────────────────────────────
def test_chroma_shape_and_normalisation():
    chroma = audio.chroma(_tune(ROOTS))
    assert chroma.ndim == 2 and chroma.shape[1] == 12
    expected = len(ROOTS) * 1.5 * audio.FPS
    assert abs(chroma.shape[0] - expected) < expected * 0.1
    norms = np.linalg.norm(chroma, axis=1)
    assert np.allclose(norms[norms > 0], 1.0, atol=1e-4)


def test_chroma_is_deterministic_and_length_tolerant():
    """Кадры STFT считаются чанками через as_strided: границы блоков не должны
    ни менять результат, ни выходить за массив."""
    base = _tune(ROOTS[:4])
    assert np.array_equal(audio.chroma(base), audio.chroma(base))
    for extra in (0, 1, audio.HOP - 1, audio.HOP, audio.HOP + 7):
        padded = np.concatenate([base, np.zeros(extra, dtype=np.float32)])
        chroma = audio.chroma(padded)
        assert np.isfinite(chroma).all() and chroma.shape[1] == 12


def test_chroma_survives_a_signal_shorter_than_one_frame():
    chroma = audio.chroma(np.zeros(100, dtype=np.float32))
    assert chroma.shape[1] == 12 and np.isfinite(chroma).all()


def test_chunking_matches_one_shot_computation():
    """Тот же сигнал при РАЗНОМ размере чанка даёт тот же признак."""
    signal = _tune(ROOTS, seconds=0.8)
    reference = audio.chroma(signal)
    original = audio.CHUNK
    try:
        audio.CHUNK = 7
        assert np.allclose(audio.chroma(signal), reference, atol=1e-5)
    finally:
        audio.CHUNK = original


# ── транспозиция ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("semitones", [0, 1, 3, 5, 7, 11])
def test_oti_finds_the_transposition(semitones):
    original = audio.chroma(_tune(ROOTS))
    moved = audio.chroma(_tune([r + semitones for r in ROOTS]))
    assert audio.oti_shift(original, moved) == (-semitones) % 12


# ── выравнивание ─────────────────────────────────────────────────────────
def test_self_alignment_covers_the_whole_reference():
    chroma = audio.chroma(_tune(ROOTS))
    result = audio.align(chroma, chroma)
    assert result["score"] > 0.9 * chroma.shape[0]
    assert abs(result["tempo"] - 1.0) < 0.15
    assert result["ref_span"][1] - result["ref_span"][0] > 0.8 * len(ROOTS) * 1.5


def test_transposed_and_retimed_cover_still_aligns():
    """Кавер в другой тональности и с другим темпом обязан совпасть: ровно это
    и отличает выравнивание от отпечатка (fingerprinting)."""
    reference = audio.chroma(_tune(ROOTS))
    cover = audio.chroma(_tune([r + 4 for r in ROOTS], seconds=1.8))
    result = audio.align(reference, cover)
    assert result["score"] > 0.4 * reference.shape[0]
    assert 0.9 < result["tempo"] < 1.6


def test_unrelated_music_scores_far_lower_than_a_cover():
    reference = audio.chroma(_tune(ROOTS))
    cover = audio.chroma(_tune(ROOTS, seconds=1.2))
    rng = np.random.default_rng(7)
    noise = audio.chroma(rng.standard_normal(reference.shape[0] * audio.HOP
                                             * audio.DOWN).astype(np.float32))
    assert audio.align(reference, cover)["score"] > \
        3 * audio.align(reference, noise)["score"]


def test_cover_longer_than_the_reference_aligns_on_its_middle():
    """Главный случай: эталон — TV-size, кавер — полная версия. Совпадение
    должно находиться ТАМ, ГДЕ ОНО ЕСТЬ, а не в начале файла.

    Проверяется положение, а не величина счёта: синтетические «чужие» аккорды —
    такие же мажорные триады и неизбежно делят с эталоном классы высот, так что
    порог по счёту здесь ничего не доказывал бы. Разделение по счёту мерится на
    настоящих записях (tools/cover_probe.py) и на шуме — тестом выше."""
    other = [61, 63, 66, 68, 70]
    lead = len(other) * 1.5
    reference = audio.chroma(_tune(ROOTS))
    cover = audio.chroma(np.concatenate([_tune(other), _tune(ROOTS),
                                         _tune(other)]))
    result = audio.align(reference, cover)
    assert result["path"]
    # Вставленный блок лежит на [lead, lead + len(ROOTS) * 1.5]; путь обязан
    # попасть в него, а не в начало кавера.
    assert lead * 0.6 < result["cov_span"][0] < lead + len(ROOTS) * 1.5
    assert result["cov_span"][1] > result["cov_span"][0] + lead
    assert 0.8 < result["tempo"] < 1.3


# ── перенос окна эталона в кавер ──────────────────────────────────────────
def test_map_window_shifts_by_the_cover_intro():
    intro = 6.0
    reference = audio.chroma(_tune(ROOTS))
    cover = audio.chroma(np.concatenate([
        np.zeros(int(intro * audio.SR), dtype=np.float32), _tune(ROOTS)]))
    result = audio.align(reference, cover)
    window = audio.map_window(result["path"], 2.0, 8.0)
    assert window is not None
    # Вступление кавера отрезается само: его нет на пути выравнивания.
    assert window[0] > intro * 0.5
    assert 4.0 < window[1] - window[0] < 14.0
    assert audio.window_density(result["path"], 2.0, 8.0) > 0.4


def test_map_window_returns_nothing_outside_the_aligned_part():
    reference = audio.chroma(_tune(ROOTS))
    cover = audio.chroma(_tune(ROOTS[:4]))
    result = audio.align(reference, cover)
    assert audio.map_window(result["path"], 0.0, 4.0) is not None
    # Дальше эталон не покрыт — притворяться, что совпало, нельзя.
    assert audio.map_window(result["path"], 200.0, 20.0) is None
    assert audio.window_density(result["path"], 200.0, 20.0) == 0.0
    assert audio.map_window([], 0.0, 20.0) is None


# ── чтение WAV ────────────────────────────────────────────────────────────
def test_read_wav_roundtrip_and_format_guard(tmp_path):
    path = tmp_path / "a.wav"
    signal = _tune(ROOTS[:2], seconds=0.3)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(audio.SR)
        stream.writeframes((signal * 32767).astype("<i2").tobytes())
    back = audio.read_wav(path)
    assert back.shape == signal.shape and np.max(np.abs(back - signal)) < 1e-3

    stereo = tmp_path / "b.wav"
    with wave.open(str(stereo), "wb") as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(audio.SR)
        stream.writeframes(b"\0\0\0\0")
    with pytest.raises(ValueError):
        audio.read_wav(stereo)


def test_decode_args_ask_for_analysis_format():
    cmd = audio.decode_args("ffmpeg", "in.m4a", "out.wav")
    assert cmd[0] == "ffmpeg" and cmd[-1] == "out.wav"
    assert "-vn" in cmd and "pcm_s16le" in cmd
    assert cmd[cmd.index("-ar") + 1] == str(audio.SR)
    assert cmd[cmd.index("-ac") + 1] == "1"


def test_fps_matches_the_documented_resolution():
    assert math.isclose(audio.FPS, audio.SR / audio.HOP / audio.DOWN)
