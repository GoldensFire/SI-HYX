# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""TmdbApi. Public namespace: animepack_api."""
from __future__ import annotations
import animepack_api as _api


class TmdbApi:
    """Обложки с themoviedb.org — ЗАПАСНОЙ источник постера.

    Основной — Shikimori: там русские названия и та же карточка, из которой
    считается всё остальное. Но у части тайтлов (свежие ONA, спешлы, редкая
    манга) постера в карточке нет вовсе или ссылка не открывается, и вопрос
    оставался без картинки в ответе. Тогда тайтл ищется здесь по названию.

    Ключ пользовательский (Настройки → API на themoviedb.org, бесплатный).
    Годятся оба вида: старый v3 («api_key=...») и токен v4 («Bearer ...») —
    отличаем по виду строки, у токена всегда есть точки, как у любого JWT.
    """

    # TMDB разрешает ~50 запросов в секунду, но нам столько не нужно: постер
    # спрашивается только там, где Shikimori не дал своего.
    def __init__(self, session: _api.Optional[_api.requests.Session] = None,
                 key: str = "", language: str = "ru-RU"):
        self.session = session or _api.make_session()
        self.key = str(key or "").strip()
        self.language = language
        self.limiter = _api.RateLimiter(8)

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    def _get(self, path: str, params: dict) -> dict:
        headers = {"Accept": "application/json"}
        params = dict(params)
        if "." in self.key:                 # v4 read access token (JWT)
            headers["Authorization"] = f"Bearer {self.key}"
        else:
            params["api_key"] = self.key
        self.limiter.acquire()
        try:
            resp = self.session.get(f"{_api.TMDB_BASE}/{path}", params=params,
                                    headers=headers, timeout=(10, 45))
            if resp.status_code in (401, 403):
                raise _api.AnimePackApiError(
                    "TMDB: ключ не принят — проверьте его в настройках.")
            resp.raise_for_status()
            data = resp.json()
        except _api.AnimePackApiError:
            raise
        except Exception as e:  # noqa: BLE001
            raise _api._friendly(e, "TMDB") from e
        return data if isinstance(data, dict) else {}

    def poster_url(self, names, year: int = 0, movie: bool = False) -> str:
        """Ссылка на обложку тайтла («» — не нашлось).

        Названия перебираются по очереди: сперва оригинальное/английское (по
        ним TMDB ищет надёжнее), русское — последним. Год, если известен,
        отсеивает одноимённые ремейки."""
        if not self.enabled:
            return ""
        for name in names:
            name = str(name or "").strip()
            if not name:
                continue
            for kind in (("movie", "tv") if movie else ("tv", "movie")):
                params = {"query": name, "include_adult": "false",
                          "language": self.language}
                if year:
                    params["first_air_date_year" if kind == "tv"
                           else "primary_release_year"] = str(int(year))
                data = self._get(f"search/{kind}", params)
                url = self._pick(data.get("results") or [], name)
                if url:
                    return url
            if year:
                # Год у аниме и у TMDB иногда расходятся на сезон — второй
                # заход тем же названием, но уже без года.
                for kind in (("movie", "tv") if movie else ("tv", "movie")):
                    data = self._get(f"search/{kind}",
                                     {"query": name, "include_adult": "false",
                                      "language": self.language})
                    url = self._pick(data.get("results") or [], name)
                    if url:
                        return url
        return ""

    @staticmethod
    def _pick(rows: list, name: str) -> str:
        """Постер самого подходящего из найденного.

        Точное совпадение названия важнее популярности: по запросу «Bleach»
        TMDB первой строкой отдаёт документалку про моющее средство."""
        want = str(name or "").strip().casefold()
        best, best_score = "", -1.0
        for row in rows:
            if not isinstance(row, dict):
                continue
            path = str(row.get("poster_path") or "").strip()
            if not path:
                continue
            titles = [str(row.get(k) or "") for k in
                      ("name", "original_name", "title", "original_title")]
            exact = any(t.strip().casefold() == want for t in titles)
            try:
                popular = float(row.get("popularity") or 0.0)
            except (TypeError, ValueError):
                popular = 0.0
            score = (1000.0 if exact else 0.0) + popular
            if score > best_score:
                best, best_score = f"{_api.TMDB_IMG}{path}", score
        return best

TmdbApi.__module__ = _api.__name__
_api.TmdbApi = TmdbApi

# ─────────────────────────────────────────────────────────────────────────────
# AnimeThemes.moe — видео опенингов и эндингов
# ─────────────────────────────────────────────────────────────────────────────
class AnimeThemesApi:
    """Ролики опенингов/эндингов с animethemes.moe (ключи не нужны).

    Чем это лучше прочих источников видео: ролики там БЕЗ КРЕДИТОВ (nc: true) —
    то есть без надписей с названием прямо в кадре, а для угадайки это главное.
    Сервер отдаёт Range (206), поэтому ffmpeg вытягивает нужные секунды, а не
    все сорок мегабайт файла.

    Соответствие с нашими кандидатами идёт по MAL id и метке вида «OP1»/«ED2»:
    в AnisongDB та же песня называется «Opening 1», см. animepack.song_tag."""

    BATCH = 10               # столько MAL id уходит в один запрос

    def __init__(self, session: _api.Optional[_api.requests.Session] = None):
        self.session = session or _api.make_session()
        self.limiter = _api.RateLimiter(3)

    def themes_by_mal_ids(self, ids: _api.Iterable[int]) -> dict:
        """{MAL id: {«OP1»: {url, resolution, size, song}}}.

        Возвращаем словарь по метке, а не список: вопросу нужен ровно тот
        опенинг, который выбран из AnisongDB, а не первый попавшийся."""
        wanted = [str(int(i)) for i in ids if int(i or 0) > 0]
        if not wanted:
            return {}
        params = {
            "filter[has]": "resources",
            "filter[site]": "MyAnimeList",
            "filter[external_id]": ",".join(wanted),
            "include": ("animethemes.animethemeentries.videos,"
                        "animethemes.song,resources"),
            "page[size]": 100,
        }
        self.limiter.acquire()
        try:
            resp = self.session.get(f"{_api.ANIMETHEMES_BASE}/anime", params=params,
                                    timeout=(10, 60))
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            raise _api._friendly(e, "AnimeThemes") from e
        out: dict[int, dict] = {}
        for anime in (data.get("anime") or []):
            mal = 0
            for res in (anime.get("resources") or []):
                if (res or {}).get("site") == "MyAnimeList":
                    try:
                        mal = int(res.get("external_id") or 0)
                    except (TypeError, ValueError):
                        mal = 0
                    if mal:
                        break
            if not mal:
                continue
            by_tag = out.setdefault(mal, {})
            for theme in (anime.get("animethemes") or []):
                tag = f"{(theme.get('type') or '').upper()}{theme.get('sequence') or 1}"
                best = None
                for entry in (theme.get("animethemeentries") or []):
                    for video in (entry.get("videos") or []):
                        link = (video or {}).get("link")
                        if not link:
                            continue
                        res = int(video.get("resolution") or 0)
                        # Из нескольких вариантов берём самый маленький файл при
                        # достаточном разрешении: качать 45 МБ, чтобы отрезать
                        # пятнадцать секунд и ужать до 720p, смысла нет.
                        cur = (0 if res >= 720 else 1, int(video.get("size") or 0))
                        if best is None or cur < best[0]:
                            best = (cur, {"url": str(link), "resolution": res,
                                          "size": int(video.get("size") or 0),
                                          "song": ((theme.get("song") or {})
                                                   .get("title") or "")})
                if best and tag not in by_tag:
                    by_tag[tag] = best[1]
        return out

AnimeThemesApi.__module__ = _api.__name__
_api.AnimeThemesApi = AnimeThemesApi
