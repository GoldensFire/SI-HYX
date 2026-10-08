"""Can saved difficulty counts supply an exact number and sum of questions?"""


def attainable(counts, slots, points):
    if slots < 0 or points < 0:
        return False
    if slots == 0:
        return points == 0
    if sum(counts.values()) < slots:
        return False
    if not counts or slots * min(counts) > points or slots * max(counts) < points:
        return False
    # One bit per sum, one row per question count. Binary bundles enforce
    # the saved stock of each level without enumerating individual titles.
    rows = [0] * (slots + 1)
    rows[0] = 1
    mask = (1 << (points + 1)) - 1
    for level, count in counts.items():
        left = min(count, slots, points // level)
        bundle = 1
        while left:
            size = min(bundle, left)
            shift = size * level
            for used in range(slots, size - 1, -1):
                rows[used] |= (rows[used - size] << shift) & mask
            left -= size
            bundle *= 2
    return bool(rows[slots] & (1 << points))
