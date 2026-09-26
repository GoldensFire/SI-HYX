"""Band-limited pulse/triangle voices. This module never accepts original audio."""
from __future__ import annotations

import wave
import numpy as np

from .notes import QualityError, validate_notes

SAMPLE_RATE = 44100


def render(notes, bass, duration, options):
    validate_notes(notes, duration)
    if bass:
        validate_notes(bass, duration, minimum_coverage=.25)
    signal = np.zeros(round(duration * SAMPLE_RATE), dtype=np.float64)
    rng = np.random.default_rng(options["seed"])
    duty = float(rng.choice([.25, .5]))
    # Each line is monophonic, at most two voices total. No original samples.
    for events, volume, triangle in ((notes, options["lead_volume"], False),
                                      (bass, options["bass_volume"], True)):
        for note in events:
            start = max(0, round(note["start"] * SAMPLE_RATE))
            end = min(len(signal), round(note["end"] * SAMPLE_RATE))
            size = end - start
            if size < 2:
                continue
            frequency = 440 * 2 ** ((note["pitch"] - 69) / 12)
            phase = np.arange(size) * 2 * np.pi * frequency / SAMPLE_RATE
            voice = np.zeros(size)
            # Add only harmonics below Nyquist; no aliasing by decimation.
            for harmonic in range(1, min(48, int(SAMPLE_RATE / 2 / frequency))):
                if triangle:
                    if harmonic % 2 == 0:
                        continue
                    amplitude = (-1) ** ((harmonic - 1) // 2) / harmonic ** 2
                else:
                    amplitude = np.sin(np.pi * harmonic * duty) / harmonic
                voice += amplitude * np.sin(phase * harmonic)
            voice /= max(1., float(np.max(np.abs(voice))))
            attack = min(size // 2, round(.008 * SAMPLE_RATE))
            release = min(size // 2, round(.025 * SAMPLE_RATE))
            envelope = .78 + .22 * np.exp(-np.arange(size) / (.06 * SAMPLE_RATE))
            envelope[:attack] *= np.sin(np.linspace(0, np.pi / 2, attack)) ** 2
            envelope[-release:] *= np.sin(np.linspace(np.pi / 2, 0, release)) ** 2
            signal[start:end] += voice * envelope * float(volume) * .48
    peak = float(np.max(np.abs(signal)))
    if peak > .89:
        signal *= .89 / peak  # attenuation only, retain requested party levels
    fade = min(len(signal), SAMPLE_RATE // 5)
    signal[-fade:] *= np.linspace(1, 0, fade)
    validate_audio(signal, duration)
    return signal.astype(np.float32)


def validate_audio(audio, duration):
    if abs(len(audio) / SAMPLE_RATE - duration) > .04:
        raise QualityError("Chiptune: неверная длительность синтеза.")
    if not len(audio) or not np.all(np.isfinite(audio)):
        raise QualityError("Chiptune: повреждённый звук.")
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
    if peak >= .999 or rms < .0003 or np.mean(np.abs(audio) > .0001) < .12:
        raise QualityError("Chiptune: тишина, слишком мало звука или клиппинг.")
    return {"duration": len(audio) / SAMPLE_RATE, "peak": peak, "rms": rms}


def write_wav(path, audio):
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(SAMPLE_RATE)
        stream.writeframes((np.clip(audio, -.999, .999) * 32767).astype("<i2").tobytes())


def read_wav(path):
    with wave.open(str(path), "rb") as stream:
        if (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) != (SAMPLE_RATE, 1, 2):
            raise QualityError("Chiptune: неизвестный формат кеша.")
        return np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").astype(float) / 32768
