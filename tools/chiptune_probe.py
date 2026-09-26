"""Reproducible musical probes; run with the isolated Python 3.11 interpreter."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from chiptune.notes import validate_notes
from chiptune.runtime import run_process
from chiptune.service import ChiptuneService
from chiptune.synthesis import render, write_wav
from chiptune.worker import track


def known_melody(directory):
    """Uneven timing, rests, vibrato and strong overtones, known ground truth."""
    pitches = [60, 62, 64, 67, 64, 62, 60, 64, 67, 69, 67, 64, 62, 60]
    lengths = [.43, .51, .48, .78, .34, .61, .74, .42, .49, .63, .45, .54, .51, .8]
    cursor, expected = .25, []
    for pitch, length in zip(pitches, lengths):
        expected.append({"start": cursor, "end": cursor + length, "pitch": pitch, "confidence": 1.})
        cursor += length + .075
    duration = cursor + .2
    source = np.zeros(round(duration * 44100), dtype=np.float32)
    for note in expected:
        start, end = round(note["start"] * 44100), round(note["end"] * 44100)
        t = np.arange(end - start) / 44100
        frequency = 440 * 2 ** ((note["pitch"] - 69) / 12)
        phase = np.cumsum(frequency * 2 ** (.18 * np.sin(2 * np.pi * 5.3 * t) / 12)) * 2 * np.pi / 44100
        voice = sum(weight * np.sin(phase * harmonic) for harmonic, weight in
                    [(1, .24), (2, .32), (3, .2), (4, .12), (6, .06)])
        edge = min(500, len(voice) // 2)
        voice[:edge] *= np.linspace(0, 1, edge)
        voice[-edge:] *= np.linspace(1, 0, edge)
        source[start:end] = voice
    directory.mkdir(parents=True, exist_ok=True)
    write_wav(directory / "original.wav", source)
    return source, expected, duration


def compare(directory):
    import torch
    torch.set_num_threads(4)
    source, expected, duration = known_melody(directory)
    started = time.monotonic()
    notes = track(source)
    results = {"crepe": {"seconds": time.monotonic() - started,
                          "notes": notes, "quality": validate_notes(notes, duration)}}
    options = {"seed": 19, "lead_volume": .85, "bass_volume": 0}
    write_wav(directory / "chiptune.wav", render(notes, [], duration, options))
    # Score stable note centres against the known score, not against our renderer.
    def score(events):
        hits, present, strongest, extras = 0, 0, 0, 0
        for wanted in expected:
            centre = (wanted["start"] + wanted["end"]) / 2
            active = [event for event in events if event["start"] <= centre <= event["end"]]
            hits += len(active) == 1 and active[0]["pitch"] == wanted["pitch"]
            present += any(event["pitch"] == wanted["pitch"] for event in active)
            strongest += bool(active) and max(active, key=lambda n: n["confidence"])["pitch"] == wanted["pitch"]
            extras += max(0, len(active) - 1)
        return {"single_correct_note_centres": hits, "correct_pitch_present": present,
                "strongest_correct": strongest, "extra_active_notes": extras,
                "total": len(expected), "monophonic_accuracy": hits / len(expected)}
    results["crepe"].update(score(notes))
    try:
        from basic_pitch.inference import predict, Model
        import basic_pitch
        model_path = Path(basic_pitch.__file__).parent / "saved_models/icassp_2022/nmp.onnx"
        started = time.monotonic()
        _, _, events = predict(str(directory / "original.wav"), Model(str(model_path)))
        basic = [{"start": float(a), "end": float(b), "pitch": int(c), "confidence": float(d)}
                 for a, b, c, d, *_ in events]
        results["basic_pitch"] = {"seconds": time.monotonic() - started,
                                  "notes": basic, **score(basic)}
    except Exception as error:
        results["basic_pitch"] = {"error": str(error)}
    results["expected"] = expected
    (directory / "comparison.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps({key: {k: v for k, v in result.items() if k != "notes"}
                      for key, result in results.items() if key != "expected"}, indent=2))


def real_examples(output, python):
    import librosa
    from music_effects import VERSION
    settings = SimpleNamespace(chiptune_python=python, chiptune_version=VERSION,
                               chiptune_seed=19, chiptune_lead="auto", chiptune_lead_volume=85,
                               chiptune_bass_volume=25)
    service = ChiptuneService(settings, run_process, "ffmpeg", log=lambda text: print(text, flush=True))
    results = []
    for name, start, length, lead in [("fishin", 35, 15, "vocals"),
                                      ("fishin", 75, 15, "vocals"),
                                      ("nutcracker", 15, 15, "other")]:
        directory = output / f"{name}-{start}"
        directory.mkdir(parents=True, exist_ok=True)
        try:
            source = librosa.ex(name, hq=True)
            settings.chiptune_lead = lead
            code, error = run_process(["ffmpeg", "-y", "-v", "error", "-ss", str(start),
                                       "-i", source, "-t", str(length), str(directory / "original.wav")])
            if code:
                raise RuntimeError(error)
            started = time.monotonic()
            metadata = service.convert(source, directory / "chiptune.wav", start, length)
            metadata["elapsed"] = time.monotonic() - started
            (directory / "processing.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            results.append({"example": directory.name, "metrics": metadata["note_metrics"],
                            "elapsed": metadata["elapsed"]})
        except Exception as error:
            results.append({"example": directory.name, "rejected": str(error)})
        print(results[-1], flush=True)
        (output / "real-results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


def compare_vocal(directory):
    import torch
    from chiptune.vocal_pitch import track_vocals
    torch.set_num_threads(4)
    source, expected, duration = known_melody(directory)
    notes = track_vocals(source)
    correct = 0
    for wanted in expected:
        centre = (wanted["start"] + wanted["end"]) / 2
        active = [note for note in notes if note["start"] <= centre < note["end"]]
        correct += len(active) == 1 and active[0]["pitch"] == wanted["pitch"]
    result = {"notes": notes, "expected": expected, "correct": correct,
              "total": len(expected), "metrics": validate_notes(notes, duration)}
    (directory / "comparison.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    write_wav(directory / "chiptune.wav", render(notes, [], duration,
              {"seed": 19, "lead_volume": .85, "bass_volume": 0}))
    print(f"RMVPE: {correct}/{len(expected)} correct single note centres; {result['metrics']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--vocal", action="store_true", help="Known melody through production RMVPE")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.vocal:
        compare_vocal(args.output / "synthetic-rmvpe")
    elif args.real:
        real_examples(args.output, sys.executable)
    else:
        compare(args.output / "synthetic")


if __name__ == "__main__":
    main()
