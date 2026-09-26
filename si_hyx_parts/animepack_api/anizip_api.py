# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AniZipApi. Public namespace: animepack_api."""
from __future__ import annotations
import animepack_api as _api


# ─────────────────────────────────────────────────────────────────────────────
# AniZip — кадры эпизодов
# ─────────────────────────────────────────────────────────────────────────────
class AniZipApi:
    """api.ani.zip/mappings — сводка тайтла со всех каталогов сразу.

    Нужна ради поля `image` у каждой серии: это превью эпизода с TheTVDB, то
    есть кадр ИЗ ЭТОЙ серии. У Shikimori скриншотов три-четыре и почти все с
    первой серии, AniList отдаёт превью только с легальных стримингов, а Kitsu
    знает не каждый тайтл — AniZip закрывает как раз середину: у «Наруто» это
    48 разных кадров из 246 серий.

    Ключа и регистрации нет, ищется прямо по MAL id — сводить каталоги, как с
    Kitsu, не требуется. Ответ на тайтл увесистый (пересказы всех серий на
    десятке языков), поэтому держим его в памяти на всю генерацию: один и тот
    же тайтл попадается в паке не раз.
    """

    def __init__(self, session: _api.Optional[_api.requests.Session] = None):
        self.session = session or _api.make_session()
        self.limiter = _api.RateLimiter(3)
        self._cache: dict[int, list[str]] = {}
        self._data_cache: dict[int, dict] = {}
        self._lock = _api.threading.Lock()

    def _mappings(self, mal_id: int) -> dict:
        self.limiter.acquire()
        resp = self.session.get(f"{_api.ANIZIP_BASE}/mappings",
                                params={"mal_id": str(int(mal_id))},
                                timeout=(10, 45))
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {}

    def info(self, mal_id: int) -> dict:
        """Полная сводка AniZip, общая для кадров и точной связки с Jimaku."""
        try:
            mal = int(mal_id or 0)
        except (TypeError, ValueError):
            return {}
        if not mal:
            return {}
        with self._lock:
            known = self._data_cache.get(mal)
        if known is not None:
            return dict(known)
        try:
            data = self._mappings(mal)
        except Exception:  # noqa: BLE001 — вспомогательный источник
            data = {}
        with self._lock:
            self._data_cache[mal] = dict(data)
        return dict(data)

    def anilist_id(self, mal_id: int) -> int:
        mappings = self.info(mal_id).get("mappings") or {}
        try:
            return int(mappings.get("anilist_id") or 0)
        except (TypeError, ValueError):
            return 0

    def episode_numbers(self, mal_id: int) -> list[int]:
        """Номера обычных серий, которые AniZip действительно перечисляет."""
        episodes = self.info(mal_id).get("episodes") or {}
        out = set()
        for key, row in (episodes.items() if isinstance(episodes, dict) else ()):
            value = (row or {}).get("episodeNumber") if isinstance(row, dict) else key
            try:
                raw_number = float(value)
            except (TypeError, ValueError):
                continue
            if not raw_number.is_integer():
                continue
            number = int(raw_number)
            if number > 0:
                out.add(number)
        return sorted(out)

    def tv_episodes(self, mal_id: int) -> list[dict]:
        """Серии с номером сезона и серии по TheTVDB (так их знает SubDL).

        {"season", "episode"} — episode тот же, что в episode_numbers, чтобы
        ведущий называл одну и ту же «Серию N» при любом источнике."""
        episodes = self.info(mal_id).get("episodes") or {}
        out = []
        for row in (episodes.values() if isinstance(episodes, dict) else ()):
            if not isinstance(row, dict):
                continue
            try:
                season = float(row.get("seasonNumber"))
                episode = float(row.get("episodeNumber"))
            except (TypeError, ValueError):
                continue
            if (season.is_integer() and episode.is_integer()
                    and season > 0 and episode > 0):
                out.append({"season": int(season), "episode": int(episode)})
        return out

    def external_ids(self, mal_id: int) -> dict:
        """IMDb и TMDB id тайтла (пустые строки, если AniZip их не знает)."""
        mappings = self.info(mal_id).get("mappings") or {}
        imdb = str(mappings.get("imdb_id") or "").strip()
        tmdb = str(mappings.get("themoviedb_id") or "").strip()
        return {"imdb_id": imdb if imdb.startswith("tt") else "",
                "tmdb_id": tmdb if tmdb.isdigit() else ""}

    def frames(self, mal_id: int) -> list[str]:
        """Превью серий тайтла по MAL id. Пусто — тайтла в AniZip нет."""
        try:
            mal = int(mal_id or 0)
        except (TypeError, ValueError):
            return []
        if not mal:
            return []
        with self._lock:
            known = self._cache.get(mal)
        if known is not None:
            return list(known)
        try:
            data = self.info(mal)
        except Exception:  # noqa: BLE001 — доп. источник кадров, не критичен
            data = {}
        out: list[str] = []
        episodes = data.get("episodes")
        if isinstance(episodes, dict):
            # Порядок словаря — порядок серий; спешлы лежат ключом «S1» и
            # прочими, их сортировка не волнует: кадр всё равно берётся
            # случайный (см. _pick_frame_url).
            for row in episodes.values():
                url = (row or {}).get("image") if isinstance(row, dict) else None
                if url:
                    out.append(str(url))
        with self._lock:
            self._cache[mal] = list(out)
        return out

AniZipApi.__module__ = _api.__name__
_api.AniZipApi = AniZipApi
