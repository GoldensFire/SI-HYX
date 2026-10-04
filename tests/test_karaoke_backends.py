"""Hardware routing, isolated cache identities and recoverable backend failures."""
import json
from pathlib import Path

import pytest

from karaoke import recognition
from karaoke.hardware import select
from karaoke.whisper_cpp import rows_from_json, token_words


@pytest.fixture(autouse=True)
def no_installs(monkeypatch):
    recognition._FAILED_SEPARATORS.clear()
    monkeypatch.setattr(recognition, "ensure_separator", lambda *a, **k: None)
    monkeypatch.setattr(recognition, "ensure_packages", lambda *a, **k: None)
    for variable in ("SI_HYX_KIM_ONNX", "SI_HYX_WHISPER_MODEL"):
        monkeypatch.delenv(variable, raising=False)


@pytest.mark.parametrize("names,cuda,backend,device", [
    (["NVIDIA RTX"], True, "faster-whisper", "cuda"),
    (["AMD Radeon"], False, "whisper.cpp", "vulkan"),
    (["Intel Arc"], False, "whisper.cpp", "vulkan"),
    (["AMD Radeon", "NVIDIA RTX"], True, "faster-whisper", "cuda"),
    ([], False, "faster-whisper", "cpu"),
])
def test_hardware_policy(names, cuda, backend, device):
    result = select(names, cuda)
    assert (result["backend"], result["asr"]) == (backend, device)
    if device == "cpu":
        assert result["compute"] == "int8"


def test_all_asr_execution_inputs_partition_the_cache(tmp_path):
    def target(**changes):
        args = dict(directory=tmp_path, source_sha="sha", backend="faster-whisper", model="medium",
                    language="ja", device="cpu", compute="int8", separator="htdemucs")
        args.update(changes)
        return recognition.asr_target(**args)
    paths = [target(), target(language="en"), target(language=None), target(model="large-v3"),
             target(backend="whisper.cpp"), target(device="cuda"), target(compute="float16"),
             target(separator="kim-onnx")]
    assert len(set(paths)) == len(paths)
    assert target() == paths[0]


def test_kim_failure_reuses_old_vocals_and_vulkan_failure_uses_separate_cpu_cache(tmp_path, monkeypatch):
    old = tmp_path / "asr-medium-ja-demucs-v2" / "sha" / "vocals.wav"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old verified stem")
    calls = []
    def run(command, timeout, **kwargs):
        action = command[5]
        backend = command[command.index("--backend") + 1]
        calls.append((action, backend))
        if action == "separate" or backend == "whisper.cpp":
            return 1, "unsupported GPU operator"
        assert Path(command[6]) == old
        Path(command[7]).write_text("[]", encoding="utf-8")
        return 0, "CPU done"
    monkeypatch.setattr(recognition, "run_process", run)
    info = dict(backend="whisper.cpp", asr="vulkan", compute="float32", separator="directml", demucs="cpu")
    result = recognition.transcribe("python", "source", "sha", tmp_path / "asr-v3", info=info,
                                    language="en", stopped=lambda: False, log=lambda _: None)
    assert calls == [("separate", "kim-onnx"), ("separate", "kim-onnx"),
                     ("transcribe", "whisper.cpp"), ("transcribe", "faster-whisper")]
    meta = json.loads((result.parent / "backend.json").read_text(encoding="utf-8"))
    assert (meta["backend"], meta["language"], meta["device"], meta["separator"]) == (
        "faster-whisper", "en", "cpu", "htdemucs")


def test_two_languages_share_stem_but_keep_distinct_asr(tmp_path, monkeypatch):
    calls = []
    def run(command, timeout, **kwargs):
        calls.append(command[5])
        target = Path(command[7])
        if command[5] == "separate":
            target.write_bytes(b"vocals")
        else:
            target.write_text("[]", encoding="utf-8")
        return 0, "done"
    monkeypatch.setattr(recognition, "run_process", run)
    info = dict(backend="faster-whisper", asr="cpu", compute="int8", separator="cpu", demucs="cpu")
    results = [recognition.transcribe("python", "source", "sha", tmp_path, info=info,
                language=language, stopped=lambda: False, log=lambda _: None) for language in ["ja", "en", "ja"]]
    assert results[0] == results[2] and results[0] != results[1]
    assert calls == ["separate", "transcribe", "transcribe"]


def test_cancellation_does_not_trigger_another_backend(tmp_path, monkeypatch):
    stopped = [False]
    calls = []
    def run(command, timeout, **kwargs):
        calls.append(command[5])
        stopped[0] = True
        return 1, "cancelled"
    monkeypatch.setattr(recognition, "run_process", run)
    info = dict(backend="whisper.cpp", asr="vulkan", compute="float32", separator="directml", demucs="cpu")
    with pytest.raises(RuntimeError, match="остановлено"):
        recognition.transcribe("python", "source", "sha", tmp_path, info=info,
                              stopped=lambda: stopped[0], log=lambda _: None)
    assert calls == ["separate"]


def test_cpp_word_segments_keep_actual_millisecond_offsets():
    rows = rows_from_json({"transcription": [
        {"text": "Hello", "offsets": {"from": 120, "to": 370}},
        {"text": " world", "offsets": {"from": 400, "to": 820}},
        {"text": "untimed", "offsets": {"from": 820, "to": 820}},
    ]})
    assert rows[0]["words"] == [{"start": .12, "end": .37, "word": "Hello"}]
    assert rows[1]["end"] == .82 and len(rows) == 2


def test_kim_out_of_memory_retries_cpu_and_does_not_disable_cpu_for_next_song(tmp_path, monkeypatch):
    calls, messages = [], []
    def run(command, timeout, **kwargs):
        backend = command[command.index("--backend") + 1]
        device = command[command.index("--device") + 1]
        calls.append((backend, device))
        if device == "directml":
            return 1, "Status Message: 8007000E\nUnicodeDecodeError: utf-8 invalid continuation byte"
        Path(command[7]).write_bytes(b"Kim vocals")
        return 0, "CPU done"
    monkeypatch.setattr(recognition, "run_process", run)
    info = {"separator": "directml", "demucs": "cpu"}
    for sha in ("first", "second"):
        result, separator = recognition.vocal_source("python", "source", sha, tmp_path, info,
                                                     stopped=lambda: False, log=messages.append)
        assert result.is_file() and separator.startswith("kim-onnx-")
    assert calls == [("kim-onnx", "directml"), ("kim-onnx", "cpu"), ("kim-onnx", "cpu")]
    assert any("нехватка памяти" in message for message in messages)
    assert not any("HTDemucs" in message for message in messages)


def test_utf16_native_oom_survives_the_python_decoding_error():
    output = "\0".join("Status Message: 8007000E") + "\nUnicodeDecodeError: hidden error"
    assert "нехватка памяти" in recognition.separation_error(output)


def test_cpp_never_invents_timestamps():
    with pytest.raises(ValueError, match="no timed words"):
        rows_from_json({"transcription": [{"text": "hello"}]})


def test_cpp_reassembles_japanese_byte_tokens_with_their_real_times():
    tokens = [{"text": b"\xe4\xb8".decode("utf-8", "surrogateescape"),
               "offsets": {"from": 24000, "to": 24270}},
              {"text": b"\xb8".decode("utf-8", "surrogateescape"),
               "offsets": {"from": 24360, "to": 24490}},
              {"text": "[_TT_600]", "offsets": {"from": 30000, "to": 30000}}]
    assert token_words(tokens) == [{"start": 24.0, "end": 24.49, "word": "丸"}]


def test_cpp_combines_latin_subwords_without_merging_japanese_or_retiming():
    tokens = [{"text": text, "offsets": {"from": i * 100, "to": i * 100 + 80}}
              for i, text in enumerate(["君", "We", " will", " sing", "ing"])]
    assert token_words(tokens) == [{"start": 0, "end": .08, "word": "君"},
                                  {"start": .1, "end": .18, "word": "We"},
                                  {"start": .2, "end": .28, "word": " will"},
                                  {"start": .3, "end": .48, "word": " singing"}]
