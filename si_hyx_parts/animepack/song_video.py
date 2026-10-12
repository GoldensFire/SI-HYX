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


def video_only(settings, candidate) -> bool:
    """Песня вне рамки сложности AMQ попала в пак только ради видеоряда.

    Без видео такой вопрос не задаётся: ни слот звука, ни запасной звук
    вместо несостоявшегося ролика ей не положены (см. filter_song)."""
    song = getattr(candidate, "song", None) or {}
    if not song or getattr(candidate, "kind", "") not in ("opening", "ending"):
        return False
    import animepack as api
    # Без мест под видеоряд исключения из рамки нет — песня пришла не через
    # него, и «только ради видео» она быть не может.
    if not api.video_ignores_difficulty(settings):
        return False
    return not api.song_difficulty_allowed(song, settings)


def log_summary(generator, candidates):
    songs = [candidate for candidate in candidates
             if requested(generator.s, candidate) or candidate.music_effect == "video"]
    if not songs:
        return
    made = sum(candidate.theme_video_ready for candidate in songs)
    generator.log(f"Видео песен: готово {made} из {len(songs)}; "
                  f"аудио вместо видео — {len(songs) - made}.")
