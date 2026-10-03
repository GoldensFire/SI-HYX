"""ASS burning with dedicated karaoke AV1 quality and Opus audio."""
from __future__ import annotations

from pathlib import Path
import tempfile

import animepack as ap
from si_hyx_parts.animepack.generation_runtime import encoding_operation
from .ass import write_ass
from .style import FONT_DIR

EFFECT_LABELS = {"original": "Без эффекта", "pitch": "Высота тона",
                 "noise": "Шум", "bandpass": "Полосовой фильтр",
                 "tempo": "Темп", "reverse": "Обратное воспроизведение"}


def tempo(settings):
    return float(settings.karaoke_tempo) if settings.karaoke_effect == "tempo" else 1.0


def audio_effect(settings):
    effect = settings.karaoke_effect
    if effect == "pitch":
        return f"rubberband=pitch={2 ** (settings.karaoke_pitch / 12):.8f}"
    if effect == "noise":
        return "aeval=exprs='val(ch)+0.012*(2*random(0)-1)':c=same"
    if effect == "bandpass":
        return "highpass=f=500,lowpass=f=2500"
    if effect == "tempo":
        return f"atempo={tempo(settings):.6f}"
    if effect == "reverse":
        return "areverse"
    return "anull"


def ass_filter(path):
    escaped = str(path).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    escaped = escaped.replace(",", r"\,").replace("[", r"\[").replace("]", r"\]")
    fonts = str(FONT_DIR).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    return f"ass=filename='{escaped}':fontsdir='{fonts}'"


@encoding_operation
def render(generator, source, destination, lines, *, start, duration, highlight=None):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    output_duration = duration / tempo(generator.s)
    with tempfile.TemporaryDirectory(prefix="karaoke-render-") as directory:
        work = Path(directory)
        subtitle = work / "lyrics.ass"
        subtitle.write_text(write_ass(lines, translations=generator.s.karaoke_translations,
                                      highlight=highlight), encoding="utf-8-sig")
        output = work / "video.mp4"
        video_args = generator.video_encode_args(generator.s.karaoke_preset,
                                                 crf=generator.s.karaoke_crf)
        index = video_args.index("-vf")
        video_args[index + 1] += "," + ass_filter(subtitle)
        filters = audio_effect(generator.s) + "," + generator.audio_filters(output_duration)
        command = [ap.FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i",
                   "color=c=0x111827:s=1280x720:r=30", "-ss", f"{start:.6f}",
                   "-t", f"{duration:.6f}", "-i", str(source), "-map", "0:v:0",
                   "-map", "1:a:0", "-t", f"{output_duration:.6f}", *video_args,
                   "-af", filters, "-c:a", "libopus", "-b:a", ap.AUDIO_BITRATE,
                   "-vbr", "on", "-application", "audio", "-shortest",
                   "-movflags", "+faststart", str(output)]
        code, error = generator._run_killable(command, timeout=600)
        if code or not output.is_file() or output.stat().st_size < ap.MIN_VIDEO_BYTES:
            raise ValueError("Рендер караоке: " + error[-500:])
        if generator.stopped():
            raise RuntimeError("Караоке: остановлено.")
        output.replace(destination)
        return subtitle.read_text(encoding="utf-8-sig"), output_duration


def reverse_audio(generator, candidate, source):
    destination = Path(generator.folder) / "Audio" / candidate.audio_out
    duration = float(generator.s.audio_cut)
    codec = ["-c:a", "libopus", "-b:a", ap.AUDIO_BITRATE] if candidate.compress_audio else ["-c:a", "libmp3lame", "-b:a", "192k"]
    command = [ap.FFMPEG, "-y", "-v", "error", "-ss", str(candidate.trim_start),
               "-t", str(duration), "-i", str(source), "-vn", "-af",
               "areverse," + generator.audio_filters(duration),
               *codec, str(destination)]
    code, error = generator._run_killable(command, timeout=180)
    if code or not destination.is_file():
        destination.unlink(missing_ok=True)
        raise ValueError("Reverse: " + error[-300:])
    candidate.karaoke = {"disabled": "reverse", "ai_used": False}
    generator.log("Караоке отключено для reverse.")
    return True
