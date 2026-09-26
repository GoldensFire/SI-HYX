# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Строгий клиент Jimaku для вопросов по настоящим диалогам."""
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit, urlunsplit

import animepack_api as _api


_SUB_EXTS = {".srt", ".ass", ".ssa"}
_BAD_FILE = re.compile(
    r"(?:generated\s+by|whisper|subgen|speech.?to.?text|\bocr\b|\bai[ _-]?subs?\b|"
    r"machine[ _-]?translat|\bbatch\b|complete)", re.IGNORECASE)
_BATCH = re.compile(r"(?:\b\d{1,3}\s*[-~]\s*\d{1,3}\b|\b(?:all|全集)\b)",
                    re.IGNORECASE)
_EP_PATTERNS = (
    re.compile(r"\bS\d{1,2}E(\d{1,4})(?:v\d+)?\b", re.IGNORECASE),
    re.compile(r"\b(?:EP?|Episode)[ ._-]*(\d{1,4})(?:v\d+)?\b", re.IGNORECASE),
    re.compile(r"(?:^|\s[-_–—]\s|\[)(\d{1,4})(?:v\d+)?(?:\]|\s|\.|$)",
               re.IGNORECASE),
)


def clean_source_url(url: str) -> str:
    """Ссылка для ответа без query/fragment, где теоретически мог быть токен."""
    parts = urlsplit(str(url or ""))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def file_episode(name: str) -> int | None:
    """Номер одиночной серии из имени файла; сборники намеренно отвергаются."""
    text = os.path.basename(str(name or ""))
    if _BATCH.search(text):
        return None
    for pattern in _EP_PATTERNS:
        match = pattern.search(text)
        if match:
            number = int(match.group(1))
            return number if number > 0 else None
    return None


def _flagged(entry: dict, flag: str) -> bool:
    flags = entry.get("flags") or {}
    if isinstance(flags, dict):
        return bool(flags.get(flag))
    if isinstance(flags, (list, tuple, set)):
        return flag in {str(value).casefold() for value in flags}
    return flag in str(flags).casefold().split()


class JimakuApi:
    """Поиск субтитров только по точному AniList id, без угадывания названия."""

    def __init__(self, api_key: str,
                 session: _api.Optional[_api.requests.Session] = None):
        self.api_key = str(api_key or "").strip()
        self.session = session or _api.make_session()
        self.limiter = _api.RateLimiter(3)
        self._entries: dict[int, dict] = {}
        self._files: dict[tuple[int, int], list[dict]] = {}
        self._lock = _api.threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _get(self, url: str, **kwargs):
        if not self.configured:
            raise _api.AnimePackApiError("не введён ключ Jimaku API")
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["Authorization"] = self.api_key
        self.limiter.acquire()
        response = self.session.get(url, headers=headers,
                                    timeout=(10, 45), **kwargs)
        if response.status_code in (401, 403):
            raise _api.AnimePackApiError("Jimaku отклонил ключ API")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response

    def entry(self, anilist_id: int) -> dict:
        """Проверенная запись аниме с тем же AniList id либо пустой словарь."""
        aid = int(anilist_id or 0)
        if not aid:
            return {}
        with self._lock:
            if aid in self._entries:
                return dict(self._entries[aid])
        response = self._get(f"{_api.JIMAKU_BASE}/entries/search",
                             params={"anilist_id": aid})
        rows = response.json() if response is not None else []
        if not isinstance(rows, list):
            rows = []
        exact = [row for row in rows if isinstance(row, dict)
                 and int(row.get("anilist_id") or 0) == aid
                 and not _flagged(row, "unverified")
                 and not _flagged(row, "adult")]
        anime = [row for row in exact if _flagged(row, "anime")]
        chosen = (anime or exact or [{}])[0]
        with self._lock:
            self._entries[aid] = dict(chosen)
        return dict(chosen)

    def files(self, entry_id: int, episode: int) -> list[dict]:
        """Только обычные файлы субтитров, явно совпавшие с номером серии."""
        key = (int(entry_id), int(episode))
        with self._lock:
            known = self._files.get(key)
        if known is not None:
            return [dict(row) for row in known]
        response = self._get(f"{_api.JIMAKU_BASE}/entries/{key[0]}/files",
                             params={"episode": key[1]})
        rows = response.json() if response is not None else []
        out = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "")
            if (os.path.splitext(name)[1].casefold() not in _SUB_EXTS
                    or _BAD_FILE.search(name) or file_episode(name) != key[1]
                    or not str(row.get("url") or "").startswith("https://")):
                continue
            out.append(dict(row))
        with self._lock:
            self._files[key] = [dict(row) for row in out]
        return out

    def download(self, file: dict, max_bytes: int = 3 * 1024 * 1024) -> bytes:
        url = str((file or {}).get("url") or "")
        host = (urlsplit(url).hostname or "").casefold()
        if host == "jimaku.cc" or host.endswith(".jimaku.cc"):
            response = self._get(url)
        else:
            # Не отправляем пользовательский ключ на сторонний CDN, даже если
            # его URL вернул Jimaku.
            self.limiter.acquire()
            response = self.session.get(url, timeout=(10, 45))
            response.raise_for_status()
        data = bytes(response.content if response is not None else b"")
        if not data or len(data) > max_bytes:
            return b""
        return data


JimakuApi.__module__ = _api.__name__
_api.JimakuApi = JimakuApi
_api.jimaku_file_episode = file_episode
_api.jimaku_clean_source_url = clean_source_url
