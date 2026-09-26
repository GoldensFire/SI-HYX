"""Musical effects plug into the existing audio downloader and SIQ writer."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile

import animepack as _api
from chiptune.service import ChiptuneService
from chiptune.runtime import run_process
from chiptune.synthesis import read_wav, validate_audio
from music_effects import processing_options


def music_service(generator):
    # Constructed once on the generation thread before parallel downloads.
    service = getattr(generator, "_music_service", None)
    if service is None:
        def run(command, timeout=900):
            # Windows venv python.exe is a launcher with a child interpreter.
            # Stop the process tree, not just the launcher used by ffmpeg's runner.
            return run_process(command, timeout, stopped=generator.stopped)
        service = ChiptuneService(generator.s, run, _api.FFMPEG,
                                  stopped=generator.stopped, log=generator.log)
        generator._music_service = service
    return service


def download_chiptune(generator, candidate):
    destination = Path(generator.folder) / "Audio" / candidate.audio_out
    try:
        if not candidate.audio_file:
            return False
        with tempfile.TemporaryDirectory(prefix="chip-", dir=generator.folder) as directory:
            work = Path(directory)
            source, rendered = work / "source.audio", work / "synth.wav"
            url = f"{_api.AMQ_CDN}/{candidate.audio_file}"
            data = generator._cached_bytes(
                url, "amq-audio", _api._MIN_AUDIO_BYTES)
            if len(data) < _api._MIN_AUDIO_BYTES:
                raise ValueError("Исходный файл подозрительно мал.")
            source.write_bytes(data)
            metadata = music_service(generator).convert(
                source, rendered, candidate.trim_start, generator.s.audio_cut)
            output = work / destination.name
            # Never pass through audio_encode_args: its no-compression path copies
            # the original stream. Chiptune's uncompressed output is synthesized PCM.
            if candidate.compress_audio:
                command = [_api.FFMPEG, "-y", "-v", "error", "-i", str(rendered),
                           "-c:a", "libmp3lame", "-b:a", "192k", str(output)]
                code, error = generator._run_killable(command, timeout=180)
                if code:
                    raise ValueError(error)
                decoded = work / "decoded.wav"
                code, error = generator._run_killable(
                    [_api.FFMPEG, "-y", "-v", "error", "-i", str(output),
                     "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", str(decoded)], timeout=180)
                if code:
                    raise ValueError(error)
                validate_audio(read_wav(decoded), generator.s.audio_cut)
            else:
                rendered.replace(output)
            if generator.stopped():
                return False
            output.replace(destination)
            candidate.music_processing = metadata
            generator.log(f"Chiptune: {metadata['note_metrics']['notes']} нот, "
                          f"ведущая партия {metadata['selected_lead']}.")
            return True
    except Exception as error:
        destination.unlink(missing_ok=True)
        generator.log(f"Chiptune «{candidate.title_ru}»: {error} — беру следующего кандидата.")
        return False


def processing_manifest(songs, settings):
    for candidate in songs:
        if candidate.music_effect == "chiptune" and (candidate.has_video or candidate.is_silent):
            raise ValueError("Chiptune: вопрос должен воспроизводить синтезированное аудио.")
    questions = [{"file": candidate.audio_out, "source_kind": candidate.base_kind,
                  "source": candidate.audio_file, "processing": candidate.music_processing}
                 for candidate in songs if candidate.music_effect == "chiptune"]
    if not questions:
        return ""
    if any(not row["processing"] for row in questions):
        raise ValueError("Chiptune: нельзя упаковать вопрос без подтверждённого синтеза.")
    return json.dumps({"settings": processing_options(settings),
                       "percent": settings.chiptune_percent, "questions": questions},
                      ensure_ascii=False, indent=2)
