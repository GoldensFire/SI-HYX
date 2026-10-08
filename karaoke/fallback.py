"""Multilingual acoustic alignment, only after authored timing is exhausted."""
from __future__ import annotations

import hashlib
import json
from contextlib import ExitStack, nullcontext
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
from .budget import Budget, attempt, measured, run as budget_run
from .lyric_versions import phonetic_key
from .asr_phrases import key


def acoustic_phrases(python, source, source_sha, original, languages, directory, *,
                     stopped, log, info, excerpt_duration=0, details=None, retain_candidates=False):
    anchored = []
    merge_normalizer = phonetic_key if "ja" in languages else key
    for language in languages[:2]:
        segments = transcribe(python, source, source_sha, directory, stopped=stopped, log=log,
                              language=language, info=info)
        normalizer = phonetic_key if language == "ja" else key
        rows = phrases(json.loads(segments.read_text(encoding="utf-8")), original,
                       indices=True, normalizer=normalizer)
        anchored = combine(anchored, rows, original, normalizer=merge_normalizer) if anchored else rows
        log(f"Караоке: ASR {language or 'auto'} подтверждает {len(anchored)}/{len(original)} строк.")
        if excerpt_duration:
            from .acoustic_excerpt import select
            if select(anchored, excerpt_duration):
                break
        if len(anchored) >= len(original) * .8:
            break
    if details is not None:
        details.update(full_lyrics_lines=len(original), acoustically_matched_lines=len(anchored),
                       full_lyrics_coverage=len(anchored) / len(original))
    if excerpt_duration:
        from .acoustic_excerpt import select
        selected = select(anchored, excerpt_duration)
        if selected:
            if details is not None:
                details.update(confirmed_excerpt=[selected[0]["start"], selected[-1]["end"]],
                               selected_lyric_indices=[row["line_index"] for row in selected])
            log(f"Караоке: подтверждён непрерывный фрагмент {selected[0]['start']:.2f}–"
                f"{selected[-1]['end']:.2f} с; {len(selected)} строк без пропусков.")
            if not retain_candidates:
                anchored = selected
        else:
            raise SourceRejected("Нет непрерывного подтверждённого фрагмента достаточной длины.")
    elif len(anchored) < len(original) * .8:
        raise SourceRejected("Вокал не подтверждает 80% строк текста: кандидат отклонён.")
    return anchored if retain_candidates else [{k: v for k, v in row.items() if k != "line_index"}
                                              for row in anchored]


def _cached_details(target, details):
    if details is not None and target.with_suffix(".json").is_file():
        details.update(json.loads(target.with_suffix(".json").read_text(encoding="utf-8")))


def _take_model_slot(stack, stopped, seconds, timed):
    """The queue for the single ML slot has its own limit.

    The processing budget used to start before the slot was taken: a song
    waiting 300 s behind other recordings timed out before any work."""
    queue = Budget(stopped, seconds)
    with (timed or (lambda _: nullcontext()))("ожидание ML-обработчика"):
        try:
            stack.enter_context(model_slot(queue))
        except Exception:
            if not stopped() and queue():
                raise TimeoutError(f"Караоке: ML-обработчик занят дольше {queue.seconds:g} с.")
            raise


def align(source, sheet, settings, *, stopped, log, cache=None, timed=None,
          excerpt_duration=0, details=None, devices=None):
    original = clean_lines(sheet.original) if sheet else []
    if not original:
        raise ValueError("Для lyric-align нужен проверенный оригинальный текст песни.")
    digest = hashlib.sha256(source.read_bytes())
    source_sha = digest.hexdigest()
    digest.update("\n".join(original).encode())
    digest.update(b"lyric-align-0.4.1-medium-multilingual-kim-v6-windows")
    if excerpt_duration:
        digest.update(f"confirmed-excerpt-v1:{excerpt_duration}".encode())
    directory = Path(cache or Path.home() / ".cache/si-hyx-karaoke/alignment")
    target = directory / (digest.hexdigest() + ".ttml")
    if target.is_file():
        _cached_details(target, details)
        return read_ttml(target.read_bytes())
    directory.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        _take_model_slot(stack, stopped, getattr(settings, "karaoke_ai_queue_timeout", 1800), timed)
        with attempt(stopped, getattr(settings, "karaoke_ai_timeout", 300), timed) as budget:
            return _align_locked(source, source_sha, original, settings, directory, target,
                                 stopped=budget, log=log, excerpt_duration=excerpt_duration,
                                 details=details, devices=devices)


def _align_locked(source, source_sha, original, settings, directory, target, *, stopped, log,
                  excerpt_duration=0, details=None, devices=None):
    # Another queued question may have completed the same recording meanwhile.
    if target.is_file():
        _cached_details(target, details)
        return read_ttml(target.read_bytes())
    with measured("подготовка ML-обработчика"):
        python = ensure_runtime(settings, log, stopped)
    digest = target.stem
    work = directory / digest
    work.mkdir(exist_ok=True)
    lyrics, output = work / "lyrics.txt", work / "timed.ttml"
    asr_cache = directory / "asr-v3"
    languages = lyric_languages(python, original, work, stopped=stopped, log=log)
    # Devices are probed once per run, not by a new process for every song.
    devices = {} if devices is None else devices
    if str(python) not in devices:
        devices[str(python)] = device_info(python, stopped)
    info = dict(devices[str(python)])
    info["separator_policy"] = getattr(settings, "karaoke_separator", "auto")
    (work / "inputs.json").write_text(json.dumps({"source_sha256": source_sha,
        "languages": languages, "device": info}), encoding="utf-8")
    diagnostics = details if details is not None else {}
    if excerpt_duration:
        from .excerpt_alignment import run as align_windows
        lines, payload = align_windows(python, source, original, languages, asr_cache, work,
            info, excerpt_duration, diagnostics, acoustic_phrases, stopped=stopped, log=log)
        _record_backend(diagnostics, info)
        target.with_suffix(".json").write_text(json.dumps(diagnostics), encoding="utf-8")
        target.write_bytes(payload)
        return lines
    anchored = acoustic_phrases(python, source, source_sha, original, languages, asr_cache,
                                stopped=stopped, log=log, info=info,
                                excerpt_duration=excerpt_duration, details=diagnostics)
    if diagnostics.get("confirmed_excerpt"):
        original = [original[i] for i in diagnostics["selected_lyric_indices"]]
    lyrics.write_text("\n".join(original), encoding="utf-8")
    prepared = work / "phrases.json"
    prepared.write_text(json.dumps(anchored, ensure_ascii=False), encoding="utf-8")
    code, error = budget_run("выравнивание текста", run_process,
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
    if diagnostics.get("confirmed_excerpt"):
        if len(lines) != len(original):
            raise SourceRejected("В подтверждённом фрагменте lyric-align пропустил строку.")
        start, end = diagnostics["confirmed_excerpt"]
        start, end = max(start, lines[0].start), min(end, lines[-1].end)
        if end - start < excerpt_duration + .15:
            raise SourceRejected("Выравнивание не подтвердило всю длительность фрагмента.")
        diagnostics["confirmed_excerpt"] = [start, end]
    if excerpt_duration:
        diagnostics["aligned_lyrics_lines"] = len(lines)
    _record_backend(diagnostics, info)
    target.with_suffix(".json").write_text(json.dumps(diagnostics), encoding="utf-8")
    target.write_bytes(payload)
    return lines


def _record_backend(diagnostics, info):
    """Name the separator and ASR that actually ran, not the policy."""
    separator = str(info.get("used_separator") or "")
    if separator:
        diagnostics["separator_backend"] = ("HTDemucs" if separator == "htdemucs" else
                                            "Kim ONNX" if separator.startswith("kim-onnx") else separator)
    if info.get("used_asr"):
        diagnostics["asr_backend"] = info["used_asr"]
