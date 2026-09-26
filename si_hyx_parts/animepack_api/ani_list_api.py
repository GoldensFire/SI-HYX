# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AniListApi. Public namespace: animepack_api."""
from __future__ import annotations
import animepack_api as _api


# ─────────────────────────────────────────────────────────────────────────────
# AniList — список пользователя и картинки
# ─────────────────────────────────────────────────────────────────────────────
class AniListApi:
    """Публичный GraphQL AniList: ключ не нужен, лимит 90 запросов в минуту.

    Список пользователя приходит ОДНИМ запросом и сразу с MAL id — сводить
    каталоги (как пришлось бы с Kitsu или AniDB) не требуется.

    Картинки: `streamingEpisodes.thumbnail` — превью серий с легальных
    стримингов, то есть кадры из РАЗНЫХ серий, а не только из первой, как у
    Shikimori. Плюс баннер тайтла (широкий кадр) и обложка.
    """

    # Раздел манги — тот же запрос с type: MANGA (манхва, манхуа и ранобэ у
    # AniList лежат там же, различаясь полем format).
    LIST_QUERY = """query($name: String) {
      MediaListCollection(userName: $name, type: ANIME) {
        lists { entries { status media { idMal } } }
      }
    }"""
    LIST_QUERY_MANGA = LIST_QUERY.replace("type: ANIME", "type: MANGA")

    IMAGES_QUERY = """query($idMal: Int) {
      Media(idMal: $idMal, type: ANIME) {
        bannerImage
        coverImage { extraLarge large }
        streamingEpisodes { thumbnail }
      }
    }"""

    def __init__(self, session: _api.Optional[_api.requests.Session] = None):
        self.session = session or _api.make_session()
        self.limiter = _api.RateLimiter(1.2)      # 90/мин с запасом

    def _graphql(self, query: str, variables: dict) -> dict:
        self.limiter.acquire()
        try:
            resp = self.session.post(_api.ANILIST_BASE,
                                     json={"query": query, "variables": variables},
                                     timeout=(10, 45))
            if resp.status_code == 404:
                return {}
            resp.raise_for_status()
            body = resp.json()
        except Exception as e:
            raise _api._friendly(e, "AniList") from e
        if isinstance(body, dict) and body.get("errors"):
            first = (body["errors"] or [{}])[0]
            raise _api.AnimePackApiError(f"AniList: {first.get('message') or 'ошибка'}")
        data = (body or {}).get("data") if isinstance(body, dict) else None
        return data if isinstance(data, dict) else {}

    def user_anime_ids(self, username: str, statuses: _api.Iterable[str],
                       progress_cb: _api.Optional[_api.Callable[[str], None]] = None,
                       should_stop: _api.Optional[_api.Callable[[], bool]] = None,
                       target: str = "anime") -> list[int]:
        """MAL id аниме (или манги) пользователя с нужными статусами (пагинации
        нет — MediaListCollection отдаёт весь список сразу)."""
        wanted = {s for s in statuses if s in _api.LIST_STATUSES}
        nick = (username or "").strip()
        if not nick or not wanted:
            return []
        manga = str(target or "anime") == "manga"
        query = self.LIST_QUERY_MANGA if manga else self.LIST_QUERY
        try:
            data = self._graphql(query, {"name": nick})
        except _api.AnimePackApiError as e:
            if "not found" in str(e).lower():
                raise _api.AnimePackApiError(
                    f"AniList: пользователь «{nick}» не найден.") from e
            raise
        out: list[int] = []
        seen: set[int] = set()
        collection = (data.get("MediaListCollection") or {})
        for lst in (collection.get("lists") or []):
            if should_stop and should_stop():
                break
            for entry in ((lst or {}).get("entries") or []):
                if not isinstance(entry, dict):
                    continue
                if _api._ANILIST_STATUS.get(entry.get("status")) not in wanted:
                    continue
                mal = ((entry.get("media") or {}).get("idMal"))
                try:
                    mal = int(mal)
                except (TypeError, ValueError):
                    continue        # у части тайтлов AniList нет пары на MAL
                if mal in seen:
                    continue
                seen.add(mal)
                out.append(mal)
        if progress_cb:
            progress_cb(f"AniList/{nick}: получено {len(out)} "
                        f"{'манги' if manga else 'аниме'}…")
        return out

    def frames(self, mal_id: int) -> list[str]:
        """Кадры тайтла: превью серий (по одному на серию) + баннер."""
        try:
            data = self._graphql(self.IMAGES_QUERY, {"idMal": int(mal_id)})
        except Exception:  # noqa: BLE001 — дополнительный источник, не критичен
            return []
        media = data.get("Media") or {}
        out = [str(ep.get("thumbnail")) for ep in (media.get("streamingEpisodes") or [])
               if isinstance(ep, dict) and ep.get("thumbnail")]
        if media.get("bannerImage"):
            out.append(str(media["bannerImage"]))
        return out

AniListApi.__module__ = _api.__name__
_api.AniListApi = AniListApi

# ─────────────────────────────────────────────────────────────────────────────
# Kitsu — превью серий
# ─────────────────────────────────────────────────────────────────────────────
class KitsuApi:
    """Kitsu (JSON:API, без ключа). Берём только миниатюры серий: у каждой серии
    свой кадр, поэтому один тайтл даёт десятки разных сцен вместо трёх-четырёх
    скриншотов Shikimori.

    Kitsu живёт на своих id, поэтому сперва ищем тайтл по MAL id через
    /mappings, а уже потом спрашиваем серии."""

    EPISODES_LIMIT = 20      # больше Kitsu не отдаёт: page[limit]=40 → 400

    def __init__(self, session: _api.Optional[_api.requests.Session] = None):
        self.session = session or _api.make_session()
        self.limiter = _api.RateLimiter(3)

    def _get(self, path: str, params: dict) -> dict:
        self.limiter.acquire()
        resp = self.session.get(f"{_api.KITSU_BASE}/{path}", params=params,
                                headers={"Accept": "application/vnd.api+json"},
                                timeout=(10, 45))
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {}

    def anime_id(self, mal_id: int) -> _api.Optional[int]:
        """Kitsu id тайтла по его MAL id («» — пары нет)."""
        try:
            data = self._get("mappings", {
                "filter[externalSite]": "myanimelist/anime",
                "filter[externalId]": str(int(mal_id)),
                "include": "item"})
        except Exception:  # noqa: BLE001
            return None
        for item in (data.get("included") or []):
            if isinstance(item, dict) and item.get("type") == "anime":
                try:
                    return int(item.get("id"))
                except (TypeError, ValueError):
                    return None
        return None

    def frames(self, mal_id: int) -> list[str]:
        """Миниатюры серий тайтла (по MAL id). Пусто — пары в Kitsu нет."""
        kid = self.anime_id(mal_id)
        if not kid:
            return []
        try:
            # Без sparse fieldset (`fields[episodes]`): с ним Kitsu отдаёт
            # пустую выборку — проверено живым запросом.
            data = self._get(f"anime/{kid}/episodes",
                             {"page[limit]": self.EPISODES_LIMIT})
        except Exception:  # noqa: BLE001
            return []
        out = []
        for row in (data.get("data") or []):
            thumb = ((row or {}).get("attributes") or {}).get("thumbnail") or {}
            url = thumb.get("original") or thumb.get("large")
            if url:
                out.append(str(url))
        return out

KitsuApi.__module__ = _api.__name__
_api.KitsuApi = KitsuApi
