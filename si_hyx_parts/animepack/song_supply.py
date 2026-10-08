"""Reserve scarce song candidates and try another song before losing a title."""
from collections import Counter

import animepack as ap


def ordered_songs(generator, songs):
    quotas = getattr(generator, '_selection_quotas', generator.s.question_quotas)
    accepted = Counter(c.kind for c in getattr(generator, '_selected_songs', ()))
    occupied = Counter(c.kind for c in getattr(generator, '_selection_state', ()))

    def score(song):
        kind = ap.song_kind(song.get('songType'))
        need = max(0, quotas.get(kind, 0) - accepted[kind])
        free = max(0, quotas.get(kind, 0) - occupied[kind])
        return (not need, not free, -need / max(1, quotas.get(kind, 0)))

    ordered = sorted(songs, key=score)
    return ordered, bool(ordered and not score(ordered[0])[0])


def retry_song(candidate, failed):
    remaining = list(getattr(candidate, '_song_alternatives', ()))
    if failed and candidate.kind in ap.SONG_KINDS and remaining:
        return remaining.pop(0), remaining
    return None, remaining
