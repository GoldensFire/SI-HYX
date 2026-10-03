"""Regression coverage for syllable boundaries, source offsets and quality settings."""
import pytest
import animepack as ap
from karaoke.ass import write_ass
from karaoke.crop import aligned_start, word_starts
from karaoke.model import Line, Unit
from karaoke.layout import positions


def lyric():
    return [Line(1, 5, [Unit(1.5, 2.5, "ki"), Unit(2.5, 4, "mi "),
                        Unit(4, 5, "wa")])]


def test_crop_never_selects_a_syllable_in_the_middle_of_a_word():
    assert word_starts(lyric()) == [1.5, 4]
    assert aligned_start(lyric(), 2.5, 5, 20) == 1.5
    assert aligned_start(lyric(), 3, 5, 20) == 4
    assert aligned_start(lyric(), 2.75, 5, 20) == 1.5


def test_alignment_uses_recording_offset_and_keeps_room_for_full_clip():
    assert aligned_start(lyric(), 4, 5, 8, offset=.25) == 1.75
    assert aligned_start(lyric(), 0, 5, 20, offset=-2) == 2
    with pytest.raises(ValueError, match="целого слова"):
        aligned_start(lyric(), 0, 5, 1)


def test_untimed_whitespace_and_first_word_after_instrumental_intro():
    lines = [Line(10, 15, [Unit(10, 11, " "), Unit(11, 12, "he"),
                          Unit(12, 13, "llo"), Unit(13, 13.5, " "),
                          Unit(13.5, 15, "world")])]
    assert word_starts(lines) == [11, 13.5]
    assert aligned_start(lines, 0, 5, 20) == 11


def test_single_lyric_line_is_at_frame_center():
    assert r"\pos(640,360)" in write_ass(lyric())


def test_next_phrase_preview_waits_for_previous_phrase_without_changing_sung_timing():
    lines = [Line(0, 3, [Unit(0, 3, "one")]),
             Line(2.5, 5, [Unit(3.4, 5, "two")])]
    layout = positions(lines, 720, 40)
    assert layout[0] == (0, 360, 360)
    assert layout[1] == (3, 360, 360)
    assert r"{\kf40}{\kf160}two" in write_ass(lines)


def test_actually_overlapping_voices_get_separate_centered_rows():
    lines = [Line(0, 3, [Unit(0, 3, "one")]),
             Line(2, 5, [Unit(2, 5, "two")])]
    layout = positions(lines, 720, 40)
    assert layout[0][1] == 328 and layout[1][1] == 392


def test_quality_settings_persist_and_legacy_settings_keep_previous_quality():
    settings = ap.PackSettings(karaoke_crf=30, karaoke_preset=11)
    restored = ap.PackSettings.from_dict(settings.to_dict())
    assert (restored.karaoke_crf, restored.karaoke_preset) == (30, 11)
    legacy = ap.PackSettings.from_dict({"video_crf": 41, "video_preset": 9})
    assert (legacy.karaoke_crf, legacy.karaoke_preset) == (41, 9)


@pytest.mark.parametrize("field,value", [("karaoke_crf", -1), ("karaoke_crf", 64),
                                        ("karaoke_preset", -1), ("karaoke_preset", 14)])
def test_invalid_karaoke_encoding_settings_are_rejected(field, value):
    settings = ap.PackSettings(karaoke_enabled=True)
    setattr(settings, field, value)
    assert any("Караоке:" in error for error in settings.validate())
