"""GPU fallback, persistent vocals and punctuation-free lyric coverage."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from karaoke import recognition
from karaoke.lyrics import Sheet, clean_lines, parse_html, text_lines


@pytest.fixture(autouse=True)
def no_runtime_install(monkeypatch):
    recognition._FAILED_SEPARATORS.clear()
    monkeypatch.setattr(recognition, "ensure_packages", lambda *a, **k: None)
    monkeypatch.setattr(recognition, "ensure_separator", lambda *a, **k: None)


def test_html_expanders_and_music_separators_are_not_sung_lines():
    content = '<div>君は<br>+<br>世界<br>♪<br>...<br>2人で<br><button>Expand</button></div>'
    assert text_lines(parse_html(content.encode()), short=True) == ["君は", "世界", "2人で"]
    assert clean_lines(["+", "♪", "  kimi wa  ", "..."]) == ["kimi wa"]


def test_punctuation_only_lyrics_fail_before_loading_models(tmp_path, monkeypatch):
    from karaoke import fallback
    def unexpected(*args, **kwargs):
        raise AssertionError("Empty lyric sheet must not start a model")
    monkeypatch.setattr(fallback, "ensure_runtime", unexpected)
    with pytest.raises(ValueError, match="проверенный оригинальный текст"):
        fallback.align(tmp_path / "missing.audio", Sheet("Song", "Singer", "site", ["+", "♪"], []),
                       SimpleNamespace(), stopped=lambda: False, log=lambda _: None)


def test_failed_asr_keeps_vocals_and_retry_skips_demucs(tmp_path, monkeypatch):
    calls = []
    fail = [True]
    def run(command, timeout, **kwargs):
        action = command[5]
        calls.append(action)
        if action == "devices":
            return 0, json.dumps({"asr": "cpu", "compute": "int8", "demucs": "cpu"})
        if action == "separate":
            Path(command[7]).write_bytes(b"cached vocal")
            return 0, "separated"
        if fail[0]:
            return 1, "temporary ASR failure"
        Path(command[7]).write_text("[]", encoding="utf-8")
        return 0, "done"
    monkeypatch.setattr(recognition, "run_process", run)
    with pytest.raises(ValueError, match="Whisper"):
        recognition.transcribe("python", "source.audio", "sha", tmp_path, stopped=lambda: False, log=lambda _: None)
    fail[0] = False
    target = recognition.transcribe("python", "source.audio", "sha", tmp_path,
                                    stopped=lambda: False, log=lambda _: None)
    assert target.is_file() and calls.count("separate") == 1
    before = len(calls)
    recognition.transcribe("python", "source.audio", "sha", tmp_path, stopped=lambda: False, log=lambda _: None)
    assert calls[before:] == ["devices"]


def test_missing_cuda_libraries_retry_asr_on_cpu_without_reseparation(tmp_path, monkeypatch):
    calls = []
    def run(command, timeout, **kwargs):
        action = command[5]
        if action == "devices":
            return 0, json.dumps({"asr": "cuda", "compute": "float16", "demucs": "cpu"})
        if action == "separate":
            Path(command[7]).write_bytes(b"vocals")
            calls.append("separate")
            return 0, "done"
        device = command[command.index("--device") + 1]
        calls.append(device)
        if device == "cuda":
            return 1, "missing cuDNN"
        Path(command[7]).write_text("[]", encoding="utf-8")
        return 0, "done"
    monkeypatch.setattr(recognition, "run_process", run)
    recognition.transcribe("python", "source.audio", "sha", tmp_path, stopped=lambda: False, log=lambda _: None)
    assert calls == ["separate", "cuda", "cpu"]
