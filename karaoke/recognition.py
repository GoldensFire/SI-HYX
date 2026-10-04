"""Cancellable backend routing, separate stem cache and backend/language ASR keys."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import os
import re

from chiptune.runtime import run_process
from .ai_runtime import ensure_packages, ensure_separator
from .ai_assets import KIM_SHA

WORKER = Path(__file__).with_name("asr_worker.py")
_FAILED_SEPARATORS = set()


def separation_error(output):
    # ORT writes some Windows diagnostics as UTF-16 into an otherwise UTF-8
    # stream; its Python binding can then hide the actual HRESULT behind a
    # UnicodeDecodeError. Keep the native error, not just the traceback tail.
    output = output.replace("\0", "")
    if "8007000E" in output.upper():
        return "ONNX Runtime: нехватка памяти (8007000E)."
    rows = [row.strip() for row in output.splitlines()
            if "Status Message:" in row or "Error:" in row or "Exception:" in row]
    return re.sub(r"\x1b\[[0-9;]*m", "", rows[-1] if rows else output[-500:])[-500:]


def device_info(python, stopped):
    code, output = run_process([str(python), "-I", "-X", "utf8", str(WORKER), "devices"],
                               30, stopped=stopped)
    if not code:
        try:
            return json.loads(output.strip().splitlines()[-1])
        except (ValueError, IndexError):
            pass
    return {"backend": "faster-whisper", "asr": "cpu", "compute": "int8",
            "separator": "cpu", "demucs": "cpu"}


def _model_identity(default, variable):
    custom = os.environ.get(variable)
    if not custom:
        return default
    path = Path(custom)
    try:
        stat = path.stat()
        signature = f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"
    except OSError:
        signature = str(path)
    return hashlib.sha256(signature.encode()).hexdigest()[:16]


def vocal_source(python, source, source_sha, directory, info, *, stopped, log):
    command = [str(python), "-I", "-X", "utf8", str(WORKER)]
    identity = _model_identity(KIM_SHA[:16], "SI_HYX_KIM_ONNX")
    base = directory / "vocals"
    kim = base / ("kim-onnx-" + identity) / source_sha / "vocals.wav"
    demucs = base / "htdemucs" / source_sha / "vocals.wav"
    if kim.is_file():
        return kim, "kim-onnx-" + identity
    kim.parent.mkdir(parents=True, exist_ok=True)
    preferred = info.get("separator", "cpu")
    providers = [preferred] + (["cpu"] if preferred != "cpu" else [])
    for provider in providers:
        backend_key = (str(python), provider, identity)
        if backend_key in _FAILED_SEPARATORS:
            continue
        try:
            ensure_separator(python, provider, stopped=stopped, log=log)
            log(f"Караоке: MelBand RoFormer Kim отделяет вокал ({provider.upper()})…")
            code, output = run_process([*command, "separate", str(source), str(kim),
                                       "--backend", "kim-onnx", "--device", provider], 1800, stopped=stopped)
            (kim.parent / f"separation-{provider}.txt").write_text(output, encoding="utf-8")
            if code or not kim.is_file():
                raise ValueError(separation_error(output))
            return kim, "kim-onnx-" + identity
        except (RuntimeError, ValueError, OSError) as error:
            if stopped():
                raise RuntimeError("Караоке: остановлено.") from error
            log(f"Караоке: Kim ONNX ({provider.upper()}): {error}")
            if any(token in str(error).casefold() for token in
                   ("onnx", "directml", "cuda", "download", "checksum", "gpu")):
                _FAILED_SEPARATORS.add(backend_key)
            if provider != "cpu":
                log("Караоке: повторяю Kim ONNX на CPU.")
    log("Караоке: Kim ONNX недоступен на GPU и CPU; использую HTDemucs.")
    legacy = [directory / source_sha / "vocals.wav",
              directory.parent / "asr-medium-ja-demucs-v2" / source_sha / "vocals.wav"]
    for path in [demucs, *legacy]:
        if path.is_file():
            log("Караоке: вокал HTDemucs взят из кэша.")
            return path, "htdemucs"
    demucs.parent.mkdir(parents=True, exist_ok=True)
    ensure_packages(python, ["demucs"], ["demucs==4.0.1"], stopped=stopped, log=log)
    log(f"Караоке: HTDemucs отделяет вокал ({info['demucs'].upper()})…")
    code, output = run_process([*command, "separate", str(source), str(demucs),
                               "--backend", "htdemucs", "--device", info["demucs"]], 900, stopped=stopped)
    if code and info["demucs"] == "cuda" and not stopped():
        code, output = run_process([*command, "separate", str(source), str(demucs),
                                   "--backend", "htdemucs", "--device", "cpu"], 900, stopped=stopped)
    (demucs.parent / "separation.txt").write_text(output, encoding="utf-8")
    if code or not demucs.is_file():
        raise ValueError("HTDemucs: " + output[-500:])
    return demucs, "htdemucs"


def asr_target(directory, source_sha, backend, model, language, device, compute, separator):
    identity = ("asr-v3", backend, model, language or "auto", device, compute, separator)
    key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    work = Path(directory) / key
    work.mkdir(parents=True, exist_ok=True)
    (work / "backend.json").write_text(json.dumps(dict(zip(
        ("version", "backend", "model", "language", "device", "compute", "separator"), identity))),
        encoding="utf-8")
    return work / (source_sha + ".json")


def transcribe(python, source, source_sha, directory, *, stopped, log, language=None,
               model="medium", info=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    info = info or device_info(python, stopped)
    backend = info.get("backend", "faster-whisper")
    model_id = _model_identity(model, "SI_HYX_WHISPER_MODEL") if backend == "whisper.cpp" else model
    kim_id = "kim-onnx-" + _model_identity(KIM_SHA[:16], "SI_HYX_KIM_ONNX")
    attempts = [(backend, info["asr"], info["compute"])]
    if info["asr"] != "cpu":
        attempts.append(("faster-whisper", "cpu", "int8"))
    for engine, device, compute in attempts:
        for separator in (kim_id, "htdemucs"):
            identity = model_id if engine == "whisper.cpp" else model
            target = asr_target(directory, source_sha, engine, identity, language, device, compute, separator)
            if target.is_file():
                return target
    vocals, separator = vocal_source(python, source, source_sha, directory, info, stopped=stopped, log=log)
    command = [str(python), "-I", "-X", "utf8", str(WORKER)]
    for engine, device, compute in attempts:
        identity = model_id if engine == "whisper.cpp" else model
        target = asr_target(directory, source_sha, engine, identity, language, device, compute, separator)
        log(f"Караоке: {engine} {model} распознаёт вокал ({device.upper()}, {language or 'auto'}, beam=1)…")
        code, output = run_process([*command, "transcribe", str(vocals), str(target),
                                   "--backend", engine, "--model", model, "--language", language or "auto",
                                   "--device", device, "--compute", compute], 1800, stopped=stopped)
        (target.parent / (source_sha + "-transcription.txt")).write_text(output, encoding="utf-8")
        if not code and target.is_file():
            return target
        if stopped():
            raise RuntimeError("Караоке: остановлено.")
        if device != "cpu":
            log("Караоке: ускоренный ASR недоступен; повторяю faster-whisper на CPU int8.")
    raise ValueError("Whisper: " + output[-500:])
