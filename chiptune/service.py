"""Desktop boundary: cancellable subprocesses, caches, rendering and validation."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import tempfile

from music_effects import VERSION, processing_options, runtime_python
from .notes import QualityError, validate_notes
from .synthesis import read_wav, render, validate_audio, write_wav
from .gate import MODEL_GATE, model_slot  # MODEL_GATE remains available for diagnostics
from .launcher import isolated_command

def worker_path():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root / "chiptune/worker.py"


def cache_root():
    return Path.home() / ".cache/si-hyx-chiptune/audio"


def cache_key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class ChiptuneService:
    def __init__(self, settings, run, ffmpeg, *, stopped=lambda: False,
                 log=lambda text: None, cache=None):
        self.settings, self.run, self.ffmpeg = settings, run, str(ffmpeg)
        self.stopped, self.log = stopped, log
        self.cache = Path(cache) if cache else cache_root()
        self.python = str(settings.chiptune_python or runtime_python())
        self.identity = None

    def command(self, operation, target, *args):
        with isolated_command(self.python, worker_path()) as command:
            code, error = self.run([*command, operation, "--target", str(target),
                                    *map(str, args)], timeout=900)
        if code or not Path(target).is_file():
            raise QualityError(error.strip()[-1000:] or "Chiptune: обработчик не создал результат.")

    def preflight(self):
        if self.identity is None:
            with tempfile.TemporaryDirectory(prefix="sihyx_chip_probe_") as directory:
                target = Path(directory) / "identity.json"
                self.command("probe", target)
                self.identity = json.loads(target.read_text(encoding="utf-8"))
        return self.identity

    def convert(self, source, target, start, duration, *, seed=None):
        self.log("Chiptune: ожидание свободного обработчика…")
        with model_slot(self.stopped):
            if self.stopped():
                raise QualityError("Chiptune: остановлено.")
            return self._convert(source, target, start, duration, seed)

    def _convert(self, source, target, start, duration, seed):
        if (not math.isfinite(start) or start < 0 or not math.isfinite(duration)
                or not 4 <= duration <= 60):
            raise QualityError("Chiptune: неверное начало или длительность фрагмента (4–60 с).")
        options = processing_options(self.settings)
        if options["version"] != VERSION:
            raise QualityError("Chiptune: неподдерживаемая версия обработки.")
        if seed is not None:
            options["seed"] = seed
        identity = self.preflight()
        digest = hashlib.sha256()
        with open(source, "rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                if self.stopped():
                    raise QualityError("Chiptune: остановлено.")
                digest.update(block)
        source_key = {"source_sha256": digest.hexdigest(), "start": float(start),
                      "duration": float(duration), "models": identity,
                      "separation": "htdemucs-shifts0-overlap.25-pcm44100-v1"}
        # A different pitch model must not repeat expensive separation.
        stem_key = cache_key({**source_key, "models": identity.get("separation", identity)})
        note_key = cache_key({"stem": stem_key, "lead": options["lead"], "version": VERSION,
                              "models": identity.get("transcription", identity),
                              "tracker": "rmvpe-vocals-path40ms-crepe-other-v2"})
        render_key = cache_key({"notes": note_key, "options": options})
        self.cache.mkdir(parents=True, exist_ok=True)
        stems = self.cache / f"{stem_key}.npz"
        notes_path = self.cache / f"{note_key}.json"
        rendered = self.cache / f"{render_key}.wav"
        # Each job owns its incomplete files. Only completed results are published.
        with tempfile.TemporaryDirectory(prefix="job-", dir=self.cache) as directory:
            work = Path(directory)
            if not notes_path.is_file():
                if not stems.is_file():
                    self.log("Chiptune: выделение вокала, баса и инструментов…")
                    clip = work / "source.wav"
                    code, error = self.run([self.ffmpeg, "-y", "-v", "error", "-ss", str(start),
                                            "-i", str(source), "-t", str(duration), "-vn",
                                            "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le",
                                            str(clip)], timeout=180)
                    if code:
                        raise QualityError(error)
                    temporary = work / "stems.npz"
                    self.command("separate", temporary, "--source", clip,
                                 "--seed", options["seed"])
                    temporary.replace(stems)
                self.log("Chiptune: распознавание ведущей мелодии и очистка нот…")
                temporary = work / "notes.json"
                self.command("transcribe", temporary, "--source", stems, "--lead", options["lead"])
                temporary.replace(notes_path)
            data = json.loads(notes_path.read_text(encoding="utf-8"))
            if abs(data["duration"] - duration) > .15:
                raise QualityError("Chiptune: исходный фрагмент короче заказанной длительности.")
            validate_notes(data["notes"], data["duration"])
            if data["bass"]:
                validate_notes(data["bass"], data["duration"], minimum_coverage=.25)
            self.log("Chiptune: синтез пульсовой мелодии и треугольного баса…")
            if rendered.is_file():
                try:
                    audio = read_wav(rendered)
                    validate_audio(audio, data["duration"])
                except (ValueError, OSError, EOFError):
                    rendered.unlink(missing_ok=True)
            if not rendered.is_file():
                audio = render(data["notes"], data["bass"], data["duration"], options)
                temporary = work / "render.wav"
                write_wav(temporary, audio)
                temporary.replace(rendered)
            if self.stopped():
                raise QualityError("Chiptune: остановлено.")
            shutil.copyfile(rendered, target)
            metrics = validate_audio(read_wav(target), data["duration"])
            return {**source_key, "processing": options, "cache_key": render_key,
                    "selected_lead": data["lead"], "notes": data["notes"], "bass": data["bass"],
                    "note_metrics": data["metrics"], "audio_metrics": metrics}
