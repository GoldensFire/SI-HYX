"""A selected or locally disabled separator cannot be bypassed by cached Kim."""
import json

from karaoke import recognition, separator_health


def test_local_optout_survives_runs_and_is_scoped_to_hardware(tmp_path, monkeypatch):
    monkeypatch.setattr(separator_health, "STATUS", tmp_path / "health.json")
    monkeypatch.setattr(separator_health, "gpu_names", lambda: ["AMD"])
    assert not separator_health.kim_disabled()
    separator_health.disable_kim("DirectML and CPU allocation failures")
    assert separator_health.kim_disabled()
    monkeypatch.setattr(separator_health, "gpu_names", lambda: ["NVIDIA"])
    assert not separator_health.kim_disabled()


def test_explicit_demucs_does_not_reuse_cached_kim_stem(tmp_path, monkeypatch):
    from karaoke.ai_assets import KIM_SHA

    kim = tmp_path / "vocals" / ("kim-onnx-" + KIM_SHA[:16]) / "sha" / "vocals.wav"
    demucs = tmp_path / "vocals/htdemucs/sha/vocals.wav"
    for path in (kim, demucs):
        path.parent.mkdir(parents=True)
        path.write_bytes(b"cached stem")
    monkeypatch.setattr(recognition, "kim_disabled", lambda: False)
    monkeypatch.setattr(recognition, "ensure_separator", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("Kim must not be prepared")))
    path, name = recognition.vocal_source("python", "source", "sha", tmp_path,
        {"separator_policy": "htdemucs", "separator": "directml", "demucs": "cpu"},
        stopped=lambda: False, log=lambda _: None)
    assert path == demucs and name == "htdemucs"


def test_disabled_kim_is_skipped_in_asr_cache_lookup(tmp_path, monkeypatch):
    from karaoke.ai_assets import KIM_SHA

    monkeypatch.setattr(recognition, "kim_disabled", lambda: True)
    common = dict(directory=tmp_path, source_sha="sha", backend="faster-whisper",
                  model="medium", language="ja", device="cpu", compute="int8")
    kim = recognition.asr_target(**common, separator="kim-onnx-" + KIM_SHA[:16])
    demucs = recognition.asr_target(**common, separator="htdemucs")
    kim.write_text(json.dumps([{"text": "Kim"}]), encoding="utf-8")
    demucs.write_text(json.dumps([{"text": "Demucs"}]), encoding="utf-8")
    info = dict(backend="faster-whisper", asr="cpu", compute="int8", separator="directml",
                demucs="cpu", separator_policy="auto")
    target = recognition.transcribe("python", "source", "sha", tmp_path,
        info=info, language="ja", stopped=lambda: False, log=lambda _: None)
    assert target == demucs
