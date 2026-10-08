# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Списки пользователей: UserList и кэш уже загруженных списков. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


def user_list_cache_key(source: str, username: str, statuses) -> tuple:
    """Ключ кэша: источник + ник без учёта регистра + набор статусов."""
    return (str(source or "").strip().lower(),
            str(username or "").strip().casefold(),
            tuple(sorted(str(s) for s in (statuses or []))))

user_list_cache_key.__module__ = _api.__name__
_api.user_list_cache_key = user_list_cache_key

def cached_user_list(key: tuple) -> _api.Optional[list[int]]:
    with _api._LISTS_LOCK:
        ids = _api._LISTS_CACHE.get(key)
    return list(ids) if ids is not None else None

cached_user_list.__module__ = _api.__name__
_api.cached_user_list = cached_user_list

def remember_user_list(key: tuple, ids) -> None:
    with _api._LISTS_LOCK:
        _api._LISTS_CACHE[key] = [int(i) for i in ids]

remember_user_list.__module__ = _api.__name__
_api.remember_user_list = remember_user_list

def clear_user_list_cache() -> None:
    """Забыть все запомненные списки (нужно тестам и кнопке «обновить»)."""
    with _api._LISTS_LOCK:
        _api._LISTS_CACHE.clear()

clear_user_list_cache.__module__ = _api.__name__
_api.clear_user_list_cache = clear_user_list_cache

# ─────────────────────────────────────────────────────────────────────────────
# Настройки
# ─────────────────────────────────────────────────────────────────────────────
@_api.dataclass
class UserList:
    """Один пользователь и его списки (карточка «Add List» в ASPG)."""
    username: str = ""
    source: str = "shikimori"            # shikimori | myanimelist | anilist
    statuses: list[str] = _api.field(
        default_factory=lambda: ["watching", "completed"])
    # Что берём из списка: аниме или мангу/ранобэ (у всех трёх сайтов это
    # отдельные разделы — см. LIST_TARGETS).
    target: str = "anime"
    # Доля вопросов пака, которую даёт ЭТОТ список, в процентах. 0 — «как
    # получится»: тогда порядок общий и большой список просто перевешивает
    # маленькие (у кого 1500 тайтлов, тот и заполнит пак). Ползунок на вкладке
    # раздаёт сотню между всеми списками.
    share: int = 0
    # «В основном музыка»: тайтлы из этого списка по возможности становятся
    # песенными вопросами, а не кадрами и персонажами. Нужно для списков, где
    # человек угадывает только музыку (просьба пользователя).
    prefer_music: bool = False

    def to_dict(self) -> dict:
        return {"username": self.username, "source": self.source,
                "statuses": list(self.statuses), "target": self.target,
                "share": int(self.share),
                "prefer_music": bool(self.prefer_music)}

    @classmethod
    def from_dict(cls, d: dict) -> '_api.UserList':
        d = d or {}
        st = [s for s in (d.get("statuses") or []) if s in _api.LIST_STATUSES]
        target = str(d.get("target") or "anime")
        try:
            share = max(0, min(100, int(d.get("share") or 0)))
        except (TypeError, ValueError):
            share = 0
        return cls(username=str(d.get("username") or "").strip(),
                   source=str(d.get("source") or "shikimori"),
                   statuses=st or ["watching", "completed"],
                   target=target if target in _api.LIST_TARGETS else "anime",
                   share=share,
                   prefer_music=bool(d.get("prefer_music")))

UserList.__module__ = _api.__name__
_api.UserList = UserList

def _current_year() -> int:
    return _api.date.today().year

_current_year.__module__ = _api.__name__
_api._current_year = _current_year
