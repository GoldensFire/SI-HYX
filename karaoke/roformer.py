"""Kim MelBand RoFormer ONNX spectrogram inference with overlapping audio chunks."""
from __future__ import annotations

import json
from math import gcd
from pathlib import Path


def session_for(path, provider):
    import onnxruntime as ort
    requested = {"directml": "DmlExecutionProvider", "cuda": "CUDAExecutionProvider",
                 "cpu": "CPUExecutionProvider"}[provider]
    if requested not in ort.get_available_providers():
        raise RuntimeError("ONNX provider unavailable: " + requested)
    options = ort.SessionOptions()
    options.enable_mem_pattern = False
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    if provider == "cpu":
        # Keep the CPU retry's retained memory and thread count bounded while
        # the desktop app and other generation workers are still running.
        options.enable_cpu_mem_arena = False
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
        options.intra_op_num_threads = 4
    if provider == "directml":
        # Fusing the whole transformer can exhaust shared memory on iGPUs.
        options.add_session_config_entry("ep.dml.disable_graph_fusion", "1")
    session = ort.InferenceSession(str(path), sess_options=options,
                                   providers=[requested, "CPUExecutionProvider"] if provider != "cpu"
                                   else [requested])
    session.disable_fallback()
    if requested not in session.get_providers():
        raise RuntimeError("ONNX did not activate " + requested)
    return session


def separate(source, target, provider, *, ffmpeg="ffmpeg"):
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    from .ai_assets import kim_model
    from .stft import forward, inverse
    from .audio_chunks import pad_context, chunks
    from .input_audio import read

    mix, source_sr = read(source, ffmpeg)
    if not len(mix) or not np.isfinite(mix).all():
        raise ValueError("Аудио пустое или повреждено.")
    session = session_for(kim_model(), provider)
    meta = session.get_modelmeta().custom_metadata_map
    mask_graph = session.get_inputs()[0].name == "spec"
    if mask_graph:
        # models-v1.0/manifest.json fixes this geometry and source checkpoint.
        if session.get_inputs()[0].shape != [1, 2050, 801, 2]:
            raise ValueError("Expected the pinned Kim T801 spec/mask contract")
        sr, channels, length, hop, nfft, win_length = 44100, 2, 352800, 441, 2048, 2048
        stems, normalized = ["vocals"], False
    else:
        if meta.get("model_family") != "roformer" or meta.get("architecture") != "mel_band_roformer":
            raise ValueError("Expected a MelBand RoFormer ONNX export")
        sr, channels = int(meta["sample_rate"]), int(meta["audio_channels"])
        length, hop, nfft = int(meta["segment_samples"]), int(meta["stft_hop_length"]), int(meta["stft_n_fft"])
        win_length = int(meta["stft_win_length"])
        stems = json.loads(meta["sources"])[:int(meta["num_stems"])]
        normalized = meta["stft_normalized"] == "true"
    if "vocals" not in stems:
        raise ValueError("Kim export must predict a vocals stem")
    if source_sr != sr:
        factor = gcd(source_sr, sr)
        mix = resample_poly(mix, sr // factor, source_sr // factor, axis=0)
    if mix.shape[1] == 1 and channels == 2:
        mix = np.repeat(mix, 2, axis=1)
    if not len(mix) or mix.shape[1] != channels:
        raise ValueError("Unsupported audio channel count")
    audio = np.ascontiguousarray(mix.T)
    original_length = audio.shape[-1]
    audio, border = pad_context(audio, length)
    result, weights = np.zeros_like(audio), np.zeros(audio.shape[-1], dtype=np.float32)
    dtype = np.float16 if session.get_inputs()[0].type == "tensor(float16)" else np.float32
    for start, count, chunk, ramp in chunks(audio, length):
        spec = forward(chunk, nfft, hop, win_length, normalized)
        if mask_graph:
            pairs = np.stack([spec.real, spec.imag], axis=-1).transpose(1, 0, 2, 3)
            packed = np.ascontiguousarray(pairs.reshape(1, -1, spec.shape[-1], 2).astype(dtype))
            mask = session.run(["mask"], {"spec": packed})[0][0, 0]
            masked = (packed[0, ..., 0] + 1j * packed[0, ..., 1]) * (mask[..., 0] + 1j * mask[..., 1])
            spectrum = masked.reshape(nfft // 2 + 1, channels, -1).transpose(1, 0, 2)
            spectrum[:, 0] = 0
        else:
            real, imag = session.run(["out_spec_real", "out_spec_imag"],
                                     {"spec_real": spec.real[None].astype(dtype),
                                      "spec_imag": spec.imag[None].astype(dtype)})
            index = stems.index("vocals")
            spectrum = real[0, index].astype(np.float32) + 1j * imag[0, index].astype(np.float32)
        vocal = inverse(spectrum, nfft, hop, win_length, length, normalized)[:, :count]
        if not np.isfinite(vocal).all():
            raise ValueError("RoFormer produced non-finite vocals")
        result[:, start:start + count] += vocal * ramp[:count]
        weights[start:start + count] += ramp[:count]
        print(f"Kim ONNX ({provider}): {min(start + count, audio.shape[-1]) / sr:.1f}s", flush=True)
    vocals = (result / np.maximum(weights, 1e-8)).T
    vocals = vocals[border:border + original_length]
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp.wav")
    sf.write(str(temporary), vocals, sr, subtype="FLOAT")
    temporary.replace(target)
