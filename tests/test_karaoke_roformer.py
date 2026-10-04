"""The spec/mask port keeps stereo channels and the original recording duration."""
from types import SimpleNamespace

import numpy as np
import soundfile as sf

from karaoke import roformer, ai_assets


def test_identity_complex_mask_preserves_stereo_and_chunk_edges(tmp_path, monkeypatch):
    sr, size = 44100, 44100 * 9 + 123
    time = np.arange(size) / sr
    mix = np.stack([.1 * np.sin(2 * np.pi * (sr / 128) * time),
                    .2 * np.sin(2 * np.pi * (sr / 64) * time)], axis=-1).astype(np.float32)
    source, target = tmp_path / "mix.wav", tmp_path / "vocals.wav"
    sf.write(source, mix, sr, subtype="FLOAT")
    calls = []
    class Session:
        def get_modelmeta(self):
            return SimpleNamespace(custom_metadata_map={})
        def get_inputs(self):
            return [SimpleNamespace(name="spec", shape=[1, 2050, 801, 2], type="tensor(float)")]
        def run(self, outputs, inputs):
            calls.append(inputs["spec"].shape)
            mask = np.zeros((1, 1, 2050, 801, 2), dtype=np.float32)
            mask[..., 0] = 1
            return [mask]
    monkeypatch.setattr(ai_assets, "kim_model", lambda: tmp_path / "model.onnx")
    monkeypatch.setattr(roformer, "session_for", lambda *a: Session())
    roformer.separate(source, target, "directml")
    vocals, rate = sf.read(target, dtype="float32", always_2d=True)
    assert rate == sr and vocals.shape == mix.shape
    assert calls and all(shape == (1, 2050, 801, 2) for shape in calls)
    # Zeroing DC changes a small amount of reflected chunk-edge energy.
    np.testing.assert_allclose(vocals[2048:-2048], mix[2048:-2048], atol=3e-5)
