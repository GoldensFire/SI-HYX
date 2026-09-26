"""Missing musical phrases must not hide behind good global coverage."""
import json

import numpy as np
import pytest

from chiptune.melody_quality import melody_diagnostics, validate_melody_coverage
from chiptune.notes import QualityError


def events(*intervals):
    # Deliberately no pitch-model confidence: only timing explains activity.
    return [{"start": start, "end": end} for start, end in intervals]


def test_loud_missing_second_half_fails_despite_good_first_half():
    rms = np.full(800, .08)
    notes = events((0, 4.5))
    result = melody_diagnostics(notes, rms)
    assert result["active_note_coverage"] > .5
    assert result["worst_window_coverage"] == 0
    assert result["missing_phrases"]
    with pytest.raises(QualityError, match="пропущена звучащая фраза"):
        validate_melody_coverage(notes, rms)


def test_trailing_phrase_is_checked_when_duration_is_not_a_window_multiple():
    rms = np.full(713, .08)
    result = melody_diagnostics(events((0, 5.63)), rms)
    last = result["missing_phrases"][-1]
    assert last["end"] == pytest.approx(7.13)
    assert last["coverage"] == 0


def test_quiet_intro_breath_and_tail_are_allowed():
    rms = np.full(1200, .0004)
    rms[203:477] = .06
    rms[618:947] = .08
    notes = events((2.03, 4.77), (6.18, 9.47))
    result = validate_melody_coverage(notes, rms)
    assert result["active_note_coverage"] == 1
    assert result["missing_phrases"] == []
    json.dumps(result, allow_nan=False)


def test_short_unvoiced_syllables_and_sparse_real_rhythm_are_not_missing_phrases():
    rms = np.full(600, .015)
    # Phrase energy may continue through consonants and brief reverb tails.
    notes = events(*[(index * .4 + .031, index * .4 + .211) for index in range(15)])
    result = validate_melody_coverage(notes, rms)
    assert .4 < result["active_note_coverage"] < .5


def test_isolated_loud_noise_does_not_establish_a_sung_phrase():
    rms = np.full(600, .0001)
    rms[280:294] = .8
    result = validate_melody_coverage([], rms)
    assert result["checked_windows"] == 0
    assert result["missing_phrases"] == []


@pytest.mark.parametrize("hop", [.005, .01, .02])
def test_window_decision_and_timing_follow_configured_frame_hop(hop):
    rms = np.full(round(6 / hop), .06)
    result = melody_diagnostics(events((0, 4.4)), rms, hop=hop)
    assert result["active_seconds"] == pytest.approx(6)
    assert result["missing_phrases"][-1]["end"] == pytest.approx(6)
    with pytest.raises(QualityError):
        validate_melody_coverage(events((0, 4.4)), rms, hop=hop)


def test_gain_changes_preserve_activity_when_above_the_absolute_noise_floor():
    rms = np.r_[np.full(200, .0001), np.full(400, .1)]
    notes = events((2, 4.5))
    louder = melody_diagnostics(notes, rms)
    quieter = melody_diagnostics(notes, rms * .25)
    assert louder["missing_phrases"] == quieter["missing_phrases"]
    assert louder["active_note_coverage"] == quieter["active_note_coverage"]


def test_silent_stem_is_left_to_the_global_note_and_audio_checks():
    result = validate_melody_coverage([], np.zeros(500))
    assert result["active_seconds"] == 0
    assert result["checked_windows"] == 0


@pytest.mark.parametrize("rms", [[], [[.1]], [.1, np.nan], [.1, np.inf], [-.1]])
def test_invalid_energy_data_is_rejected(rms):
    with pytest.raises(QualityError, match="громкости"):
        melody_diagnostics([], rms)


@pytest.mark.parametrize("parameters", [{"hop": 0}, {"step": 2},
                                      {"minimum_active": 2}, {"minimum_coverage": 1}])
def test_invalid_window_configuration_is_rejected(parameters):
    with pytest.raises(ValueError):
        melody_diagnostics([], [.1] * 100, **parameters)


def test_timing_outside_the_analyzed_stem_is_rejected():
    with pytest.raises(QualityError, match="границы нот"):
        melody_diagnostics(events((0, 6)), [.1] * 500)
