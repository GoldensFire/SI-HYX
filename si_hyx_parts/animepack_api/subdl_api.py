# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Клиент SubDL: русские субтитры серии для вопросов «Диалоги из аниме».

SubDL идёт ПЕРВЫМ, Jimaku — когда суточная квота SubDL кончилась (просьба
пользователя). Русские субтитры не нужно переводить, поэтому такой вопрос не
стоит ни одного запроса Gemini.

Тайтл ищется только по точному IMDb/TMDB id из AniZip — поиск по похожему
названию не используется, как и у Jimaku. Серия — по номеру сезона и серии
TheTVDB. Сборники серий, целые сезоны и чужие языки отбрасываются.

Ключ уходит параметром запроса только на api.subdl.com; в ссылку ответа идёт
страница субтитров на сайте, без ключа.
"""
from __future__ import annotations

import io
import os
import time
import zipfile

import animepack_api as _api

_SUB_EXTS = {".srt", ".ass", ".ssa"}
# Сколько ждать, если SubDL просит сбавить темп (ошибка rate_limit).
RATE_LIMIT_WAIT = 15.0


class SubdlQuotaError(_api.AnimePackApiError):
    """Суточная квота ключа SubDL исчерпана — дальше диалоги из Jimaku."""


def _payload(response) -> dict:
    try:
        data = response.json()
    except Exception:  # noqa: BLE001 — тело бывает не JSON (страница CDN)
        return {}
    return data if isinstance(data, dict) else {}


def _number(value):
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _single_episode(item: dict, season: int, episode: int) -> bool:
    """Файл ровно этой серии: не сезон целиком и не диапазон серий."""
    if item.get("full_season"):
        return False
    start = _number(item.get("episode_from"))
    end = _number(item.get("episode_end"))
    if start is not None and end is not None and start != end:
        return False
    own = _number(item.get("episode"))
    if own is None:
        own = start if start is not None else end
    if own != episode:
        return False
    own_season = _number(item.get("season"))
    return own_season in (None, season)


def _russian(item: dict) -> bool:
    lang = str(item.get("language") or item.get("lang") or "").casefold()
    return lang in ("ru", "russian", "русский")


class SubdlApi:
    """Поиск русских субтитров одной серии по IMDb/TMDB id."""

    def __init__(self, api_key: str,
                 session: _api.Optional[_api.requests.Session] = None,
                 sleep=time.sleep):
        self.api_key = str(api_key or "").strip()
        self.session = session or _api.make_session()
        self.limiter = _api.RateLimiter(2)
        self._sleep = sleep
        self._found: dict[tuple, list[dict]] = {}
        self._lock = _api.threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _check(self, response, retry):
        code = int(getattr(response, "status_code", 0) or 0)
        if code == 403:
            error = str(_payload(response).get("error") or "").casefold()
            if "key" in error or "auth" in error:
                raise _api.AnimePackApiError("SubDL отклонил ключ API")
            raise _api.AnimePackApiError("SubDL не пустил запрос (403)")
        if code == 429:
            error = str(_payload(response).get("error") or "").casefold()
            if error == "rate_limit":
                if retry:
                    self._sleep(RATE_LIMIT_WAIT)
                    return None
                raise _api.AnimePackApiError("SubDL просит сбавить темп")
            if error == "service_busy":
                raise _api.AnimePackApiError("SubDL занят, попробуйте позже")
            # daily_limit, api_download_limit_exceeded и 429 без пояснения —
            # на сегодня ключ своё отработал.
            raise SubdlQuotaError("суточная квота ключа SubDL исчерпана")
        if code == 404:
            return response
        response.raise_for_status()
        return response

    def _get(self, url: str, params=None):
        for retry in (True, False):
            self.limiter.acquire()
            response = self.session.get(url, params=params, timeout=(10, 45))
            checked = self._check(response, retry)
            if checked is not None:
                return checked
        raise _api.AnimePackApiError("SubDL просит сбавить темп")

    def episode_files(self, ids: dict, season: int, episode: int) -> list[dict]:
        """Русские субтитры ровно этой серии: [{name, url, page}]."""
        if not self.configured:
            raise _api.AnimePackApiError("не введён ключ SubDL API")
        imdb = str((ids or {}).get("imdb_id") or "")
        tmdb = str((ids or {}).get("tmdb_id") or "")
        if not imdb and not tmdb:
            return []
        key = (imdb or "tmdb:" + tmdb, int(season), int(episode))
        with self._lock:
            known = self._found.get(key)
        if known is not None:
            return [dict(row) for row in known]
        params = {"api_key": self.api_key, "type": "tv", "languages": "RU",
                  "season_number": key[1], "episode_number": key[2],
                  "subs_per_page": 30, "unpack": 1}
        params["imdb_id" if imdb else "tmdb_id"] = imdb or tmdb
        response = self._get(f"{_api.SUBDL_BASE}/subtitles", params)
        data = _payload(response) if response.status_code == 200 else {}
        out = []
        rows = data.get("subtitles") if data.get("status", True) else []
        for item in rows if isinstance(rows, list) else []:
            if (not isinstance(item, dict) or not _russian(item)
                    or not _single_episode(item, key[1], key[2])):
                continue
            url = str(item.get("url") or "")
            if not url.startswith("/"):
                continue
            page = str(item.get("subtitlePage") or "")
            out.append({"name": str(item.get("release_name")
                                    or item.get("name") or ""),
                        "url": url, "episode": key[2],
                        "page": (_api.SUBDL_SITE + page
                                 if page.startswith("/") else "")})
        with self._lock:
            self._found[key] = [dict(row) for row in out]
        return out

    def download(self, item: dict, max_bytes: int = 3 * 1024 * 1024):
        """(данные, имя файла) субтитров серии; (b"", "") — не вышло.

        Ответ — архив или (при unpack) сам файл. Из архива берётся только
        файл этой серии: одиночный, либо тот, чьё имя называет её номер."""
        url = _api.SUBDL_DL + str((item or {}).get("url") or "")
        response = self._get(url)
        if response.status_code != 200:
            return b"", ""
        data = bytes(response.content or b"")
        if not data or len(data) > 8 * max_bytes:
            return b"", ""
        if not zipfile.is_zipfile(io.BytesIO(data)):
            # Без архива имени файла нет — род субтитров видно по телу.
            name = str(item.get("name") or "subtitle")
            if os.path.splitext(name)[1].casefold() not in _SUB_EXTS:
                name += ".ass" if b"[Events]" in data[:65536] else ".srt"
            return (data, name) if len(data) <= max_bytes else (b"", "")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = [n for n in archive.namelist()
                     if os.path.splitext(n)[1].casefold() in _SUB_EXTS]
            if len(names) > 1:
                episode = int(item.get("episode") or 0)
                names = [n for n in names
                         if _api.jimaku_file_episode(n) == episode]
            if len(names) != 1:
                return b"", ""
            info = archive.getinfo(names[0])
            if info.file_size > max_bytes:
                return b"", ""
            return archive.read(info), os.path.basename(names[0])


SubdlApi.__module__ = _api.__name__
SubdlQuotaError.__module__ = _api.__name__
