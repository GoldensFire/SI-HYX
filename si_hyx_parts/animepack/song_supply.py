"""Reserve scarce song candidates and try another song before losing a title."""
from collections import Counter

import animepack as ap


def ordered_songs(generator, songs):
    quotas = getattr(generator, '_selection_quotas', generator.s.question_quotas)
    accepted = Counter(c.kind for c in getattr(generator, '_selected_songs', ()))
    occupied = Counter(c.kind for c in getattr(generator, '_selection_state', ()))
    from .karaoke_catalog import karaoke_free, song_timed
    karaoke = bool(songs) and karaoke_free(generator)

    def timed(song):
        # Песня из индекса Karaoke Mugen — первой, пока ждут слоты караоке.
        try:
            mal = int((song.get('linked_ids') or {}).get('myanimelist') or 0)
        except (TypeError, ValueError):
            mal = 0
        return karaoke and song_timed(generator, mal, song)

    slots = getattr(generator, '_effect_slots', None)
    video_free = slots is None or slots.video_free()

    def blocked(song):
        # Вне рамки AMQ песня годится только под видеоряд (filter_song): пока
        # его места заняты, она последняя в очереди тайтла.
        kind = ap.song_kind(song.get('songType'))
        return (not video_free and kind in ('opening', 'ending')
                and not ap.song_difficulty_allowed(song, generator.s))

    def score(song):
        kind = ap.song_kind(song.get('songType'))
        need = max(0, quotas.get(kind, 0) - accepted[kind])
        free = max(0, quotas.get(kind, 0) - occupied[kind])
        return (blocked(song), not need, not free, not timed(song),
                -need / max(1, quotas.get(kind, 0)))

    ordered = sorted(songs, key=score)
    first = score(ordered[0]) if ordered else None
    return ordered, bool(first and not first[0] and not first[1])


def retry_song(candidate, failed):
    remaining = list(getattr(candidate, '_song_alternatives', ()))
    if failed and candidate.kind in ap.SONG_KINDS and remaining:
        return remaining.pop(0), remaining
    return None, remaining
