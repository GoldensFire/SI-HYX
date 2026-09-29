"""Normalize narration to the same Opus loudness target as other pack audio."""
from __future__ import annotations

import os
import tempfile

import animepack as api

from .description_tts import SpeechError


def encode(generator, audio: bytes, source_ext: str, output: str) -> None:
    if source_ext not in ("mp3", "wav"):
        raise SpeechError("неизвестный формат исходной озвучки")
    with tempfile.NamedTemporaryFile(
            mode="wb", suffix=f".{source_ext}", prefix="_description_",
            dir=os.path.dirname(output), delete=False) as source:
        source.write(audio)
        temporary = source.name
    audio_filter = (
        f"loudnorm=I={api.AUDIO_LOUDNORM_I}:LRA={api.AUDIO_LOUDNORM_LRA}"
        f":TP={api.AUDIO_LOUDNORM_TP},{api.OPUS_LAYOUT_FIX}")
    cmd = [api.FFMPEG, "-y", "-loglevel", "error", "-i", temporary,
           "-vn", "-af", audio_filter, "-c:a", "libopus",
           "-b:a", api.AUDIO_BITRATE, "-vbr", "on", "-application", "audio",
           output]
    try:
        code, error = generator._run_killable(cmd, timeout=180)
        if code != 0 or not os.path.isfile(output) or os.path.getsize(output) == 0:
            raise SpeechError((error or "ffmpeg не создал Opus").strip()[:200])
    except Exception:
        try:
            os.remove(output)
        except OSError:
            pass
        raise
    finally:
        try:
            os.remove(temporary)
        except OSError:
            pass
