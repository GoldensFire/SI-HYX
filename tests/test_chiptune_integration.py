"""Settings, quota retries, public API and real WAV/MP3 inside a SIQ archive."""
import json
from pathlib import Path
import shutil
import sys
import zipfile

import numpy as np
import pytest

import animepack as ap
from chiptune.notes import QualityError
from chiptune.runtime import run_process
from chiptune.service import ChiptuneService, MODEL_GATE
from chiptune.synthesis import read_wav, render, write_wav
from music_effects import EffectSlots, processing_options


@pytest.fixture(autouse=True)
def isolated_model_lock(tmp_path, monkeypatch):
    # Unit tests never lock the user's running music worker.
    monkeypatch.setattr("chiptune.gate.lock_file", lambda: tmp_path / "model.lock")


def settings(**kwargs):
    return ap.PackSettings(chiptune_enabled=True, chiptune_python=sys.executable,
                           audio_cut=5, rounds=1, themes=1, questions=1, **kwargs)


def candidate():
    return ap.SongCandidate(song={"audio": "source.mp3", "annSongId": 7, "songType": 1},
                            anime={"malId": 1, "name": "Test"}, kind="opening", music_effect="chiptune")


def notes():
    return [{"start": .1 + i * .6, "end": .6 + i * .6, "pitch": pitch, "confidence": .95}
            for i, pitch in enumerate([60, 62, 64, 67, 65, 64, 62, 60])]


def test_settings_roundtrip_and_old_defaults():
    original = settings(chiptune_percent=40, chiptune_seed=781, chiptune_bass_volume=0)
    restored = ap.PackSettings.from_dict(original.to_dict())
    assert processing_options(restored) == processing_options(original)
    assert restored.chiptune_percent == 40
    assert not ap.PackSettings.from_dict({}).chiptune_enabled
    assert ap.PackSettings.from_dict({"chiptune_version": "chiptune-1"}).chiptune_version == "chiptune-2"
    restored.chiptune_version = "future-version"
    assert any("версия" in error for error in restored.validate())


def test_existing_positional_candidate_api():
    cand = ap.SongCandidate({}, {}, [], "ending", 3, True)
    assert cand.has_poster
    assert cand.music_effect == "original"
    assert cand.base_kind == "ending"


def test_missing_runtime_fails_before_any_download(tmp_path):
    current = settings()
    current.chiptune_python = str(tmp_path / "absent.exe")
    generator = ap.AnimePackGenerator(current)
    with pytest.raises(ap.AnimePackError, match="обработчик"):
        generator.run()


def test_worker_staging_excludes_bundled_dependencies_and_cleans_up(tmp_path):
    from chiptune.launcher import isolated_command
    bundle = tmp_path / "_internal"
    package = bundle / "chiptune"
    package.mkdir(parents=True)
    (package / "worker.py").write_text("print('worker')", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (bundle / "numpy").mkdir()
    (bundle / "numpy/incompatible.pyd").write_bytes(b"Python 3.14 library")
    with isolated_command(sys.executable, package / "worker.py") as command:
        staged = Path(command[2]).parent
        assert command[1] == "-I"
        assert (staged / "worker.py").is_file()
        assert not (staged.parent / "numpy").exists()
        assert staged.parent != bundle
    assert not staged.exists()


def test_slots_retry_without_losing_effect_and_expand():
    current = settings(chiptune_percent=40, chiptune_seed=12)
    slots = EffectSlots(current, 10)
    accepted = []
    first = candidate()
    slots.reserve(first)
    failed_effect = first.music_effect
    slots.release(first)
    retry = candidate()
    slots.reserve(retry)
    assert retry.music_effect == failed_effect
    accepted.append(retry.music_effect)
    slots.expand(current, 15)
    while slots.free:
        cand = candidate()
        slots.reserve(cand)
        accepted.append(cand.music_effect)
    assert accepted.count("chiptune") == 6


def test_failure_limit_is_explicit():
    slots = EffectSlots(settings(chiptune_percent=100), 1)
    for _ in range(11):
        cand = candidate()
        slots.reserve(cand)
        slots.release(cand)
    slots.reserve(cand)
    with pytest.raises(RuntimeError, match="неудачных"):
        slots.release(cand)


@pytest.mark.parametrize("compress", [True, False])
def test_real_audio_packaging_never_copies_original(tmp_path, monkeypatch, compress):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg unavailable")
    monkeypatch.setattr(ap, "FFMPEG", ffmpeg)
    current = settings(compress_audio=compress)
    generator = ap.AnimePackGenerator(current)
    generator.folder = str(tmp_path)
    (tmp_path / "Audio").mkdir()
    cand = candidate()
    cand.compress_audio = compress
    generator._get_bytes = lambda url: b"ORIGINAL_STREAM_MUST_NOT_BE_COPIED" * 2000
    class FakeTranscription:
        def convert(self, source, target, start, duration):
            audio = render(notes(), [], 5, processing_options(current))
            write_wav(target, audio)
            return {"notes": notes(), "selected_lead": "vocals", "note_metrics": {"notes": 8}}
    generator._music_service = FakeTranscription()
    assert generator.download_audio(cand)
    assert cand.base_kind == "opening" and cand.kind == "opening"
    assert cand.audio_out.endswith(".mp3" if compress else ".wav")
    packed = generator.write_package([cand], str(tmp_path / "test.siq"))
    with zipfile.ZipFile(packed) as archive:
        xml = archive.read("content.xml").decode("utf-8")
        assert cand.audio_out in xml and "Chiptune" in xml
        assert b"ORIGINAL_STREAM" not in archive.read("Audio/" + cand.audio_out)
        manifest = json.loads(archive.read("chiptune.json"))
        assert manifest["questions"][0]["source_kind"] == "opening"
    assert not list(tmp_path.glob("chip-*"))


def test_rejected_transcription_has_no_original_fallback(tmp_path):
    generator = ap.AnimePackGenerator(settings())
    generator.folder = str(tmp_path)
    (tmp_path / "Audio").mkdir()
    generator._get_bytes = lambda url: b"original" * 20000
    class Failure:
        def convert(self, *args):
            raise QualityError("Ненадёжная мелодия")
    generator._music_service = Failure()
    cand = candidate()
    assert not generator.download_audio(cand)
    assert list((tmp_path / "Audio").iterdir()) == []
    assert not list(tmp_path.glob("chip-*"))


def test_cancel_waiting_for_model_does_not_launch_process(tmp_path):
    service = ChiptuneService(settings(), lambda *a, **kw: pytest.fail("launched"), "ffmpeg",
                              cache=tmp_path, stopped=lambda: True)
    MODEL_GATE.acquire()
    try:
        with pytest.raises(QualityError, match="остановлено"):
            service.convert("source", "target", 0, 5)
    finally:
        MODEL_GATE.release()


def test_cached_notes_reused_but_source_crop_model_and_settings_invalidate(tmp_path):
    calls = []
    current = settings()
    def fake_run(command, timeout):
        calls.append(command)
        if "--target" in command:
            target = Path(command[command.index("--target") + 1])
            if "probe" in command:
                target.write_text('{"fingerprint":"model-A"}', encoding="utf-8")
            elif "separate" in command:
                np.savez(target, vocals=np.zeros(50))
            else:
                target.write_text(json.dumps({"notes": notes(), "bass": [], "lead": "vocals",
                                               "duration": 5, "metrics": {"notes": 8}}), encoding="utf-8")
        else:
            Path(command[-1]).write_bytes(b"pcm")
        return 0, ""
    source, target = tmp_path / "source", tmp_path / "target.wav"
    source.write_bytes(b"original-A")
    service = ChiptuneService(current, fake_run, "ffmpeg", cache=tmp_path / "cache")
    first = service.convert(source, target, 0, 5)
    initial_calls = len(calls)
    assert service.convert(source, target, 0, 5)["cache_key"] == first["cache_key"]
    assert len(calls) == initial_calls
    current.chiptune_lead_volume = 60
    assert service.convert(source, target, 0, 5)["cache_key"] != first["cache_key"]
    assert len(calls) == initial_calls  # synth settings don't repeat ML inference
    service.convert(source, target, 1, 5)
    assert len(calls) > initial_calls
    previous = len(calls)
    source.write_bytes(b"original-B")
    service.convert(source, target, 0, 5)
    assert len(calls) > previous
    previous = len(calls)
    service.identity = {"fingerprint": "model-B"}
    service.convert(source, target, 0, 5)
    assert len(calls) > previous
    service.identity = {"separation": "demucs", "transcription": "tracker-A"}
    service.convert(source, target, 0, 5)
    previous = len(calls)
    service.identity["transcription"] = "tracker-B"
    service.convert(source, target, 0, 5)
    assert len(calls) == previous + 1
    assert "transcribe" in calls[-1]  # different pitch model reuses the same stems
    assert not list((tmp_path / "cache").glob("job-*"))
    assert len(read_wav(target)) == 5 * 44100


def test_cancel_running_worker():
    import time
    started = time.monotonic()
    code, message = run_process([sys.executable, "-c", "import time; time.sleep(30)"],
                                stopped=lambda: time.monotonic() - started > .3)
    assert code != 0 and "Остановлено" in message
    assert time.monotonic() - started < 10


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process-tree cancellation")
def test_cancel_also_stops_child_interpreter(tmp_path):
    import time
    marker = tmp_path / "child-survived"
    child_code = ("import time; from pathlib import Path; time.sleep(2); "
                  f"Path({str(marker)!r}).write_bytes(b'alive')")
    parent_code = ("import subprocess,sys,time; "
                   f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); time.sleep(30)")
    started = time.monotonic()
    code, _ = run_process([sys.executable, "-c", parent_code],
                          stopped=lambda: time.monotonic() - started > .5)
    assert code != 0
    time.sleep(2.2)
    assert not marker.exists()
