"""Bounded BS-RoFormer/viperx CPU probe. Research only, not an app backend."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    import numpy as np
    import soundfile as sf
    import torch
    import yaml
    from chiptune.worker import track
    from chiptune.notes import validate_notes
    from chiptune.synthesis import render, write_wav

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    args = parser.parse_args()
    # The published viperx config targets the MSST fork, not the PyPI class.
    sys.path.insert(0, str(args.models / "msst"))
    from models.bs_roformer import BSRoformer
    args.output.mkdir(parents=True, exist_ok=True)
    result_path = args.output / "bs-roformer-result.json"
    result = {"model": "viperx model_bs_roformer_ep_317_sdr_12.9755",
              "source": str(args.source), "device": "cpu", "duration": 8}
    try:
        torch.set_num_threads(4)
        config = yaml.safe_load((args.models / "bs-roformer.yaml").read_text(
            encoding="utf-8").replace("!!python/tuple", ""))
        for name in ("freqs_per_bands", "multi_stft_resolutions_window_sizes"):
            config["model"][name] = tuple(config["model"][name])
        model = BSRoformer(**config["model"]).eval()
        state = torch.load(args.models / "bs-roformer.ckpt", map_location="cpu", weights_only=True)
        model.load_state_dict(state, strict=True)
        result["parameters"] = sum(p.numel() for p in model.parameters())
        audio, sr = sf.read(args.source, dtype="float32", always_2d=True)
        assert sr == 44100
        audio = audio[:sr * 8]
        started = time.monotonic()
        with torch.inference_mode():
            predicted = model(torch.from_numpy(audio.T.copy())[None])[0, 0].cpu().numpy()
        result["separation_seconds"] = time.monotonic() - started
        result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        np.save(args.output / "bs-vocals.npy", predicted)
        vocals = predicted.mean(axis=0)
        sf.write(args.output / "bs-vocals.wav", predicted.T, sr)
        notes = track(vocals)
        for note in notes:
            note["end"] = min(note["end"], 8.)
        result["note_metrics"] = validate_notes(notes, 8.)
        result["notes"] = notes
        options = {"seed": 19, "lead_volume": .85, "bass_volume": 0}
        write_wav(args.output / "bs-chiptune.wav", render(notes, [], 8., options))
    except Exception as error:
        result["error"] = str(error)
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "notes"}, indent=2))


if __name__ == "__main__":
    main()
