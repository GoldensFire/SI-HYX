"""Authored timing, crop boundaries, translation safety and tempo semantics."""
import pytest

from karaoke.ass import read_ass, write_ass
from karaoke.model import Line, Unit
from karaoke.timeline import transform
from karaoke.ttml import read_ttml

ASS = r"""[Script Info]
ScriptType: v4.00+
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:05.00,Romaji,,0,0,0,,{\k50\fad(200,200)}{\k100}ki{\kf150}mi {\k100}wa
Dialogue: 0,0:00:01.00,0:00:05.00,RU,,0,0,0,,Ты {\pos(1,1)}свет
Dialogue: 0,0:00:01.00,0:00:05.00,EN translation,,0,0,0,,You shine
Dialogue: 0,0:00:01.00,0:00:05.00,Romaji-furigana,,0,0,0,,{\k400}duplicate
"""


def test_ass_keeps_leadin_and_syllable_sweep_without_source_commands():
    lines = read_ass(ASS)
    assert len(lines) == 1
    assert [(u.start, u.end, u.text) for u in lines[0].units] == [
        (1.5, 2.5, "ki"), (2.5, 4.0, "mi "), (4.0, 5.0, "wa")]
    rendered = write_ass(lines, translations=True)
    assert r"{\kf50}{\kf100}ki{\kf150}mi {\kf100}wa" in rendered
    assert r"\fad" not in rendered and r"\pos(1,1)" not in rendered
    assert r"\pos(640,322)" in rendered and r"\pos(640,398)" in rendered
    assert "Ты свет" in rendered and "You shine" not in rendered
    translations = [s for s in rendered.splitlines() if s.startswith("Dialogue:") and ",Translation," in s]
    assert len(translations) == 1 and r"\kf" not in translations[0]


def test_ass_native_only_uses_dictionary_and_keeps_authored_clock():
    pytest.importorskip("pykakasi")
    pytest.importorskip("sudachipy")
    payload = r"""[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Kanji,,0,0,0,,{\kf100}君{\kf100}は
Dialogue: 0,0:00:01.00,0:00:03.00,EN translation,,0,0,0,,{\kf200}You
"""
    line = read_ass(payload)[0]
    assert line.text.strip() == "kimi wa"
    assert [(unit.start, unit.end) for unit in line.units] == [(1, 2), (2, 3)]
    assert line.translation == "You"
    assert len(read_ass(payload)) == 1


def test_ass_authored_romaji_prevents_reading_duplicate_kanji(monkeypatch):
    import karaoke.romanization as pronunciation
    def unexpected(*args):
        raise AssertionError("Authored romaji must be used directly")
    monkeypatch.setattr(pronunciation, "romanize_units", unexpected)
    payload = ASS + r"Dialogue: 0,0:00:01.00,0:00:05.00,Kanji,,0,0,0,,{\kf400}君は" + "\n"
    lines = read_ass(payload)
    assert len(lines) == 1 and lines[0].text == "kimi wa"


def test_crop_through_a_syllable_and_tempo_scale_preserves_phrase():
    result = transform(read_ass(ASS), crop_start=3, crop_end=4.5, tempo=1.5)
    assert result[0].text == "kimi wa"
    assert result[0].start == 0
    assert result[0].end == pytest.approx(4 / 3)
    assert result[0].visible_end == 1
    assert [(u.start, u.end) for u in result[0].units] == [
        (0, 0), (0, pytest.approx(2 / 3)), (pytest.approx(2 / 3), pytest.approx(4 / 3))]
    assert result[0].translation == "Ты свет"
    assert transform(read_ass(ASS), reverse=True) == []


def test_gaps_are_rendered_as_unhighlighted_waits_without_rounding_drift():
    line = Line(0, 3, [Unit(.5, 1, "hello "), Unit(2, 3, "world")])
    text = write_ass([line])
    assert r"{\kf50}{\kf50}hello {\kf100}{\kf100}world" in text
    assert read_ass(text)[0].units == line.units


def test_ttml_word_romaji_and_ru_preference():
    payload = b'''<tt xmlns="http://www.w3.org/ns/ttml"
    xmlns:ttm="http://www.w3.org/ns/ttml#metadata" xml:lang="ja"><body><div>
    <p begin="1s" end="5s"><span begin="1.5s" end="3s">kimi </span>
    <span begin="3s" end="4.5s">wa</span>
    <span ttm:role="x-translation" xml:lang="en">You</span>
    <span ttm:role="x-translation" xml:lang="ru">&#1058;&#1099;</span></p>
    </div></body></tt>'''
    line = read_ttml(payload)[0]
    assert line.text == "kimi wa"
    assert line.translation == "Ты"
    assert line.units[0].start == 1.5


def test_ttml_without_word_timing_is_not_claimed_to_be_karaoke():
    with pytest.raises(ValueError, match="таймингами"):
        read_ttml(b'<tt><body><p begin="1s" end="5s">kimi wa</p></body></tt>')


def test_ttml_authored_romaji_is_preferred_to_dictionary_reading():
    payload = '''<tt xmlns:ttm="http://www.w3.org/ns/ttml#metadata"><body>
    <p begin="0s" end="2s"><span begin="0s" end="1s">君</span>
    <span begin="1s" end="2s">は</span><span ttm:role="x-roman">kimi wa</span>
    </p></body></tt>'''.encode()
    assert read_ttml(payload)[0].text == "kimi wa"


def test_dictionary_multiple_readings_preserve_a_single_authored_word_interval():
    pytest.importorskip("pykakasi")
    pytest.importorskip("sudachipy")
    payload = '<tt><body><p begin="0s" end="2s"><span begin="0s" end="2s">君は</span></p></body></tt>'.encode()
    units = read_ttml(payload)[0].units
    assert len(units) == 1 and units[0].start == 0 and units[0].end == 2
    assert "kimi" in units[0].text


@pytest.mark.parametrize("rate", [0, -1, float("nan"), float("inf")])
def test_invalid_tempo_is_rejected(rate):
    with pytest.raises(ValueError):
        transform(read_ass(ASS), tempo=rate)
