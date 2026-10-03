"""Recording identity must reject covers, TV/full edits and temporal drift."""
import numpy as np
import pytest

from karaoke.matching import metadata_matches, verify_audio
from karaoke.model import Track
import cover_audio


@pytest.fixture
def recording():
    # Changing partials give fingerprints independent of a fixed repeated tone.
    random = np.random.default_rng(27)
    rate = cover_audio.SR
    parts = []
    t = np.arange(rate // 2) / rate
    for _ in range(80):
        frequency = random.uniform(240, 1200)
        part = sum(np.sin(2 * np.pi * frequency * n * t + random.uniform(0, 6)) / n
                   for n in range(1, 5))
        parts.append(part * np.hanning(len(t)))
    return np.concatenate(parts).astype(np.float32) * .2


def test_recording_with_constant_encoder_delay_matches_three_anchors(recording):
    delay = round(.3 * cover_audio.SR)
    source = np.r_[np.zeros(delay, dtype=np.float32), recording[:-delay]]
    result = verify_audio(source, recording)
    assert len(result["anchors"]) == 3
    assert result["offset"] == pytest.approx(.3, abs=.05)
    assert all(a["pairs_per_second"] >= 1.5 for a in result["anchors"])


def test_different_recording_is_rejected_even_at_same_duration(recording):
    with pytest.raises(ValueError, match="Аудиоотпечаток"):
        verify_audio(np.random.default_rng(42).normal(0, .1, len(recording)).astype(np.float32), recording)


def test_full_version_cannot_supply_tv_timings(recording):
    with pytest.raises(ValueError, match="TV/full"):
        verify_audio(recording, np.tile(recording, 2))


def test_cut_and_paste_edit_is_rejected(recording):
    edited = recording.copy()
    middle = len(edited) // 2
    edited[middle:middle + cover_audio.SR * 10] = recording[:cover_audio.SR * 10]
    with pytest.raises(ValueError):
        verify_audio(edited, recording)


def test_metadata_rejects_wrong_artist_length_and_cover():
    track = Track("Gurenge", ["LiSA"], 91, "KM", "ass", "audio")
    assert metadata_matches("Gurenge", "LiSA", 90, track)
    assert not metadata_matches("Gurenge", "Other singer", 90, track)
    assert not metadata_matches("Gurenge", "LiSA", 240, track)
    assert not metadata_matches("Other song", "LiSA", 90, track)
    track.version = "English cover"
    assert not metadata_matches("Gurenge", "LiSA", 90, track)
