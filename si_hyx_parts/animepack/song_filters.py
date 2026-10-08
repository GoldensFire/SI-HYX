# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Песни и тайтлы: вид и тег песни, сложность, фильтры AnisongDB/Shikimori. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


def song_kind(song_type: str) -> _api.Optional[str]:
    """«Opening 1» → «opening». None — незнакомый тип."""
    head = str(song_type or "").split(" ")[0].lower()
    return head if head in _api.SONG_KINDS else None

song_kind.__module__ = _api.__name__
_api.song_kind = song_kind


def song_tag(song_type: str) -> str:
    """«Opening 1» → «OP1», «Ending 12» → «ED12», «Insert Song» → «OST».
    Незнакомый тип — пустая строка (в ответ ничего не дописываем)."""
    kind = _api.song_kind(song_type)
    if not kind:
        return ""
    m = _api._RE_TAG_NUM.search(str(song_type or ""))
    return _api._TAG_BY_KIND[kind] + (m.group(1) if m else "")

song_tag.__module__ = _api.__name__
_api.song_tag = song_tag


def _truthy(value) -> bool:
    """AnisongDB когда-то слал 0/1, теперь шлёт true/false — понимаем оба."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes")
    return False

_truthy.__module__ = _api.__name__
_api._truthy = _truthy


def _chunks(seq, size):
    seq = list(seq)
    for i in range(0, len(seq), size):
        yield seq[i:i + size]

_chunks.__module__ = _api.__name__
_api._chunks = _chunks


def _genre_ids(anime: dict) -> set[int]:
    out: set[int] = set()
    for g in (anime.get("genres") or []):
        if not isinstance(g, dict):
            continue
        try:
            out.add(int(g.get("id")))
        except (TypeError, ValueError):
            continue
    return out

_genre_ids.__module__ = _api.__name__
_api._genre_ids = _genre_ids


def song_difficulty_band(s: _api.PackSettings, kind: str) -> tuple[float, float]:
    """Рамка AMQ для типа песни; у OST она отдельная.

    None сохраняет поведение старых settings.json и программного API: пока
    отдельная рамка OST не задана, вставки используют общую рамку OP/ED.
    """
    low, high = s.difficulty_min, s.difficulty_max
    if kind == "insert":
        own_low = getattr(s, "ost_difficulty_min", None)
        own_high = getattr(s, "ost_difficulty_max", None)
        low = low if own_low is None else own_low
        high = high if own_high is None else own_high
    return float(low), float(high)


def song_difficulty_allowed(song: dict, s: _api.PackSettings) -> bool:
    """Проходит ли реальная songDifficulty свою рамку AMQ."""
    kind = _api.song_kind(song.get("songType")) if isinstance(song, dict) else None
    if kind is None:
        return False
    try:
        difficulty = float(song.get("songDifficulty"))
    except (TypeError, ValueError):
        return False
    low, high = song_difficulty_band(s, kind)
    return low <= difficulty <= high


song_difficulty_band.__module__ = _api.__name__


song_difficulty_allowed.__module__ = _api.__name__


_api.song_difficulty_band = song_difficulty_band


_api.song_difficulty_allowed = song_difficulty_allowed


def filter_song(song: dict, s: _api.PackSettings) -> bool:
    """Проходит ли песня по настройкам (без обращения к сети)."""
    if not isinstance(song, dict):
        return False
    if not song.get("audio"):
        return False
    if not song.get("songLength"):
        return False
    kind = _api.song_kind(song.get("songType"))
    if kind is None:
        return False
    # Снятая галочка типа («только опенинги») — песня даже не рассматривается.
    if not s.picked_kinds.get(kind, True):
        return False
    if not song.get("animeType"):
        return False
    if not (song.get("linked_ids") or {}).get("myanimelist"):
        return False
    if not s.allow_rebroadcast and _api._truthy(song.get("isRebroadcast")):
        return False
    if not s.allow_dub and _api._truthy(song.get("isDub")):
        return False
    category = str(song.get("songCategory") or "").lower()
    if not s.categories.get(category, False):
        return False
    return song_difficulty_allowed(song, s)

filter_song.__module__ = _api.__name__
_api.filter_song = filter_song


def filter_anime(anime: dict, s: _api.PackSettings, manga: bool = False) -> bool:
    """Проходит ли карточка Shikimori по настройкам.

    manga=True — та же проверка для карточки манги/ранобэ: у неё свой набор
    типов (манга/манхва/ранобэ) и нет ни скриншотов, ни коллажа."""
    if not isinstance(anime, dict):
        return False
    if not anime.get("malId"):
        return False
    # Из анонсов не берём ничего (просьба пользователя) — см. announced.py.
    if _api.is_announced(anime):
        return False
    if (not (anime.get("poster") or {}).get("originalUrl")
            and s.only_kind != _api.AI_ART_KIND):
        return False
    kind = str(anime.get("kind") or "").lower()
    if manga:
        if kind not in _api.MANGA_KINDS or not s.manga_kinds.get(kind, False):
            return False
    else:
        # Скриншоты нужны, только если из них собирается коллаж (ASPG требовал
        # их всегда и зря выбрасывал половину подходящих тайтлов). Для
        # вопроса-кадра они уже не обязательны: кадры всегда добираются ещё и
        # с AniList/Kitsu.
        if (s.images and s.songs_percent
                and len(anime.get("screenshots") or []) < _api.COLLAGE_IMAGES):
            return False
        if not s.kinds.get(kind, False):
            return False
    year = ((anime.get("airedOn") or {}).get("year"))
    try:
        year = int(year)
    except (TypeError, ValueError):
        return False
    if not (s.year_from <= year <= s.year_to):
        return False
    try:
        score = float(anime.get("score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    if not (s.score_from <= score <= s.score_to):
        return False
    genres = _api._genre_ids(anime)
    if s.genres_exclude and genres & set(s.genres_exclude):
        return False
    if s.genres_include:
        need = set(s.genres_include)
        if s.genres_partial:
            if not (genres & need):
                return False
        elif not need <= genres:
            return False
    return True

filter_anime.__module__ = _api.__name__
_api.filter_anime = filter_anime
