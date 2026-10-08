"""Compare complete credited lineups; a group member is not a solo recording."""
from difflib import SequenceMatcher
import re

from .model import normalize


def same_name(left, right):
    a, b = normalize(left), normalize(right)
    return bool(a and b and (a == b or SequenceMatcher(None, a, b).ratio() >= .93))


def complete_lineup(slots, actual):
    if not slots or len(slots) != len(actual) or len(slots) > 30:
        return False
    # Match each credited singer once, including explicitly supplied name aliases.
    choices = [[i for i, singer in enumerate(actual)
                if any(same_name(alias, singer) for alias in aliases)] for aliases in slots]
    choices.sort(key=len)

    matched = {}

    def assign(index, visited):
        for singer in choices[index]:
            if singer in visited:
                continue
            visited.add(singer)
            previous = matched.get(singer)
            if previous is None or assign(previous, visited):
                matched[singer] = index
                return True
        return False

    return all(assign(index, set()) for index in range(len(choices)))


def performers_match(requested, actual, *, groups=(), lineup=()):
    actual = list(dict.fromkeys(name for name in actual if normalize(name)))
    for name in requested:
        if any(same_name(name, group) for group in groups):
            return True
        if len(actual) == 1 and same_name(name, actual[0]):
            return True
        parts = re.split(r"\s*(?:[,;、&]|\band\b|\bfeat\.?|\bfeaturing\b)\s*", name,
                         flags=re.I)
        slots = [[part] for part in parts if normalize(part)]
        if complete_lineup(slots, actual):
            return True
    return complete_lineup(lineup, actual)


def credited_lineup(song):
    """Only expand the credited group, never a soloist's group affiliations."""
    result = []
    for artist in song.get("artists") or []:
        for performer in artist.get("members") or [artist]:
            names = [name for name in performer.get("names") or [] if isinstance(name, str)]
            if names:
                result.append(names)
    return result
