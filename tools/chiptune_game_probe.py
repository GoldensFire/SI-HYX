"""Research-only GAME ONNX note transcription; never mixes source into synthesis.

Run in an isolated Python 3.11 environment containing numpy, scipy, soundfile,
and onnxruntime. Official v1.0.3 exported models are loaded from --models.
Weights: CC BY-NC-SA 4.0; upstream code: MIT. No production backend is changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import numpy as np
import onnxruntime as ort
import soundfile as sf
from scipy.signal import resample_poly

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chiptune.synthesis import render, write_wav

UPSTREAM = "https://github.com/openvpi/GAME/tree/v1.0.3"
UPSTREAM_COMMIT = "475a8ee781fe8cca980b3b12fbe6c80c768a813a"


def read_source(path, sample_rate, stem):
    if path.suffix == ".npy":
        signal, rate = np.load(path, allow_pickle=False), sample_rate
    elif path.suffix == ".npz":
        with np.load(path, allow_pickle=False) as archive:
            signal = archive[stem]
        rate = sample_rate
    else:
        signal, rate = sf.read(path, dtype="float32", always_2d=True)
        signal = signal.mean(axis=1)
    if signal.ndim != 1 or not np.all(np.isfinite(signal)):
        raise ValueError("Expected finite mono input after decoding.")
    return np.asarray(signal, dtype=np.float32), rate


def session(path, threads):
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = threads
    opts.inter_op_num_threads = 1
    return ort.InferenceSession(str(path), sess_options=opts,
                               providers=["CPUExecutionProvider"])


def predict(signal, rate, args):
    """Mirror upstream forward_encoder/segmenter/estimator without Torch."""
    config = json.loads((args.models / "config.json").read_text(encoding="utf-8"))
    target_rate = config["samplerate"]
    if rate != target_rate:
        factor = math.gcd(rate, target_rate)
        signal = resample_poly(signal, target_rate // factor, rate // factor)
    signal = np.ascontiguousarray(signal, dtype=np.float32)
    duration = len(signal) / target_rate
    ort.set_seed(args.seed)
    sessions = {name: session(args.models / f"{name}.onnx", args.threads)
                for name in ("encoder", "segmenter", "bd2dur", "estimator")}
    x_seg, x_est, mask = sessions["encoder"].run(None, {
        "waveform": signal[None],
        "duration": np.array([duration], np.float32),
    })
    known = np.zeros(mask.shape, dtype=bool)
    boundaries = known.copy()
    language = config["languages"][args.language]
    steps = args.steps if config["loop"] else 1
    for i in range(steps):
        feed = {
            "x_seg": x_seg,
            "language": np.array([language], np.int64),
            "known_boundaries": known,
            "prev_boundaries": boundaries,
            "t": np.array([i / steps], np.float32),
            "maskT": mask,
            "threshold": np.array(args.boundary_threshold, np.float32),
            "radius": np.array(round(.02 / config["timestep"]), np.int64),
        }
        accepted = {x.name for x in sessions["segmenter"].get_inputs()}
        boundaries, = sessions["segmenter"].run(
            None, {k: v for k, v in feed.items() if k in accepted})
        print(f"Segmentation {i + 1}/{steps}", flush=True)
    durations, mask_n = sessions["bd2dur"].run(None, {
        "boundaries": boundaries, "maskT": mask,
    })
    presence, scores = sessions["estimator"].run(None, {
        "x_est": x_est, "boundaries": boundaries, "maskT": mask,
        "maskN": mask_n, "threshold": np.array(args.presence_threshold, np.float32),
    })
    events, cursor = [], 0.
    for length, present, pitch in zip(durations[0], presence[0], scores[0]):
        end = min(duration, cursor + float(length))
        events.append({"start": round(cursor, 5), "end": round(end, 5),
                       "pitch_float": float(pitch), "present": bool(present)})
        cursor = end
    return events, duration, config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--sample-rate", type=int, default=44100)
    parser.add_argument("--stem", default="vocals")
    parser.add_argument("--language", default="ja")
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--start", type=float, default=0.)
    parser.add_argument("--duration", type=float, default=0.)
    parser.add_argument("--boundary-threshold", type=float, default=.2)
    parser.add_argument("--presence-threshold", type=float, default=.2)
    args = parser.parse_args()
    if args.steps < 1 or args.threads < 1:
        parser.error("steps and threads must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    signal, rate = read_source(args.source, args.sample_rate, args.stem)
    start = max(0, round(args.start * rate))
    end = start + round(args.duration * rate) if args.duration > 0 else len(signal)
    signal = signal[start:end]
    started = time.perf_counter()
    events, duration, config = predict(signal, rate, args)
    elapsed = time.perf_counter() - started
    # The export returns binary presence, not calibrated confidence. 1.0 below
    # only adapts accepted notes to the existing renderer's research interface.
    notes = [{"start": x["start"], "end": x["end"],
              "pitch": int(round(x["pitch_float"])), "confidence": 1.}
             for x in events if x["present"] and x["end"] > x["start"]]
    report = {
        "upstream": UPSTREAM, "commit": UPSTREAM_COMMIT,
        "weights_license": "CC-BY-NC-SA-4.0", "code_license": "MIT",
        "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
        "source": str(args.source.resolve()), "crop_start": args.start,
        "duration": duration, "seconds": elapsed, "seed": args.seed,
        "steps": args.steps, "language": args.language,
        "boundary_threshold": args.boundary_threshold,
        "presence_threshold": args.presence_threshold,
        "config": config, "onnxruntime": ort.__version__,
        "hashes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted(args.models.glob("*.onnx"))},
        "events": events, "notes": notes,
        "confidence_note": "Binary model presence; confidence=1 is not a probability.",
    }
    try:
        audio = render(notes, [], duration,
                       {"seed": args.seed, "lead_volume": .85, "bass_volume": 0.})
        write_wav(args.output / "game-chiptune.wav", audio)
        report["rendered"] = True
    except ValueError as exc:
        report.update(rendered=False, rejection=str(exc))
    (args.output / "game-result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("duration", "seconds", "rendered")}
                     | {"notes": len(notes)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
