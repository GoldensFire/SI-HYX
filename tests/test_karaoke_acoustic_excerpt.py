"""A partial transcript is usable only as a continuous confirmed twenty-second clip."""
import json

import pytest

from karaoke.acoustic_excerpt import select
from karaoke.fallback import acoustic_phrases
from karaoke.rejections import SourceRejected


def row(index, start, end):
    return {"line_index": index, "start": start, "end": end}


def test_excerpt_cannot_bridge_missing_lines_or_long_audio_gaps():
    assert not select([row(0, 0, 10), row(2, 10, 20), row(3, 20, 30)], 20)
    assert not select([row(0, 0, 10), row(1, 15, 25), row(2, 25, 35)], 20)
    assert not select([row(0, 0, 8), row(1, 8, 16), row(2, 16, 20)], 20)


def test_excerpt_keeps_only_a_complete_long_confirmed_verse():
    rows = [row(0, 0, 8), row(2, 20, 28), row(3, 28, 36), row(4, 36, 44)]
    assert select(rows, 20) == rows[1:]


def test_partial_recording_requires_twenty_continuous_seconds(tmp_path, monkeypatch):
    import karaoke.fallback as module
    original = ["first known phrase", "second known verse", "third known chorus",
                "unrecorded fourth passage", "unrecorded fifth passage"]
    segments = [{"words": [{"word": original[i], "start": i * 8, "end": (i + 1) * 8}]}
                for i in range(3)]
    target = tmp_path / "asr.json"
    target.write_text(json.dumps(segments), encoding="utf-8")
    monkeypatch.setattr(module, "transcribe", lambda *a, **k: target)
    options = dict(stopped=lambda: False, log=lambda _: None, info={})
    with pytest.raises(SourceRejected, match="80%"):
        acoustic_phrases("python", "source", "sha", original, ["en"], tmp_path, **options)
    details = {}
    rows = acoustic_phrases("python", "source", "sha", original, ["en"], tmp_path,
                            excerpt_duration=20, details=details, **options)
    assert len(rows) == 3 and details["confirmed_excerpt"] == [0, 24]
    assert details["full_lyrics_coverage"] == .6
    assert details["selected_lyric_indices"] == [0, 1, 2]
