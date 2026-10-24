# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Обработчик карты песни в Python генератора (music_effects.runtime_python):
torch, Beat This!, HTDemucs и librosa не грузятся в приложение.

    python -I -X utf8 music_worker.py beats <звук.wav> <итог.json> --checkpoint <ckpt>
    python -I -X utf8 music_worker.py stems <звук.wav> <папка>
    python -I -X utf8 music_worker.py features <звук.wav> <доли.json> <итог.json> [--vocals …]

beats — доли и сильные доли Beat This! без DBN (секунды); stems — барабаны и
вокал HTDemucs (4 стема той же модели, что у караоке) моно 24 кГц; features —
признаки по долям: хрома (CQT), MFCC, громкость, яркость. Итог пишется
атомарно (временный файл → замена); прогресс — строки JSON в stdout."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

STEM_RATE = 24000                # сетка 10 мс — ровно 240 сэмплов, тарелки до 12 кГц
FEATURE_RATE = 22050


def _threads():
    try:
        n = int(os.environ.get("SI_HYX_ML_THREADS", "6"))
    except ValueError:
        n = 6
    return max(1, min(os.cpu_count() or 1, n))


def _say(stage, **kw):
    print(json.dumps(dict({"stage": stage}, **kw), ensure_ascii=False), flush=True)


def _write_json(obj, target):
    target = Path(target)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    tmp.replace(target)


def beats(source, target, checkpoint):
    import numpy as np
    import soundfile as sf
    import torch
    from beat_this.inference import Audio2Beats
    torch.set_num_threads(_threads())
    x, sr = sf.read(str(source), dtype="float32", always_2d=True)
    _say("beats", model=Path(checkpoint).stem)
    a2b = Audio2Beats(checkpoint_path=str(checkpoint), device="cpu", dbn=False)
    with torch.inference_mode():
        b, d = a2b(x, sr)
    _write_json({"beats": [round(float(v), 4) for v in np.asarray(b)],
                 "downbeats": [round(float(v), 4) for v in np.asarray(d)],
                 "model": Path(checkpoint).stem}, target)


def _mono_24k(path, target):
    import numpy as np
    import soundfile as sf
    import soxr
    x, sr = sf.read(str(path), dtype="float32", always_2d=True)
    y = soxr.resample(x.mean(axis=1), sr, STEM_RATE).astype(np.float32)
    tmp = Path(target).with_suffix(".tmp.wav")
    sf.write(str(tmp), y, STEM_RATE, subtype="PCM_16")
    tmp.replace(target)


def stems(source, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="demucs-", dir=out) as directory:
        work = Path(directory).resolve()
        if work.parent != out.resolve():
            raise ValueError("временная папка Demucs вне папки стемов")
        _say("stems")
        n = str(_threads())
        subprocess.run([sys.executable, "-I", "-m", "demucs", "-n", "htdemucs", "--shifts", "0",
                        "-d", "cpu", "-o", str(work), str(source)], check=True,
                       env={**os.environ, "OMP_NUM_THREADS": n, "MKL_NUM_THREADS": n})
        found = work / "htdemucs" / Path(source).stem
        for name in ("drums", "vocals"):
            _mono_24k(found / f"{name}.wav", out / f"{name}.wav")


def _beat_frames(grid, n, sr, hop):
    import librosa
    import numpy as np
    frames = librosa.time_to_frames(np.asarray(grid, float), sr=sr, hop_length=hop)
    edges = np.clip(np.concatenate([frames, [n]]), 0, n)
    return [(int(a), int(max(b, a + 1))) for a, b in zip(edges[:-1], edges[1:])]


def features(source, beats_json, target, vocals=""):
    """Признаки на каждую долю (от доли до следующей): хрома 12 (CQT), MFCC
    13, громкость dB, яркость (центроид, Гц), сила начала звука; с вокалом
    (стем) — его хрома, взвешенная громкостью (мелодия: припев поётся
    одинаково, а гармония куплета и припева у рока одна), и громкость."""
    import librosa
    import numpy as np
    grid = json.loads(Path(beats_json).read_text(encoding="utf-8"))["beats"]
    y, sr = librosa.load(str(source), sr=FEATURE_RATE, mono=True)
    hop = 512
    _say("features")
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13, hop_length=hop)
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    cent = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=hop)[0]
    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    n = min(chroma.shape[1], mfcc.shape[1], len(rms), len(cent), len(onset))
    vch = vrms = None
    if vocals:
        v, _ = librosa.load(str(vocals), sr=FEATURE_RATE, mono=True)
        vch = librosa.feature.chroma_cqt(y=v, sr=sr, hop_length=hop)
        vrms = librosa.feature.rms(y=v, hop_length=hop)[0]
    rows = []
    for a, b in _beat_frames(grid, n, sr, hop):
        sl = slice(a, min(b, n))
        row = {
            "chroma": [round(float(x), 4) for x in np.median(chroma[:, sl], axis=1)],
            "mfcc": [round(float(x), 3) for x in mfcc[:, sl].mean(axis=1)],
            "db": round(float(20 * np.log10(np.sqrt(np.mean(rms[sl] ** 2)) + 1e-9)), 2),
            "centroid": round(float(cent[sl].mean()), 1),
            "onset": round(float(onset[sl].mean()), 4)}
        if vch is not None:
            vs = slice(min(a, vch.shape[1] - 1), min(b, vch.shape[1]))
            w = vrms[vs] ** 2
            vc = (vch[:, vs] * w).sum(axis=1) / (w.sum() + 1e-12)
            row["vchroma"] = [round(float(x), 4) for x in vc]
            row["vdb"] = round(float(10 * np.log10(w.mean() + 1e-12)), 2)
        rows.append(row)
    _write_json({"rows": rows[:len(grid)], "hop_s": hop / sr}, target)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("beats", "stems", "features"))
    ap.add_argument("source")
    ap.add_argument("target")
    ap.add_argument("extra", nargs="?")
    ap.add_argument("--checkpoint", default="")
    ap.add_argument("--vocals", default="")
    args = ap.parse_args()
    if args.action == "beats":
        beats(args.source, args.target, args.checkpoint)
    elif args.action == "stems":
        stems(args.source, args.target)
    else:
        features(args.source, args.target, args.extra, args.vocals)


if __name__ == "__main__":
    main()
