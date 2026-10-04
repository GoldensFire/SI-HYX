"""Original-language selection and the 80% gate for a second bilingual pass."""
import json
from pathlib import Path
from types import SimpleNamespace
from contextlib import nullcontext

import numpy as np
import pytest

from karaoke import fallback
from karaoke.languages import rank
from karaoke.rejections import SourceRejected
from karaoke.stft import forward, inverse


def test_original_japanese_is_primary_and_english_is_secondary():
    original = ["君と歩くこの世界で未来を信じて歌う", "君と歩くこの世界で未来を信じて歌う",
                "We will be together forever"]
    assert rank(original, lambda text: ("en", 1.0)) == ["ja", "en"]


@pytest.mark.parametrize("original,expected", [
    (["We will be together forever"], ["en"]),
    (["한글노래를부르는우리들의꿈"], ["ko"]),
    (["未来属于我们永远一起唱歌"], ["zh"]),
    (["Nous chantons ensemble pour toujours"], ["fr"]),
    (["Мы поём эту песню вместе"], ["ru"]),
])
def test_other_whisper_languages(original, expected):
    assert rank(original, lambda text: (expected[0], 1.0)) == expected


def test_unsupported_language_uses_whisper_auto():
    assert rank(["Some unknown language"], lambda text: ("xx", 1.0)) == [None]


@pytest.mark.parametrize("first_count,expected_calls", [(5, ["ja"]), (4, ["ja"]), (3, ["ja", "en"])])
def test_second_pass_only_below_eighty_percent(tmp_path, monkeypatch, first_count, expected_calls):
    original = ["春の夢", "夜の星", "君の声", "Our bright future", "We sing together"]
    calls = []
    def transcribe(*args, language, **kwargs):
        calls.append(language)
        indices = range(first_count) if language == "ja" else range(3, 5)
        rows = [{"words": [{"word": original[index], "start": index * 2, "end": index * 2 + 1}]}
                for index in indices]
        target = tmp_path / (language + ".json")
        target.write_text(json.dumps(rows), encoding="utf-8")
        return target
    monkeypatch.setattr(fallback, "transcribe", transcribe)
    rows = fallback.acoustic_phrases("python", "source", "sha", original, ["ja", "en"], tmp_path,
                                    stopped=lambda: False, log=lambda _: None, info={})
    assert calls == expected_calls and len(rows) >= 4
    assert all("line_index" not in row for row in rows)


def test_both_passes_below_gate_still_reject(tmp_path, monkeypatch):
    target = tmp_path / "segments.json"
    target.write_text("[]", encoding="utf-8")
    calls = []
    def transcribe(*args, **kwargs):
        calls.append(kwargs["language"])
        return target
    monkeypatch.setattr(fallback, "transcribe", transcribe)
    with pytest.raises(SourceRejected, match="80%"):
        fallback.acoustic_phrases("python", "source", "sha", ["君の声", "Our bright future"],
                                 ["ja", "en"], tmp_path, stopped=lambda: False, log=lambda _: None, info={})
    assert calls == ["ja", "en"]


def test_aligner_language_input_never_reads_romaji(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.write_bytes(b"audio")
    original, seen = ["Our bright future"], []
    monkeypatch.setattr(fallback, "ensure_runtime", lambda *a: "python")
    monkeypatch.setattr(fallback, "model_slot", lambda *a: nullcontext())
    def languages(python, lyrics, work, **kwargs):
        seen.extend(lyrics)
        return ["en"]
    monkeypatch.setattr(fallback, "lyric_languages", languages)
    monkeypatch.setattr(fallback, "device_info", lambda *a: {})
    target = tmp_path / "asr.json"
    target.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(fallback, "transcribe", lambda *a, **k: target)
    with pytest.raises(SourceRejected):
        fallback.align(source, SimpleNamespace(original=original, romaji=["kimi no koe"]),
                       SimpleNamespace(), cache=tmp_path / "cache", stopped=lambda: False, log=lambda _: None)
    assert seen == original


@pytest.mark.parametrize("normalized", [False, True])
def test_kim_stft_contract_round_trips_short_and_non_aligned_audio(normalized):
    audio = np.random.default_rng(7).normal(size=(2, 13231)).astype(np.float32)
    spectrum = forward(audio, 2048, 441, 2048, normalized)
    restored = inverse(spectrum, 2048, 441, 2048, audio.shape[-1], normalized)
    assert restored.shape == audio.shape
    np.testing.assert_allclose(restored, audio, atol=1e-6)
