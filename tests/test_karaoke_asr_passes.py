"""A second language must preserve previously confirmed monotone evidence."""
from karaoke.asr_passes import combine
from karaoke.lyric_versions import phonetic_key


def test_long_secondary_anchor_cannot_erase_an_entire_confirmed_verse():
    original = ["心"] * 8
    primary = [dict(line_index=i, start=i * 3, end=i * 3 + 2, text="こころ") for i in range(8)]
    secondary = [dict(line_index=0, start=0, end=90, text="心")]
    rows = combine(primary, secondary, original)
    assert rows == primary


def test_japanese_pass_quality_uses_the_same_phonetic_comparison_as_confirmation():
    original = ["心を繋ぐ強い絆"]
    primary = dict(line_index=0, start=0, end=3, text="こころをつなぐつよいきずな")
    secondary = dict(line_index=0, start=0, end=3, text="心と絆")
    assert combine([primary], [secondary], original, normalizer=phonetic_key) == [primary]
