"""Separate cancellable model stages and persistent, recording-specific stem caching."""
from __future__ import annotations

import json
from pathlib import Path

from chiptune.runtime import run_process

WORKER = Path(__file__).with_name("asr_worker.py")


def device_info(python, stopped):
    code, output = run_process([str(python), "-I", "-X", "utf8", str(WORKER), "devices"],
                               30, stopped=stopped)
    if not code:
        try:
            return json.loads(output.strip().splitlines()[-1])
        except (ValueError, IndexError):
            pass
    return {"asr": "cpu", "compute": "int8", "demucs": "cpu"}


def transcribe(python, source, source_sha, directory, *, stopped, log):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (source_sha + ".json")
    if target.is_file():
        return target
    settings = device_info(python, stopped)
    work = directory / source_sha
    work.mkdir(exist_ok=True)
    vocals = work / "vocals.wav"
    command = [str(python), "-I", "-X", "utf8", str(WORKER)]
    if not vocals.is_file():
        log(f"Караоке: Demucs отделяет вокал ({settings['demucs'].upper()})…")
        code, output = run_process([*command, "separate", str(source), str(vocals),
                                    "--device", settings["demucs"]], 900, stopped=stopped)
        (work / "separation.txt").write_text(output, encoding="utf-8")
        if code or not vocals.is_file():
            raise ValueError("Demucs: " + output[-500:])
    else:
        log("Караоке: вокал взят из кэша; повторное разделение не требуется.")
    log(f"Караоке: Whisper medium распознаёт вокал ({settings['asr'].upper()}, beam=1)…")
    code, output = run_process([*command, "transcribe", str(vocals), str(target),
                                "--device", settings["asr"], "--compute", settings["compute"]],
                               900, stopped=stopped)
    # CTranslate2 can see an NVIDIA driver before noticing missing CUDA/cuDNN DLLs.
    if code and settings["asr"] == "cuda" and not stopped():
        log("Караоке: CUDA недоступна обработчику; повторяю распознавание на CPU.")
        code, output = run_process([*command, "transcribe", str(vocals), str(target),
                                    "--device", "cpu", "--compute", "int8"], 900, stopped=stopped)
    (work / "transcription.txt").write_text(output, encoding="utf-8")
    if code or not target.is_file():
        raise ValueError("Whisper: " + output[-500:])
    return target
