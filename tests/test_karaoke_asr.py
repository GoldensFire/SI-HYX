"""Long ASR stanzas must retain actual word anchors without filling missing lyrics."""
from karaoke.asr_phrases import phrases


def test_four_lyric_lines_inside_one_asr_stanza_use_word_boundaries():
    words = [{"word": text, "start": i * .5, "end": (i + 1) * .5}
             for i, text in enumerate(["強く", "なれる", "僕を", "連れて", "夜の", "匂い", "空を", "見て"])]
    result = phrases([{"words": words}], ["強くなれる", "僕を連れて", "夜の匂い", "空を見て"])
    assert [(row["start"], row["end"]) for row in result] == [(0, 1), (1, 2), (2, 3), (3, 4)]
    assert all(len(row["words"]) == 2 for row in result)


def test_unrelated_lyrics_do_not_get_fake_uniform_timing():
    segments = [{"words": [{"word": "知らない曲", "start": 0, "end": 4}]}]
    assert phrases(segments, ["強くなれる", "僕を連れて"]) == []


def test_repeated_choruses_keep_forward_order():
    words = [{"word": text, "start": i, "end": i + 1}
             for i, text in enumerate(["kimi", " wa", " sora", " kimi", " wa"])]
    result = phrases([{"words": words}], ["kimi wa", "sora", "kimi wa"])
    assert [row["start"] for row in result] == [0, 2, 3]
