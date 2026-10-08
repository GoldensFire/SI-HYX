"""Database maintenance settings do not inherit generation or view filters."""


def database_settings():
    import animepack as api
    return api.PackSettings(
        year_from=0, year_to=9999, score_from=0, genres_exclude=[],
        kinds=dict.fromkeys(api.ANIME_KINDS, True),
        manga_kinds=dict.fromkeys(api.MANGA_KINDS, True),
        pack_manga=True, pct_manga=100, pct_songs=0,
        manga_gemini_check=False, manga_character_crop=False)
