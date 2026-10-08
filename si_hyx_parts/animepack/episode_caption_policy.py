"""Explicit subtitle modes, including migration of the former RU checkbox."""
MODES = ("none", "required", "preferred")


def mode(settings):
    value = str(getattr(settings, "episode_subtitle_mode", "") or "")
    if value in MODES:
        return value
    return "required" if getattr(settings, "episode_ru_subtitles", False) else "none"


def dialogue_window(rows):
    import re
    lines = {re.sub(r"\W+", "", text.casefold()) for left, right, text in rows
             if right - left >= .5 and len(re.findall(r"[^\W\d_]", text)) >= 4}
    intervals = sorted((left, right) for left, right, _ in rows)
    coverage, end = 0.0, 0.0
    for left, right in intervals:
        coverage += max(0, right - max(end, left))
        end = max(end, right)
    return coverage >= 3 and (len(lines) >= 2 or any(len(line) >= 24 for line in lines))
