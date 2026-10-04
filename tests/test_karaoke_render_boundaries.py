"""Actual libass frames preserve the sung clock at the clip's right edge."""
from pathlib import Path
import re
import shutil
import subprocess

import pytest
import animepack as ap
from karaoke.ass import read_ass, write_ass
from karaoke.model import Line, Unit
from karaoke.render import ass_filter
from karaoke.style import font_size
from karaoke.timeline import transform


def test_future_words_keep_their_clock_and_the_partial_syllable_does_not_accelerate():
    source = [Line(10, 20, [Unit(10, 12, "past "), Unit(12, 17, "singing "), Unit(18, 20, "future")])]
    cropped = transform(source, crop_start=13, crop_end=15, tempo=1.25)
    line = cropped[0]
    assert line.visible_end == 1.6
    assert line.units[0].end == 0
    assert line.units[1].end == 3.2  # Still mid-sweep at 1.6s.
    assert line.units[2].start == 4  # Cannot highlight before the video ends.
    rendered = write_ass(cropped)
    restored = read_ass(rendered)[0]
    assert restored.text == line.text and restored.units == line.units
    assert restored.visible_end == line.visible_end
    assert ",0:00:00.00,0:00:01.60,Romaji," in rendered


def test_next_phrase_preview_after_the_cut_does_not_create_an_invalid_event():
    source = [Line(0, 4, [Unit(0, 4, "singing")]),
              Line(1.5, 7, [Unit(4, 7, "future")])]
    rendered = write_ass(transform(source, crop_end=2))
    events = [row for row in rendered.splitlines() if row.startswith("Dialogue:")]
    assert len(events) == 1 and "future" not in events[0]


@pytest.mark.parametrize("language,text", [("en", "A longer translated sentence " * 5),
                                           ("ru", "Это длинная строка перевода " * 5)])
def test_translation_and_romaji_use_the_same_size_even_when_one_needs_to_fit(language, text):
    rendered = write_ass([Line(0, 2, [Unit(0, 2, "kimi wa")], {language: text})], translations=True)
    rows = [row for row in rendered.splitlines() if row.startswith("Dialogue:")]
    sizes = [re.findall(r"\\fs(\d+)", row) for row in rows]
    assert len(rows) == 2 and sizes[0] == sizes[1] and sizes[0]
    assert f"Style: Translation,Karaoke Rounded,{font_size(720)}," in rendered


def test_cropped_highlight_pixels_match_the_full_recording_before_the_cut(tmp_path):
    ffmpeg = shutil.which("ffmpeg") or ap.FFMPEG
    if not Path(ffmpeg).is_file():
        pytest.skip("FFmpeg is required for the libass timing check")
    source = [Line(0, 7, [Unit(0, 1, "past "), Unit(1, 5, "singing "), Unit(5, 7, "future")])]
    cropped = transform(source, crop_start=1, crop_end=3)
    def frame(lines, seconds, name):
        subtitle = tmp_path / name
        subtitle.write_text(write_ass(lines, width=640, height=360, highlight="51EB85"), encoding="utf-8-sig")
        result = subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=s=640x360:r=10:d=7",
                                 "-vf", ass_filter(subtitle), "-ss", str(seconds), "-frames:v", "1",
                                 "-pix_fmt", "rgb24", "-f", "rawvideo", "-"], capture_output=True, timeout=30)
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        assert len(result.stdout) == 640 * 360 * 3
        return result.stdout
    # The same lyric frame on the original clock and the cropped clock must
    # contain exactly the same highlighted pixels, including the future word.
    assert frame(source, 2.9, "full.ass") == frame(cropped, 1.9, "crop.ass")
