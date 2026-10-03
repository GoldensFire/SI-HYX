"""Recover lyric-sized ASR phrases from real word anchors in long stanzas."""
from __future__ import annotations

from difflib import SequenceMatcher
import unicodedata


def key(text):
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())


def phrases(segments, lyrics):
    """Split on known text anchors, retaining ASR times and never filling gaps.

    Whisper often returns a 20-second stanza as one segment. The aligner's
    fixed line/segment pairing then loses later choruses. Character matches
    on the complete monotone word stream locate source line boundaries; the
    aligner still verifies each resulting phrase independently. Unmatched
    lines and ambiguous/shared word boundaries receive no invented interval.
    """
    words = [word for segment in segments for word in segment.get("words", [])
             if word.get("word") and float(word["end"]) > float(word["start"])]
    transcription, owners = [], []
    for index, word in enumerate(words):
        text = key(word["word"])
        transcription.append(text)
        owners.extend([index] * len(text))
    source = [key(line) for line in lyrics]
    matcher = SequenceMatcher(None, "".join(source), "".join(transcription), autojunk=False)
    mapping = {}
    for block in matcher.get_matching_blocks():
        for shift in range(block.size):
            mapping[block.a + shift] = block.b + shift
    result, cursor, previous = [], 0, -1
    for text in source:
        matched = [mapping[i] for i in range(cursor, cursor + len(text)) if i in mapping]
        cursor += len(text)
        if not text or len(matched) / len(text) < .6:
            continue
        first, last = owners[min(matched)], owners[max(matched)]
        if first <= previous or last < first:
            continue
        selected = words[first:last + 1]
        # A match spanning an ASR silence/foreign verse is not a lyric phrase.
        if any(float(b["start"]) - float(a["end"]) > 3
               for a, b in zip(selected, selected[1:])):
            continue
        result.append({"start": selected[0]["start"], "end": selected[-1]["end"],
                       "text": "".join(word["word"] for word in selected), "words": selected})
        previous = last
    return result
