"""Demucs + lyric-align is invoked only after authored timing is exhausted."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from chiptune.gate import model_slot
from chiptune.runtime import run_process
from music_effects import runtime_python
from .ttml import read_ttml
from .asr_phrases import phrases
from .rejections import SourceRejected
from .lyrics import clean_lines
from .recognition import transcribe


def ensure_runtime(settings, log, stopped):
    python = Path(settings.karaoke_python or runtime_python())
    run = lambda command, timeout=900: run_process(command, timeout, stopped=stopped)
    probe = [str(python), "-I", "-X", "utf8", "-c", "import lyric_align, faster_whisper, demucs, pykakasi"]
    code, _ = run(probe, timeout=30)
    if not code:
        return python
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("Караоке: для установки Demucs + lyric-align требуется uv или готовый Python обработчика.")
    if not python.is_file():
        code, error = run([uv, "venv", "--python", "3.11", str(python.parent.parent)], timeout=600)
        if code:
            raise RuntimeError(error)
    log("Караоке: установка Demucs + lyric-align в отдельное окружение…")
    code, error = run([uv, "pip", "install", "--python", str(python),
                       "lyric-align[asr,separate]==0.4.1", "pykakasi==2.3.0"], timeout=1800)
    if code:
        raise RuntimeError("Караоке: установка обработчика: " + error[-500:])
    return python


def align(source, sheet, settings, *, stopped, log, cache=None):
    original = clean_lines(sheet.original) if sheet else []
    if not original:
        raise ValueError("Для lyric-align нужен проверенный оригинальный текст песни.")
    digest = hashlib.sha256(source.read_bytes())
    source_sha = digest.hexdigest()
    digest.update("\n".join(original).encode())
    digest.update(b"lyric-align-0.4.1-medium-demucs-v2")
    directory = Path(cache or Path.home() / ".cache/si-hyx-karaoke/alignment")
    target = directory / (digest.hexdigest() + ".ttml")
    if target.is_file():
        return read_ttml(target.read_bytes())
    directory.mkdir(parents=True, exist_ok=True)
    with model_slot(stopped):
        python = ensure_runtime(settings, log, stopped)
        work = directory / digest.hexdigest()
        work.mkdir(exist_ok=True)
        lyrics, output = work / "lyrics.txt", work / "timed.ttml"
        asr_cache = directory / "asr-medium-ja-demucs-v2"
        segments = directory / "asr-medium-ja-demucs-v1" / (source_sha + ".json")
        (work / "inputs.json").write_text(json.dumps({"source_sha256": source_sha}), encoding="utf-8")
        lyrics.write_text("\n".join(original), encoding="utf-8")
        anchored = phrases(json.loads(segments.read_text(encoding="utf-8")), original) if segments.is_file() else []
        if len(anchored) < len(original) * .8:
            segments = transcribe(python, source, source_sha, asr_cache, stopped=stopped, log=log)
            anchored = phrases(json.loads(segments.read_text(encoding="utf-8")), original)
        if len(anchored) < len(original) * .8:
            raise SourceRejected("Вокал не подтверждает 80% строк текста: кандидат отклонён.")
        prepared = work / "phrases.json"
        prepared.write_text(json.dumps(anchored, ensure_ascii=False), encoding="utf-8")
        code, error = run_process(
            [str(python), "-I", "-X", "utf8", "-m", "lyric_align.cli",
             "--segments", str(prepared), str(lyrics), "--pairing", "1",
             "-f", "ttml", "-o", str(output)], 1800, stopped=stopped)
        (work / "diagnostics.txt").write_text(error, encoding="utf-8")
        if code or not output.is_file():
            raise ValueError("Demucs + lyric-align: " + error[-500:])
        payload = output.read_bytes()
        try:
            lines = read_ttml(payload)
        except ValueError as failure:
            raise ValueError("lyric-align: " + str(failure) + " " + error[-500:]) from failure
        if len(lines) < len(original) * .8:
            raise SourceRejected("lyric-align сопоставил менее 80% строк: кандидат отклонён.")
        target.write_bytes(payload)
        return lines
