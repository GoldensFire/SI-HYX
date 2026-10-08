# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Song video eligibility and reporting, including legacy video questions."""


def requested(settings, candidate):
    if candidate.music_effect == "video":
        return candidate.kind in ("opening", "ending")
    return candidate.is_video or (
        settings.song_video and candidate.kind in ("opening", "ending")
        and getattr(settings, "song_video_percent", None) is None
        and candidate.music_effect == "original")


def log_summary(generator, candidates):
    songs = [candidate for candidate in candidates
             if requested(generator.s, candidate) or candidate.music_effect == "video"]
    if not songs:
        return
    made = sum(candidate.theme_video_ready for candidate in songs)
    generator.log(f"Видео песен: готово {made} из {len(songs)}; "
                  f"аудио вместо видео — {len(songs) - made}.")
