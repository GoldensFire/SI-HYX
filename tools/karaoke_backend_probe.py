"""Measure isolated karaoke workers on real audio, retaining logs and stems."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from music_effects import runtime_python
from chiptune.gate import model_slot


def measured(command, log, timeout, memory_limit):
    started = time.monotonic()
    peak_rss = peak_private = 0
    reason = ""
    with log.open("wb") as stream:
        process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT)
        owner = psutil.Process(process.pid)
        while process.poll() is None:
            rss = private = 0
            try:
                family = [owner, *owner.children(recursive=True)]
            except psutil.Error:
                family = []
            for child in family:
                try:
                    info = child.memory_info()
                    rss += info.rss
                    private += getattr(info, "private", info.vms)
                except psutil.Error:
                    pass
            peak_rss, peak_private = max(peak_rss, rss), max(peak_private, private)
            elapsed = time.monotonic() - started
            if elapsed >= timeout or private > memory_limit * 2**30:
                reason = "timeout" if elapsed >= timeout else "memory_limit"
                for child in reversed(family):
                    try:
                        child.kill()
                    except psutil.Error:
                        pass
                process.wait(timeout=20)
                break
            time.sleep(.25)
    return {"seconds": round(time.monotonic() - started, 3),
            "exit_code": process.returncode, "stopped_by": reason,
            "peak_rss_gib": round(peak_rss / 2**30, 3),
            "peak_private_gib": round(peak_private / 2**30, 3), "log": str(log)}


def audio_metrics(path):
    import numpy as np
    import soundfile as sf

    samples, rate = sf.read(path, always_2d=True)
    return {"audio_seconds": len(samples) / rate, "sample_rate": rate,
            "channels": samples.shape[1], "finite": bool(np.isfinite(samples).all()),
            "rms": float(np.sqrt(np.mean(samples**2))),
            "peak": float(np.max(np.abs(samples)))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend", choices=("kim-onnx", "htdemucs", "whisper.cpp",
                                             "faster-whisper"), required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--memory-limit", type=float, default=5)
    parser.add_argument("--language", default="ja")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    stem = args.backend + "-" + args.device
    action = "separate" if args.backend in ("kim-onnx", "htdemucs") else "transcribe"
    target = args.output / (stem + (".wav" if action == "separate" else ".json"))
    if target.exists():
        parser.error("Output already exists; use a fresh output directory for a timed run.")
    command = [str(runtime_python()), "-I", "-X", "utf8",
               str(Path(__file__).resolve().parent.parent / "karaoke/asr_worker.py"),
               action, str(args.source.resolve()), str(target.resolve()),
               "--backend", args.backend, "--device", args.device,
               "--ffmpeg", shutil.which("ffmpeg") or "ffmpeg",
               "--language", args.language]
    report = {"source": str(args.source.resolve()), "backend": args.backend,
              "device": args.device, "memory_limit_gib": args.memory_limit,
              "system_available_gib": psutil.virtual_memory().available / 2**30}
    print(f"Starting {stem}", flush=True)
    with model_slot(lambda: False):
        report.update(measured(command, args.output / (stem + ".log"),
                               args.timeout, args.memory_limit))
    report["output_exists"] = target.is_file()
    if not report["exit_code"] and target.is_file() and action == "separate":
        report.update(audio_metrics(target))
        report["real_time_factor"] = report["seconds"] / report["audio_seconds"]
    (args.output / (stem + "-report.json")).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
