"""RMVPE ONNX vocal melody inference in the isolated worker.

Input features and local-cent decoding follow the RVC implementation:
https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI
Only note events leave this module; there is no speech/vocoder synthesis.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import urllib.request

RMVPE_SHA256 = "5370e71ac80af8b4b7c793d27efd51fd8bf962de3a7ede0766dac0befa3660fd"
RMVPE_URL = ("https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/"
             "e6d0c1a17da07c33557852f9dfa2bd44cc75737d/rmvpe.onnx")


def model_path():
    return Path.home() / ".cache/si-hyx-chiptune/models/rmvpe.onnx"


def install_model(workdir=None):
    target = model_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == RMVPE_SHA256:
        return
    with tempfile.TemporaryDirectory(prefix="rmvpe-", dir=workdir or target.parent) as directory:
        temporary = Path(directory) / "model.onnx"
        with urllib.request.urlopen(RMVPE_URL, timeout=60) as source, temporary.open("wb") as output:
            digest = hashlib.sha256()
            while block := source.read(1024 * 1024):
                digest.update(block)
                output.write(block)
        if digest.hexdigest() != RMVPE_SHA256:
            raise RuntimeError("Контрольная сумма RMVPE не совпала; повторите установку моделей.")
        temporary.replace(target)


def pitch_frames(audio):
    import librosa
    import numpy as np
    import onnxruntime as ort
    import torch

    mono = librosa.resample(audio, orig_sr=44100, target_sr=16000)
    tensor = torch.from_numpy(mono.copy())[None]
    spectrum = torch.stft(tensor, n_fft=1024, hop_length=160, win_length=1024,
                          window=torch.hann_window(1024), center=True, return_complex=True)
    basis = librosa.filters.mel(sr=16000, n_fft=1024, n_mels=128,
                               fmin=30, fmax=8000, htk=True)
    mel = torch.log(torch.clamp(torch.from_numpy(basis) @ spectrum.abs(), min=1e-5)).numpy()
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(model_path()), sess_options=options,
                                   providers=["CPUExecutionProvider"])
    hidden = infer_chunks(session, mel)
    confidence = hidden.max(-1)
    centres = hidden.argmax(-1)
    # Weighted average in a narrow neighbourhood around the dominant peak.
    bins = np.arange(hidden.shape[-1])
    local = hidden * (np.abs(bins[None, :] - centres[:, None]) <= 4)
    cents = 20 * bins + 1997.3794084376191
    frequency = 10 * 2 ** ((local @ cents / np.maximum(local.sum(-1), 1e-12)) / 1200)
    frequency[confidence < .15] = 0
    rms = librosa.feature.rms(y=mono, frame_length=1024, hop_length=160)[0]
    return frequency, confidence, rms


def infer_chunks(session, mel):
    """Bound activation memory even for 60 s questions; keep border context."""
    import numpy as np
    frames, core, context = mel.shape[-1], 1536, 128
    input_name = session.get_inputs()[0].name
    chunks = []
    for start in range(0, frames, core):
        end = min(start + core, frames)
        left, right = max(0, start - context), min(frames, end + context)
        segment = mel[..., left:right]
        segment = np.pad(segment, ((0, 0), (0, 0), (0, (-(right - left)) % 32)))
        hidden = session.run(None, {input_name: segment})[0][0]
        chunks.append(hidden[start - left:end - left])
    return np.concatenate(chunks)


def track_vocals(audio):
    from .notes import pitch_notes
    pitch, confidence, rms = pitch_frames(audio)
    return pitch_notes(pitch, confidence, rms, threshold=.15, stabilize=True)
