"""Compressed AMQ containers use FFmpeg before loading an expensive model."""
from pathlib import Path
import subprocess

import numpy as np
import pytest
import soundfile as sf

from config import FFMPEG
from karaoke import input_audio, roformer


def test_aac_under_generic_audio_name_decodes_with_sample_rate_and_stereo(tmp_path):
    source = tmp_path / "source.audio"
    subprocess.run([FFMPEG, "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=0.2", "-ac", "2", "-ar", "48000",
                    "-c:a", "aac", "-f", "mp4", str(source)], check=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    with pytest.raises(sf.LibsndfileError):
        sf.read(source)
    audio, rate = input_audio.read(source, FFMPEG)
    assert rate == 48000 and audio.shape[1] == 2
    assert len(audio) >= 9600 and np.isfinite(audio).all()
    assert np.max(np.abs(audio)) > 0.01


def test_failed_container_decode_reports_ffmpeg_error_and_removes_temporary(monkeypatch, tmp_path):
    source = tmp_path / "source.audio"
    source.write_bytes(b"not audio")
    outputs = []

    def run(command, **kwargs):
        outputs.append(Path(command[-1]))
        return subprocess.CompletedProcess(command, 1, stderr=b"Invalid input")

    monkeypatch.setattr(input_audio.subprocess, "run", run)
    with pytest.raises(ValueError, match="Invalid input"):
        input_audio.read(source, "bundled ffmpeg.exe")
    assert len(outputs) == 1 and not outputs[0].parent.exists()


@pytest.mark.parametrize("audio", [np.empty((0, 2)), np.full((5, 2), np.nan)])
def test_invalid_audio_never_loads_onnx_model(monkeypatch, tmp_path, audio):
    monkeypatch.setattr(input_audio, "read", lambda *args: (audio, 44100))

    def unexpected(*args):
        raise AssertionError("Invalid audio must not allocate the separator model")

    monkeypatch.setattr(roformer, "session_for", unexpected)
    with pytest.raises(ValueError, match="пустое или повреждено"):
        roformer.separate(tmp_path / "bad.audio", tmp_path / "vocals.wav", "cpu")
