"""Default romaji-only output, fixed typography and opt-in translations."""
import re
from pathlib import Path
import shutil
import subprocess

import pytest

import animepack as ap
from karaoke.ass import read_ass, write_ass
from karaoke.model import Line, Unit
from karaoke.style import COLOURS, ass_colour, choose_colour, font_size
from test_karaoke_timing import ASS


def test_default_hides_both_translations_and_centres_the_main_line():
    text = write_ass(read_ass(ASS), highlight=COLOURS["green"])
    assert "Ты свет" not in text and "You shine" not in text
    assert r"\pos(640,360)" in text
    assert "Style: Romaji,Karaoke Rounded,64," + ass_colour(COLOURS["green"]) in text
    assert ",1,5,1.5,5," in text
    assert font_size(720) > 40
    assert not ap.PackSettings.from_dict({"karaoke_enabled": True}).karaoke_translations


def test_english_is_only_emitted_when_translation_checkbox_is_enabled():
    line = Line(0, 2, [Unit(0, 2, "kimi")], {"en": "You"})
    assert "You" not in write_ass([line])
    assert "You" in write_ass([line], translations=True)


def test_only_safe_position_size_and_karaoke_tags_reach_the_renderer():
    text = write_ass(read_ass(ASS))
    tags = re.findall(r"\\([A-Za-z]+)", text)
    assert set(tags) <= {"kf", "pos", "fs"}
    assert read_ass(text)[0].units == read_ass(ASS)[0].units


def test_every_palette_colour_can_be_selected_and_long_phrases_fit():
    class Pick:
        def __init__(self, index):
            self.index = index
        def choice(self, values):
            return values[self.index]
    assert {choose_colour(Pick(i)) for i in range(9)} == set(COLOURS.values())
    words = "habataitara modoranai to itte " * 3
    text = write_ass([Line(0, 5, [Unit(0, 5, words)])])
    assert r"\fs" in text
    assert read_ass(text)[0].text == words


def test_ffmpeg_selects_the_bundled_rounded_font_instead_of_a_system_fallback(tmp_path):
    from karaoke.render import ass_filter
    ffmpeg = shutil.which("ffmpeg") or ap.FFMPEG
    if not Path(ffmpeg).is_file():
        pytest.skip("FFmpeg is required to verify actual font selection")
    subtitle = tmp_path / "font.ass"
    subtitle.write_text(write_ass([Line(0, 1, [Unit(0, 1, "karaoke")])]), encoding="utf-8-sig")
    result = subprocess.run([ffmpeg, "-v", "verbose", "-f", "lavfi", "-i", "color=s=1280x720:d=1",
                             "-vf", ass_filter(subtitle), "-frames:v", "1", "-f", "null", "-"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    assert result.returncode == 0, result.stderr
    assert re.search(r"fontselect:.*-> KaraokeRounded-Black", result.stderr)
