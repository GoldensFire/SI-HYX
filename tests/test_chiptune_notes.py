"""Musical invariants, no models/network required for the regular suite."""
import numpy as np
import pytest

from chiptune.notes import QualityError, pitch_notes, validate_notes
from chiptune.synthesis import SAMPLE_RATE, read_wav, render, validate_audio, write_wav


@pytest.fixture
def melody():
    return [{"start": .1 + index * .6, "end": .6 + index * .6,
             "pitch": pitch, "confidence": .9}
            for index, pitch in enumerate([60, 62, 64, 67, 65, 64, 62, 60])]


def test_pitch_cleaning_preserves_unquantized_timing_and_rejects_short_false_notes():
    midi = np.r_[np.full(43, 60.), np.full(3, 80.), np.full(51, 62.),
                 np.full(34, 64.), np.full(61, 67.), np.full(47, 65.)]
    midi += .2 * np.sin(np.arange(len(midi)) * .4)
    frequencies = 440 * 2 ** ((midi - 69) / 12)
    notes = pitch_notes(frequencies, np.full(len(midi), .9), np.full(len(midi), .1))
    assert [note["pitch"] for note in notes] == [60, 62, 64, 67, 65]
    assert notes[1]["start"] == pytest.approx(.46)
    assert notes[2]["end"] == pytest.approx(1.31)


def test_unvoiced_and_silent_frames_do_not_become_notes():
    assert pitch_notes(np.full(500, 440), np.ones(500), np.zeros(500)) == []
    assert pitch_notes(np.full(500, 440), np.zeros(500), np.ones(500)) == []
    assert pitch_notes([], [], []) == []


def test_vocal_vibrato_keeps_held_notes_and_semitone_steps_without_a_beat_grid():
    # Wide vibrato crosses the rounding boundary; genuine held semitone steps
    # must remain distinct, with their original uneven timings.
    midi = np.r_[np.full(83, 60.), np.full(61, 61.), np.full(47, 64.)]
    midi += .18 + .6 * np.sin(np.arange(len(midi)) * 2 * np.pi * .055)
    result = pitch_notes(440 * 2 ** ((midi - 69) / 12), np.full(len(midi), .9),
                         np.full(len(midi), .1), stabilize=True)
    assert [n["pitch"] for n in result] == [60, 61, 64]
    assert result[0]["end"] == pytest.approx(.83, abs=.10)
    assert result[1]["end"] == pytest.approx(1.44, abs=.06)
    assert sum(n["end"] - n["start"] for n in result) > 1.8


def test_vocal_path_does_not_bridge_a_rest_or_clamp_out_of_range_pitch():
    midi = np.r_[np.full(40, 60.), np.full(25, 60.), np.full(40, 60.), np.full(40, 110.)]
    confidence = np.full(len(midi), .9)
    confidence[40:65] = 0
    result = pitch_notes(440 * 2 ** ((midi - 69) / 12), confidence,
                         np.full(len(midi), .1), stabilize=True)
    assert len(result) == 2
    assert result[0]["end"] == pytest.approx(.4)
    assert result[1]["start"] == pytest.approx(.65)
    assert result[1]["end"] == pytest.approx(1.05)


def test_vocal_inference_bounds_memory_and_preserves_every_border_frame():
    from types import SimpleNamespace
    from chiptune.vocal_pitch import infer_chunks
    sizes = []
    class Session:
        def get_inputs(self):
            return [SimpleNamespace(name="mel")]
        def run(self, outputs, inputs):
            segment = inputs["mel"]
            sizes.append(segment.shape[-1])
            return [segment.transpose(0, 2, 1)]
    mel = np.arange(6010)[None, None, :]
    actual = infer_chunks(Session(), mel)
    assert np.array_equal(actual[:, 0], mel[0, 0])
    assert len(sizes) == 4 and max(sizes) <= 1792


@pytest.mark.parametrize("change", ["few", "overlap", "nan", "sparse", "jumps"])
def test_unmusical_note_sequences_fail(melody, change):
    if change == "few":
        melody = melody[:2]
    elif change == "overlap":
        melody[1]["start"] = .2
    elif change == "nan":
        melody[0]["confidence"] = float("nan")
    elif change == "sparse":
        for note in melody:
            note["end"] = note["start"] + .03
    else:
        for index, note in enumerate(melody):
            note["pitch"] = [30, 80, 45][index % 3]
    with pytest.raises(QualityError):
        validate_notes(melody, 5)


def test_synthesis_pitch_envelopes_duration_and_repeatability(melody, tmp_path):
    options = {"seed": 5, "lead_volume": .85, "bass_volume": .25}
    audio = render(melody, [], 5, options)
    assert np.array_equal(audio, render(melody, [], 5, options))
    metrics = validate_audio(audio, 5)
    assert metrics["peak"] < .9 and metrics["rms"] > .05
    assert len(audio) == SAMPLE_RATE * 5
    for note in melody:
        assert abs(audio[round(note["start"] * SAMPLE_RATE)]) < 1e-6
        assert abs(audio[round(note["end"] * SAMPLE_RATE) - 1]) < 1e-6
    # Fundamental pitch is measured from an independent FFT of a steady note.
    segment = audio[round(.2 * SAMPLE_RATE):round(.5 * SAMPLE_RATE)]
    spectrum = abs(np.fft.rfft(segment * np.hanning(len(segment))))
    frequency = np.fft.rfftfreq(len(segment), 1 / SAMPLE_RATE)[np.argmax(spectrum)]
    assert frequency == pytest.approx(261.63, abs=4)
    path = tmp_path / "chip.wav"
    write_wav(path, audio)
    assert np.max(np.abs(read_wav(path) - audio)) < .00007


def test_bass_volume_is_independent_and_polyphony_is_limited(melody):
    bass = [{**note, "pitch": note["pitch"] - 24} for note in melody]
    options = {"seed": 5, "lead_volume": .5, "bass_volume": 0}
    lead_only = render(melody, bass, 5, options)
    assert np.array_equal(lead_only, render(melody, [], 5, options))
    combined = render(melody, bass, 5, {**options, "bass_volume": .4})
    assert not np.array_equal(lead_only, combined)
    assert np.max(np.abs(combined)) < .9


@pytest.mark.parametrize("audio", [np.zeros(220500), np.ones(220500), np.full(220500, np.nan)])
def test_silence_clipping_and_nan_are_rejected(audio):
    with pytest.raises(QualityError):
        validate_audio(audio, 5)
