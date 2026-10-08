"""Providers with verified output in the October 2026 episode audit."""
ACTIVE_NATIVE = ("anizone", "anikoto", "kaa", "animegg", "aniwaves")
DISABLED = frozenset(("anineko", "anibd", "miruro", "mkissa", "animeonsen", "reanime"))
RU_CAPABLE = frozenset(("anizone", "anikoto"))
START_DELAY = {"kaa": 2, "animegg": 4, "aniwaves": 8}


def enabled(name, ctx=None):
    name = str(name or "").casefold().split("/", 1)[0]
    if name in DISABLED:
        return False
    mode = (ctx or {}).get("subtitle_mode")
    return not (mode == "required" and name in ACTIVE_NATIVE and name not in RU_CAPABLE)
