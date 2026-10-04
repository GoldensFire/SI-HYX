"""Multilingual acoustic alignment, only after authored timing is exhausted."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from chiptune.gate import model_slot
from chiptune.runtime import run_process
from .ttml import read_ttml
from .asr_phrases import phrases
from .rejections import SourceRejected
from .lyrics import clean_lines
from .recognition import transcribe, device_info
from .ai_runtime import ensure_runtime
from .languages import lyric_languages
from .asr_passes import combine


def acoustic_phrases(python, source, source_sha, original, languages, directory, *, stopped, log, info):
    anchored = []
    for language in languages[:2]:
        segments = transcribe(python, source, source_sha, directory, stopped=stopped, log=log,
                              language=language, info=info)
        rows = phrases(json.loads(segments.read_text(encoding="utf-8")), original, indices=True)
        anchored = combine(anchored, rows, original) if anchored else rows
        log(f"Караоке: ASR {language or 'auto'} подтверждает {len(anchored)}/{len(original)} строк.")
        if len(anchored) >= len(original) * .8:
            break
    if len(anchored) < len(original) * .8:
        raise SourceRejected("Вокал не подтверждает 80% строк текста: кандидат отклонён.")
    return [{k: v for k, v in row.items() if k != "line_index"} for row in anchored]


def align(source, sheet, settings, *, stopped, log, cache=None):
    original = clean_lines(sheet.original) if sheet else []
    if not original:
        raise ValueError("Для lyric-align нужен проверенный оригинальный текст песни.")
    digest = hashlib.sha256(source.read_bytes())
    source_sha = digest.hexdigest()
    digest.update("\n".join(original).encode())
    digest.update(b"lyric-align-0.4.1-medium-multilingual-kim-v3")
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
        asr_cache = directory / "asr-v3"
        languages = lyric_languages(python, original, work, stopped=stopped, log=log)
        info = device_info(python, stopped)
        (work / "inputs.json").write_text(json.dumps({"source_sha256": source_sha,
            "languages": languages, "device": info}), encoding="utf-8")
        lyrics.write_text("\n".join(original), encoding="utf-8")
        anchored = acoustic_phrases(python, source, source_sha, original, languages, asr_cache,
                                    stopped=stopped, log=log, info=info)
        prepared = work / "phrases.json"
        prepared.write_text(json.dumps(anchored, ensure_ascii=False), encoding="utf-8")
        code, error = run_process(
            [str(python), "-I", "-X", "utf8", "-m", "lyric_align.cli",
             "--segments", str(prepared), str(lyrics), "--pairing", "1",
             "-f", "ttml", "-o", str(output)], 1800, stopped=stopped)
        (work / "diagnostics.txt").write_text(error, encoding="utf-8")
        if code or not output.is_file():
            raise ValueError("Whisper + lyric-align: " + error[-500:])
        payload = output.read_bytes()
        try:
            lines = read_ttml(payload)
        except ValueError as failure:
            raise ValueError("lyric-align: " + str(failure) + " " + error[-500:]) from failure
        if len(lines) < len(original) * .8:
            raise SourceRejected("lyric-align сопоставил менее 80% строк: кандидат отклонён.")
        target.write_bytes(payload)
        return lines
