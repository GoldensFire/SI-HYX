"""Match untimed TV romaji to a site's unsplit full Japanese lyric column."""
from difflib import SequenceMatcher
from functools import lru_cache

from .model import normalize
from .romanization import readings


@lru_cache(maxsize=8192)
def phonetic_key(text):
    return normalize("".join(word["hepburn"] for word in readings(text)))


def native_version(native, roman):
    if not native or not roman:
        return native
    try:
        source = [phonetic_key(line) for line in native]
    except ValueError:
        return native
    target = normalize("".join(roman))
    complete = "".join(source)
    # A projection is only needed when the native column has substantially
    # more text. Different line wrapping alone is not a different version.
    if not target or len(complete) < len(target) * 1.25:
        return native
    matcher = SequenceMatcher(None, complete, target, autojunk=False)
    matched = set()
    for block in matcher.get_matching_blocks():
        matched.update(range(block.a, block.a + block.size))
    if len(matched) / len(target) < .85:
        return native
    selected, cursor = [], 0
    for line, text in zip(native, source):
        covered = sum(i in matched for i in range(cursor, cursor + len(text)))
        cursor += len(text)
        if text and covered / len(text) >= .8:
            selected.append(line)
    return selected if len(selected) >= 3 else native
