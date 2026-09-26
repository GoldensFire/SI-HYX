"""Compare vocal pitch estimators on cached stems without changing production."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    import librosa
    import numpy as np
    import soundfile as sf
    import torch
    from chiptune.notes import pitch_notes

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", choices=["rmvpe", "fcpe"], required=True)
    parser.add_argument("--rvc", type=Path)
    args = parser.parse_args()
    torch.set_num_threads(4)
    if args.source.suffix == ".npy":
        audio = np.load(args.source)
        audio = audio.mean(0) if audio.ndim == 2 else audio
        sr = 44100
    else:
        audio, sr = sf.read(args.source, dtype="float32", always_2d=True)
        audio = audio.mean(1)
    mono = librosa.resample(audio, orig_sr=sr, target_sr=16000)
    tensor = torch.from_numpy(mono.copy())[None]
    with torch.inference_mode():
        if args.model == "rmvpe":
            sys.path.insert(0, str(args.rvc))
            from rmvpe import RMVPE
            model = RMVPE(str(args.rvc / "rmvpe.pt"), is_half=False, device="cpu")
            hidden = model.mel2hidden(model.extract_mel(tensor))[0].cpu().numpy()
            pitch = model.decode(hidden, thred=.03)
            confidence = hidden.max(-1)
            threshold = .03
        else:
            from torchfcpe import spawn_bundled_infer_model
            model = spawn_bundled_infer_model(device="cpu")
            hidden = model.model(model.wav2mel(tensor[..., None], 16000))
            cents = model.model.latent2cents_local_decoder(hidden, threshold=.006)
            pitch = model.model.cent_to_f0(cents)[0, :, 0].cpu().numpy()
            confidence = hidden.max(-1)[0][0].cpu().numpy()
            threshold = .006
    rms = librosa.feature.rms(y=mono, frame_length=1024, hop_length=160)[0]
    notes = pitch_notes(pitch, confidence, rms, threshold=threshold)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez(args.output.with_suffix(".npz"), pitch=pitch, confidence=confidence, rms=rms)
    result = {"model": args.model, "source": str(args.source), "notes": notes,
              "coverage": sum(n["end"] - n["start"] for n in notes) / (len(audio) / sr)}
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "notes"}))
    print([(n["start"], n["end"], n["pitch"]) for n in notes])


if __name__ == "__main__":
    main()
