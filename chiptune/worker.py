"""Isolated Python 3.11 worker; never imported by the desktop application."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys

# The same source directory is shipped as data by PyInstaller.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

EXPECTED = {"torch": "2.5.1", "torchaudio": "2.5.1", "demucs": "4.0.1",
            "torchcrepe": "0.0.23", "numpy": "1.26.4", "librosa": "0.10.2.post1",
            "onnxruntime": "1.23.2", "soundfile": "0.13.1"}


def check_versions():
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError("Нужен отдельный Python 3.11; запустите установку обработчика.")
    for package, expected in EXPECTED.items():
        try:
            actual = importlib.metadata.version(package).split("+")[0]
        except importlib.metadata.PackageNotFoundError as error:
            raise RuntimeError(f"Нет пакета {package}. Нажмите «Установить модели».") from error
        if actual != expected:
            raise RuntimeError(f"{package}: требуется {expected}, установлен {actual}.")


def model_files():
    import torch
    import torchcrepe
    from chiptune.vocal_pitch import model_path
    return [Path(torch.hub.get_dir()) / "checkpoints/955717e8-8726e21a.th",
            Path(torchcrepe.__file__).parent / "assets/full.pth", model_path()]


def fingerprint():
    check_versions()
    hashes = []
    for path in model_files():
        if not path.is_file():
            raise RuntimeError("Нет модели Chiptune. Нажмите «Установить модели».")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        hashes.append(digest.hexdigest())
    from chiptune.vocal_pitch import RMVPE_SHA256
    if hashes[-1] != RMVPE_SHA256:
        raise RuntimeError("Модель RMVPE повреждена. Повторите установку моделей.")
    return {"separation": {"weights": hashes[0], "versions": {
                key: EXPECTED[key] for key in ("torch", "demucs", "numpy", "soundfile")}},
            "transcription": {"weights": hashes[1:], "versions": EXPECTED}}


def separate(source, target, seed):
    import numpy as np
    import soundfile as sf
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    fingerprint()  # missing models fail BEFORE get_model could download
    torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
    torch.manual_seed(seed)
    audio, sr = sf.read(source, dtype="float32", always_2d=True)
    if sr != 44100 or len(audio) > 61 * sr:
        raise ValueError("Обработчику нужен PCM 44.1 кГц длиной до 60 секунд.")
    model = get_model("htdemucs").cpu().eval()
    wav = torch.from_numpy(audio.T.copy())
    if wav.shape[0] == 1:
        wav = wav.repeat(2, 1)
    ref = wav.mean(0)
    mean, std = ref.mean(), ref.std()
    if std < .0001:
        raise ValueError("Исходный фрагмент почти без звука.")
    with torch.inference_mode():
        separated = apply_model(model, ((wav - mean) / std)[None],
                                device="cpu", shifts=0, overlap=.25,
                                split=True, progress=False, num_workers=0)[0]
    separated = separated * std  # DC mean is unnecessary for pitch estimation
    np.savez_compressed(target, **{name: separated[i].mean(0).numpy()
                                  for i, name in enumerate(model.sources)})


def track(audio, *, low=65, high=1400):
    import librosa
    import torch
    import torchcrepe
    from chiptune.notes import pitch_notes

    sr, hop = 16000, 160
    torch.manual_seed(0)  # torchcrepe's pitch-bin conversion adds tiny dither
    mono = librosa.resample(audio, orig_sr=44100, target_sr=sr)
    tensor = torch.from_numpy(mono.copy())[None]
    with torch.inference_mode():
        pitch, confidence = torchcrepe.predict(
            tensor, sr, hop, low, high, model="full", batch_size=64,
            device="cpu", return_periodicity=True)
    confidence = torchcrepe.filter.median(confidence, 3)
    # Use RMS gating in pitch_notes. CREPE's spectral A-weighted silence gate
    # can label a loud sparse harmonic instrument as silence (synthetic probe).
    pitch = torchcrepe.filter.mean(pitch, 3)
    rms = librosa.feature.rms(y=mono, frame_length=1024, hop_length=hop)[0]
    return pitch_notes(pitch[0].numpy(), confidence[0].numpy(), rms,
                       midi_low=24 if low < 65 else 45,
                       midi_high=72 if low < 65 else 90)


def transcribe(source, target, lead):
    import numpy as np
    import torch
    from chiptune.notes import QualityError, validate_notes
    from chiptune.vocal_pitch import track_vocals

    torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
    with np.load(source, allow_pickle=False) as stems:
        duration = len(stems["vocals"]) / 44100
        candidates, errors = [], []
        # Prefer the singing melody. Auto tries other only if vocals fail
        # quality gates; never run pitch extraction on the original mixture.
        for name in (["vocals", "other"] if lead == "auto" else [lead]):
            notes = track_vocals(stems[name]) if name == "vocals" else track(stems[name])
            for note in notes:
                note["end"] = min(note["end"], duration)
            try:
                metrics = validate_notes(notes, duration)
                candidates.append((name, notes, metrics))
                break
            except QualityError as error:
                errors.append(f"{name}: {error}")
        if not candidates:
            raise QualityError("; ".join(errors))
        name, notes, metrics = candidates[0]
        bass = track(stems["bass"], low=32, high=500)
        for note in bass:
            note["end"] = min(note["end"], duration)
        try:
            bass_metrics = validate_notes(bass, duration, minimum_coverage=.25)
            if bass_metrics["confidence"] < .78:
                bass = []
        except QualityError:
            bass = []
    payload = {"lead": name, "notes": notes, "bass": bass, "metrics": metrics,
               "duration": duration}
    Path(target).write_text(json.dumps(payload), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["probe", "install", "separate", "transcribe"])
    parser.add_argument("--source")
    parser.add_argument("--target", required=True)
    parser.add_argument("--lead", default="auto", choices=["auto", "vocals", "other"])
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    # User-writable, stable location independent of the app/EXE directory.
    os.environ["TORCH_HOME"] = str(Path.home() / ".cache/si-hyx-chiptune/models")
    check_versions()
    if args.operation == "install":
        from demucs.pretrained import get_model
        from chiptune.vocal_pitch import install_model
        get_model("htdemucs")
        install_model(Path(args.target).parent)
    if args.operation in ("probe", "install"):
        Path(args.target).write_text(json.dumps(fingerprint()), encoding="utf-8")
    elif args.operation == "separate":
        separate(args.source, args.target, args.seed)
    else:
        fingerprint()
        transcribe(args.source, args.target, args.lead)


if __name__ == "__main__":
    # -I deliberately ignores PYTHONIOENCODING. Keep Russian failures readable
    # through the parent's UTF-8 pipe on Windows with any system code page.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        main()
    except Exception as error:
        print(f"Chiptune: {error}", file=sys.stderr)
        raise SystemExit(1)
