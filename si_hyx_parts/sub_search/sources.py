# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Источники английских субтитров для «Поиска по сабам».

* SubDL — официальный API; тайтл ищется по точному TMDB/IMDb id из AniZip,
  как и для «Диалогов из аниме». Из выдачи берётся минимальный набор
  архивов, покрывающий серии (сезонные паки вместо поштучных файлов).
* SubSource — официальный API (ключ в заголовке X-API-Key, бесплатно
  60 запросов/мин и 7200/сутки). Тайтл ищется по IMDb id из AniZip (сезоны —
  отдельные записи, берутся сезоны этой части), без IMDb — по названию и году.
  Из английских сабов сначала идут сезонные паки, затем по файлу на серию.
* TSDB (thesubtitledb.org) — открытый API: просмотр без ключа, скачивание
  без ключа 1000 файлов/час (ключ необязателен — 100 000/сутки); сериал —
  деревом сезона по TMDB id, файлы отдаются как есть (не архивом).
* OpenSubtitles — официальный REST API; скачивания ограничены суточной
  квотой аккаунта (от 5 до 20 у бесплатных), поэтому источник по умолчанию
  выключен и тратит квоту на самые скачиваемые файлы тайтла.

Ключи уходят только своим хостам; в кэш и выдачу попадают ссылки без ключей.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import sub_search as _api

from .http_client import HttpError
from .parsers import guess_episode


@dataclass
class Candidate:
    source: str
    key: str                  # стабильный ключ файла в кэше
    url: str                  # ссылка для скачивания (может нести ключ — не хранить)
    name: str
    episode: str = ""
    public_url: str = ""      # ссылка для показа (без ключей)
    rank: int = 0             # 0 — первый файл серии, 1+ — дубли других релизов
    meta: dict = field(default_factory=dict)


class QuotaExceeded(Exception):
    """Источник исчерпал квоту/лимит: до конца прогона он выключается."""


def _norm(s) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKC", str(s or "")).casefold()
    return "".join(ch for ch in s if ch.isalnum())


# ── AniZip: сопоставление каталогов ─────────────────────────────────────────
class AniZip:
    def __init__(self, http, corpus) -> None:
        self.http, self.corpus = http, corpus
        http.set_interval("api.ani.zip", 0.34)

    def mappings(self, field_name: str, value) -> dict:
        """mappings AniZip по mal_id / anidb_id ({} — не знает). Кэш полгода;
        сетевую ошибку не запоминаем."""
        k = f"anizip:{field_name}:{value}"
        known = self.corpus.kv_get(k, _api.MAPPING_TTL)
        if known is not None:
            return known
        try:
            resp = self.http.get(f"{_api.ANIZIP_BASE}/mappings",
                                 params={field_name: str(value)}, ok=(200, 404))
        except HttpError:
            return {}
        data = {}
        if resp.status == 200:
            try:
                raw = resp.json()
            except ValueError:
                raw = {}
            if isinstance(raw, dict):
                data = dict(raw.get("mappings") or {})
                seasons = sorted({int(float(e.get("seasonNumber"))) for e in
                                  (raw.get("episodes") or {}).values()
                                  if isinstance(e, dict) and _is_num(e.get("seasonNumber"))
                                  and float(e.get("seasonNumber")) > 0})
                data["tvdb_seasons"] = seasons
        self.corpus.kv_set(k, data)
        return data

    def external_ids(self, mal_id: int) -> dict:
        m = self.mappings("mal_id", int(mal_id))
        imdb = str(m.get("imdb_id") or "").strip()
        tmdb = str(m.get("themoviedb_id") or "").strip()
        return {"imdb_id": imdb if imdb.startswith("tt") else "",
                "tmdb_id": tmdb if tmdb.isdigit() else "",
                "seasons": list(m.get("tvdb_seasons") or [])}


def _is_num(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


# ── SubDL ───────────────────────────────────────────────────────────────────
def _num(v):
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


# Пауза, когда SubDL просит сбавить темп (дальше — вдвое и вчетверо дольше).
RATE_LIMIT_WAIT = 15.0


class Subdl:
    name = "subdl"

    def __init__(self, http, corpus, anizip, key: str) -> None:
        self.http, self.corpus, self.anizip = http, corpus, anizip
        self.key = str(key or "").strip()
        http.set_interval("api.subdl.com", 0.5)
        http.set_interval("dl.subdl.com", 0.3)

    @staticmethod
    def _error(resp) -> str:
        try:
            data = resp.json() if resp.body else {}
        except ValueError:
            return ""
        return str(data.get("error") or "").casefold() if isinstance(data, dict) else ""

    def _get(self, url: str, params=None, max_bytes=None):
        """Запрос к SubDL: временный лимит («сбавьте темп», 429 без пояснения)
        пережидается паузой и повтором; выключает источник только суточная
        квота или отказ ключа."""
        resp = None
        for wait in (RATE_LIMIT_WAIT, RATE_LIMIT_WAIT * 2, RATE_LIMIT_WAIT * 4, None):
            resp = self.http.get(url, params=params, ok=(200, 403, 404, 429),
                                 max_bytes=max_bytes)
            if resp.status != 429:
                return resp
            error = self._error(resp)
            if "daily" in error or "limit_exceeded" in error:
                raise QuotaExceeded("суточная квота SubDL исчерпана")
            if wait is None:
                break
            # Темп выше, чем SubDL терпит: дальше — реже.
            self.http.set_interval(urlsplit(url).hostname or "", 1.0)
            retry = str(resp.headers.get("retry-after", "") or "").strip()
            self.http._sleep(min(float(retry), 120.0) if retry.isdigit() else wait)
        raise QuotaExceeded("SubDL долго не снимает ограничение запросов")

    def _listing(self, ids: dict, kind: str) -> list:
        ident = ids["imdb_id"] or "tmdb:" + ids["tmdb_id"]
        k = f"subdl:list:{kind}:{ident}"
        known = self.corpus.kv_get(k, _api.LISTING_TTL)
        if known is not None:
            return known
        params = {"api_key": self.key, "type": kind, "languages": "EN",
                  "subs_per_page": 30}
        if ids["imdb_id"]:
            params["imdb_id"] = ids["imdb_id"]
        else:
            params["tmdb_id"] = ids["tmdb_id"]
        resp = self._get(f"{_api.SUBDL_BASE}/subtitles", params=params)
        payload = {}
        try:
            payload = resp.json() if resp.body else {}
        except ValueError:
            payload = {}
        error = str(payload.get("error") or "").casefold() if isinstance(payload, dict) else ""
        if resp.status == 403:
            raise QuotaExceeded("SubDL отклонил ключ API" if "key" in error
                                else "SubDL не пустил запрос (403)")
        rows = []
        subs = payload.get("subtitles") if isinstance(payload, dict) and payload.get("status") else []
        for s in subs if isinstance(subs, list) else []:
            if not isinstance(s, dict):
                continue
            path = urlsplit(str(s.get("url") or "")).path  # без ?api_key=…
            if not path.startswith("/subtitle/"):
                continue
            rows.append({"path": path, "name": str(s.get("release_name") or s.get("name") or ""),
                         "season": _num(s.get("season")), "episode": _num(s.get("episode")),
                         "full": bool(s.get("full_season")),
                         "from": _num(s.get("episode_from")), "to": _num(s.get("episode_end"))})
        self.corpus.kv_set(k, rows)
        return rows

    @staticmethod
    def _cover(rows: list, seasons: list, movie: bool) -> list:
        """Минимальный набор архивов: сезонные паки и диапазоны раньше
        поштучных файлов; файл берётся, только если добавляет непокрытые серии."""
        if seasons:
            own = [r for r in rows if r["season"] in (None, 0) or r["season"] in seasons]
            rows = own or rows
        if movie:
            return rows[:3]

        def span(r):
            if r["full"]:
                return 10_000
            a, b = r["from"], r["to"]
            if a is not None and b is not None and b >= a and (a or b):
                return b - a + 1
            return 1

        covered: dict = {}
        picked, rest = [], []
        for r in sorted(rows, key=lambda r: -span(r)):
            season = r["season"] or 0
            have = covered.setdefault(season, set())
            if "all" in have:
                rest.append(r)
                continue
            if r["full"]:
                have.add("all")
                picked.append(r)
                continue
            a, b = r["from"], r["to"]
            if a is not None and b is not None and b >= a and (a or b):
                eps = set(range(a, b + 1))
            else:
                eps = {r["episode"] or r["from"] or 0}
            if eps - have:
                have |= eps
                picked.append(r)
            else:
                rest.append(r)
        return picked + rest

    def candidates(self, shiki_id: int, card: dict, limit: int = 0) -> list:
        if not self.key:
            return []
        ids = self.anizip.external_ids(shiki_id)
        if not ids["imdb_id"] and not ids["tmdb_id"]:
            return []
        movie = str(card.get("kind") or "") == "movie"
        rows = self._listing(ids, "movie" if movie else "tv")
        out = []
        for n, r in enumerate(self._cover(rows, ids["seasons"], movie)):
            ep = ""
            if r["season"] and r["episode"] and not r["full"] and r["from"] == r["to"]:
                ep = f"S{r['season']:02d}E{r['episode']:02d}"
            url = _api.SUBDL_DL + r["path"]
            out.append(Candidate("subdl", "subdl:" + r["path"], url, r["name"] or r["path"],
                                 ep, url, n, {"season": r["season"]}))
        return out[:limit] if limit else out

    def fetch(self, cand: Candidate) -> bytes:
        resp = self._get(cand.url, max_bytes=48 * 1024 * 1024)
        if resp.status != 200:
            raise HttpError(resp.status, cand.url)
        return resp.body


# Файлов без номера серии (фильм, непонятное имя) — не больше стольких на тайтл.
NO_EPISODE_FILES = 3


def _one_per_episode(cands: list) -> list:
    """По файлу на серию (лучший — первый), архивы-паки целиком, файлов без
    серии — не больше NO_EPISODE_FILES; порядок — по rank."""
    out, loose = [], 0
    for c in sorted(cands, key=lambda c: c.rank):
        if c.episode:
            if c.rank == 0:
                out.append(c)
        elif c.rank == 0 and c.source == "subsource":
            out.append(c)            # пак SubSource
        elif loose < NO_EPISODE_FILES:
            loose += 1
            out.append(c)
    return out


# ── SubSource ───────────────────────────────────────────────────────────────
class SubSource:
    name = "subsource"

    def __init__(self, http, corpus, anizip, key: str) -> None:
        self.http, self.corpus, self.anizip = http, corpus, anizip
        self.key = str(key or "").strip()
        # Бесплатный ключ: 60 запросов в минуту.
        http.set_interval("api.subsource.net", 1.05)

    def _get(self, path: str, params=None, max_bytes=None):
        """GET к API SubSource; 429 пережидается, отказ ключа выключает источник."""
        url = _api.SUBSOURCE_BASE + path
        headers = {"X-API-Key": self.key, "Accept": "application/json"}
        resp = None
        for wait in (RATE_LIMIT_WAIT, RATE_LIMIT_WAIT * 2, RATE_LIMIT_WAIT * 4, None):
            resp = self.http.get(url, headers=headers, params=params,
                                 ok=(200, 401, 403, 404, 429), max_bytes=max_bytes)
            if resp.status in (401, 403):
                raise QuotaExceeded("SubSource отклонил ключ API" if resp.status == 401
                                    else "SubSource не пустил запрос (403) — ключ или квота")
            if resp.status != 429:
                return resp
            if wait is None:
                break
            retry = str(resp.headers.get("retry-after", "") or "").strip()
            if retry.isdigit() and float(retry) > 600:
                raise QuotaExceeded("суточный лимит SubSource исчерпан")
            self.http._sleep(min(float(retry), 120.0) if retry.isdigit() else wait)
        raise QuotaExceeded("SubSource долго не снимает ограничение запросов")

    @staticmethod
    def _payload(resp) -> dict:
        try:
            data = resp.json() if resp.status == 200 and resp.body else {}
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _rows(payload: dict) -> list:
        data = payload.get("data")
        if isinstance(data, dict):
            return [data]
        return [d for d in data or [] if isinstance(d, dict)]

    def _movies(self, ids: dict, card: dict, movie: bool) -> list:
        """[[movieId, season]] записей SubSource для этой части тайтла."""
        name = str(card.get("name") or "").strip()
        aired = card.get("airedOn")
        year = _num(aired.get("year")) if isinstance(aired, dict) else None
        ident = ids["imdb_id"] or f"text:{name}:{year or ''}"
        k = f"subsource:movies:{'movie' if movie else 'tv'}:{ident}"
        found = self.corpus.kv_get(k, _api.LISTING_TTL)
        if found is None:
            kind = "movie" if movie else "series"
            if ids["imdb_id"]:
                params = {"searchType": "imdb", "imdb": ids["imdb_id"], "type": kind}
            elif name:
                params = {"searchType": "text", "q": name, "type": kind}
            else:
                return []
            found = []
            for m in self._rows(self._payload(self._get("/movies/search", params=params))):
                mid = _num(m.get("movieId"))
                if not mid:
                    continue
                if not ids["imdb_id"]:
                    # По названию — только точное совпадение и год ±1.
                    if _norm(name) not in {_norm(m.get("title")), _norm(m.get("alternateTitle"))}:
                        continue
                    ry = _num(m.get("releaseYear"))
                    if year and ry and abs(ry - year) > 1:
                        continue
                found.append([mid, _num(m.get("season"))])
            self.corpus.kv_set(k, found)
        seasons = set(ids["seasons"] or ())
        if seasons and not movie:
            own = [f for f in found if f[1] in seasons]
            found = own or found
        return found

    def _listing(self, movie_id: int) -> list:
        k = f"subsource:subs:{movie_id}"
        rows = self.corpus.kv_get(k, _api.LISTING_TTL)
        if rows is not None:
            return rows
        rows = []
        for page in (1, 2, 3):
            payload = self._payload(self._get(
                "/subtitles", params={"movieId": movie_id, "language": "english",
                                      "limit": 100, "page": page, "sort": "popular"}))
            data = self._rows(payload)
            for s in data:
                sid = _num(s.get("subtitleId"))
                if not sid or str(s.get("language") or "english").casefold() != "english":
                    continue
                info = s.get("releaseInfo") or []
                if isinstance(info, str):
                    info = [info]
                name = next((str(x) for x in info if str(x).strip()), "") or f"subtitle {sid}"
                rows.append({"id": sid, "name": name, "files": _num(s.get("files")) or 1,
                             "dl": _num(s.get("downloads")) or 0})
            pages = _num((payload.get("pagination") or {}).get("pages")) or 1
            if len(data) < 100 or page >= pages:
                break
        self.corpus.kv_set(k, rows)
        return rows

    def candidates(self, shiki_id: int, card: dict, limit: int = 0) -> list:
        if not self.key:
            return []
        ids = self.anizip.external_ids(shiki_id)
        movie = str(card.get("kind") or "") == "movie"
        out = []
        for movie_id, season in self._movies(ids, card, movie):
            # Паки (много файлов) — первыми; поштучные — по файлу на серию.
            seen_ep: dict = {}
            for r in sorted(self._listing(movie_id),
                            key=lambda r: (r["files"] <= 1, -r["dl"])):
                pack = r["files"] > 1
                ep = "" if pack else guess_episode(r["name"])
                if ep:
                    rank = seen_ep.get(ep, 0)
                    seen_ep[ep] = rank + 1
                else:
                    rank = 0 if pack else 1
                url = f"{_api.SUBSOURCE_BASE}/subtitles/{r['id']}/download"
                out.append(Candidate("subsource", f"subsource:{r['id']}", url, r["name"],
                                     ep, "", rank, {"season": season, "id": r["id"]}))
        out = _one_per_episode(out)
        return out[:limit] if limit else out

    def fetch(self, cand: Candidate) -> bytes:
        resp = self._get(f"/subtitles/{int(cand.meta['id'])}/download",
                         max_bytes=48 * 1024 * 1024)
        if resp.status != 200:
            raise HttpError(resp.status, f"subsource {cand.meta['id']}")
        return resp.body


# ── TSDB (The Subtitle Database) ────────────────────────────────────────────
def _tsdb_items(block) -> list:
    sub = block.get("subtitles") if isinstance(block, dict) else None
    items = sub.get("items") if isinstance(sub, dict) else None
    return [i for i in items or [] if isinstance(i, dict)]


class Tsdb:
    """api.thesubtitledb.org: просмотр без ключа и без лимита, скачивание без
    ключа — 1000 файлов в час, с ключом — 100 000 в сутки. Тайтл — по TMDB id из
    AniZip (сериал — деревом сезона), без него — по IMDb или по названию с годом.
    Фильтр языка API применяет только к плоским спискам, поэтому английские
    файлы дерева отбираются здесь."""
    name = "tsdb"

    def __init__(self, http, corpus, anizip, key: str = "") -> None:
        self.http, self.corpus, self.anizip = http, corpus, anizip
        self.key = str(key or "").strip()
        http.set_interval("api.thesubtitledb.org", 0.1)

    def _headers(self) -> dict:
        h = {"Accept": "application/json"}
        if self.key:
            h["Authorization"] = f"Bearer {self.key}"
        return h

    def _lookup(self, path: str, params: dict):
        try:
            resp = self.http.get(_api.TSDB_BASE + path, headers=self._headers(),
                                 params=params, ok=(200, 404), max_bytes=24 * 1024 * 1024)
        except HttpError as exc:
            if exc.status == 401:
                raise QuotaExceeded("TSDB отклонил ключ API (bad_key)") from None
            raise
        if resp.status != 200:
            return {}
        try:
            data = resp.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _rows(data: dict) -> list:
        """[id, серия «S01E02» или "", имя релиза, ИИ-расшифровка, реплик] английских файлов."""
        rows, seen = [], set()

        def add(items, ep=""):
            for i in items:
                sid = _num(i.get("id"))
                if not sid or sid in seen or str(i.get("language") or "") != "en":
                    continue
                seen.add(sid)
                name = str(i.get("release_name") or "").strip().splitlines()
                rows.append([sid, ep, (name[0].strip() if name else "") or f"subtitle {sid}",
                             bool(i.get("ai_transcribed")), int(i.get("cues") or 0)])

        add(_tsdb_items(data))
        for season in data.get("seasons") or []:
            if not isinstance(season, dict):
                continue
            add(_tsdb_items(season))
            for e in season.get("episodes") or []:
                if not isinstance(e, dict):
                    continue
                s, n = _num(e.get("season")), _num(e.get("episode"))
                add(_tsdb_items(e), f"S{s:02d}E{n:02d}" if s and n else "")
        for e in data.get("episodes") or []:   # ответ на запрос одного сезона
            if isinstance(e, dict):
                s, n = _num(e.get("season")), _num(e.get("episode"))
                add(_tsdb_items(e), f"S{s:02d}E{n:02d}" if s and n else "")
        return rows

    def _listing(self, ids: dict, card: dict, movie: bool) -> list:
        seasons = [] if movie else sorted(ids["seasons"] or ())
        ident = (f"tmdb:{ids['tmdb_id']}" if ids["tmdb_id"] else
                 f"imdb:{ids['imdb_id']}" if ids["imdb_id"] else f"title:{card.get('name')}")
        k = f"tsdb:list:{'movie' if movie else 'tv'}:{ident}:{','.join(map(str, seasons))}"
        rows = self.corpus.kv_get(k, _api.LISTING_TTL)
        if rows is not None:
            return rows
        kind = "movie" if movie else "tv"
        if ids["tmdb_id"]:
            base = f"/v1/by-tmdb/{kind}/{ids['tmdb_id']}"
        elif ids["imdb_id"]:
            base = f"/v1/by-imdb/{ids['imdb_id']}"
        else:
            base = ""
        rows = []
        if movie:
            if base:
                rows = self._rows(self._lookup(base, {"lang": "en", "limit": 100}))
        elif base:
            # Сезоны этой части; не вышло (другая нумерация у TMDB) — всё дерево.
            for s in seasons:
                rows += self._rows(self._lookup(f"{base}/season/{s}", {"limit": 100}))
            if not rows:
                rows = self._rows(self._lookup(base, {"limit": 40}))
        else:
            name = str(card.get("name") or "").strip()
            aired = card.get("airedOn")
            year = _num(aired.get("year")) if isinstance(aired, dict) else None
            if name:
                data = self._lookup("/v1/by-title", {"q": name, "type": kind, "limit": 40})
                t = data.get("title") or {}
                ty = _num(t.get("year"))
                # Лучшее совпадение по названию — только при том же годе (±1).
                if t and year and ty and abs(ty - year) <= 1:
                    rows = self._rows(data)
        self.corpus.kv_set(k, rows)
        return rows

    def candidates(self, shiki_id: int, card: dict, limit: int = 0) -> list:
        wait = self._blocked()
        if wait:
            raise self._quota_error(wait)
        ids = self.anizip.external_ids(shiki_id)
        movie = str(card.get("kind") or "") == "movie"
        rows = self._listing(ids, card, movie)
        # Внутри серии: живые сабы раньше ИИ-расшифровки, полнее — раньше.
        rows = sorted(rows, key=lambda r: (r[3], -r[4]))
        out, seen_ep = [], {}
        for sid, ep, name, _ai, _cues in rows:
            ep = ep or guess_episode(name)
            if ep:
                rank = seen_ep.get(ep, 0)
                seen_ep[ep] = rank + 1
            else:
                rank = 0 if movie else 1
            url = f"{_api.TSDB_GET}/{sid}"
            out.append(Candidate("tsdb", f"tsdb:{sid}", url, name, ep, url, rank, {"id": sid}))
        out = _one_per_episode(out)
        return out[:limit] if limit else out

    def _blocked(self) -> float:
        """Секунд до сброса лимита скачиваний (0 — можно качать)."""
        import time
        until = self.corpus.kv_get("tsdb:blocked_until", 86400)
        return max(0.0, float(until or 0) - time.time())

    def _quota_error(self, wait: float) -> QuotaExceeded:
        mins = max(1, int(wait // 60) + 1)
        return QuotaExceeded(f"лимит скачиваний TSDB исчерпан, снова через ~{mins} мин "
                             "(без ключа — 1000 в час; ключ — в Настройках)")

    def fetch(self, cand: Candidate) -> bytes:
        import time
        wait = self._blocked()
        if wait:
            raise self._quota_error(wait)
        auth = {"Authorization": f"Bearer {self.key}"} if self.key else None
        try:
            resp = self.http.get(cand.url, headers=auth, ok=(200, 429),
                                 max_bytes=16 * 1024 * 1024)
        except HttpError as exc:
            if exc.status == 401:
                raise QuotaExceeded("TSDB отклонил ключ API (bad_key)") from None
            raise
        if resp.status == 429:
            # Повторы ничего не дадут до сброса окна — выключаемся сразу и
            # запоминаем срок, чтобы и следующие поиски не стучались зря.
            vals = [str(resp.headers.get(h, "") or "").strip()
                    for h in ("retry-after", "ratelimit-reset")]
            secs = [float(v) for v in vals if v.isdigit()]
            wait = min(max(secs) if secs else 600.0, 3600.0)
            self.corpus.kv_set("tsdb:blocked_until", time.time() + wait)
            raise self._quota_error(wait)
        return resp.body


# ── OpenSubtitles ───────────────────────────────────────────────────────────
class OpenSubtitles:
    name = "opensubtitles"

    def __init__(self, http, corpus, anizip, key: str, user: str, password: str) -> None:
        self.http, self.corpus, self.anizip = http, corpus, anizip
        self.key, self.user, self.password = (str(key or "").strip(), str(user or "").strip(),
                                              str(password or ""))
        self.base = _api.OPENSUBTITLES_BASE
        self.token = ""
        for host in ("api.opensubtitles.com", "vip-api.opensubtitles.com"):
            http.set_interval(host, 1.0)

    @property
    def configured(self) -> bool:
        return bool(self.key and self.user and self.password)

    def _headers(self, auth: bool = False) -> dict:
        h = {"Api-Key": self.key, "Accept": "application/json"}
        if auth and self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _login(self) -> None:
        try:
            data = self.http.post(f"{_api.OPENSUBTITLES_BASE}/login", headers=self._headers(),
                                  json_body={"username": self.user,
                                             "password": self.password}).json()
        except HttpError as exc:
            raise QuotaExceeded(f"OpenSubtitles: вход не удался (HTTP {exc.status})") from None
        self.token = str(data.get("token") or "")
        base = str(data.get("base_url") or "").strip()
        host = urlsplit(base if "//" in base else "https://" + base).hostname or ""
        if host in ("api.opensubtitles.com", "vip-api.opensubtitles.com"):
            self.base = f"https://{host}/api/v1"
        if not self.token:
            raise QuotaExceeded("OpenSubtitles: вход не удался")

    def _quota_closed(self) -> bool:
        import time
        until = self.corpus.kv_get("opensubtitles:quota_until", 2 * 86400)
        return bool(until) and time.time() < float(until)

    def _close_quota(self, reset_utc: str) -> None:
        import time
        from datetime import datetime
        try:
            ts = datetime.fromisoformat(str(reset_utc).replace("Z", "+00:00")).timestamp()
        except ValueError:
            ts = time.time() + 6 * 3600
        self.corpus.kv_set("opensubtitles:quota_until", ts)

    def candidates(self, shiki_id: int, card: dict, limit: int = 0) -> list:
        if not self.configured or self._quota_closed():
            return []
        ids = self.anizip.external_ids(shiki_id)
        movie = str(card.get("kind") or "") == "movie"
        params = {"languages": "en"}
        if ids["imdb_id"]:
            params["imdb_id" if movie else "parent_imdb_id"] = ids["imdb_id"].removeprefix("tt")
        elif ids["tmdb_id"]:
            params["tmdb_id" if movie else "parent_tmdb_id"] = ids["tmdb_id"]
        else:
            return []
        ident = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        k = f"opensubtitles:list:{ident}"
        rows = self.corpus.kv_get(k, _api.LISTING_TTL)
        if rows is None:
            rows = []
            for page in (1, 2, 3):
                try:
                    data = self.http.get(f"{self.base}/subtitles", headers=self._headers(),
                                         params=dict(params, page=page)).json()
                except HttpError as exc:
                    if exc.status in (401, 403):
                        raise QuotaExceeded("OpenSubtitles отклонил ключ API") from None
                    raise
                for item in data.get("data") or []:
                    a = item.get("attributes") or {}
                    fd = a.get("feature_details") or {}
                    s, e = _num(fd.get("season_number")), _num(fd.get("episode_number"))
                    for f in a.get("files") or []:
                        fid = _num(f.get("file_id"))
                        if fid:
                            rows.append({"id": fid, "name": str(f.get("file_name") or fid),
                                         "dl": int(a.get("download_count") or 0),
                                         "ep": f"S{s:02d}E{e:02d}" if s and e else "",
                                         "url": str(a.get("url") or "")})
                if page >= int(data.get("total_pages") or 1):
                    break
            self.corpus.kv_set(k, rows)
        rows = sorted(rows, key=lambda r: -r["dl"])
        out, seen = [], set()
        for r in rows:
            rank = 1 if (r["ep"] and r["ep"] in seen) else 0
            seen.add(r["ep"])
            page = r["url"] if urlsplit(r["url"]).hostname in (
                "www.opensubtitles.com", "opensubtitles.com") else ""
            out.append(Candidate("opensubtitles", f"opensubtitles:{r['id']}", "", r["name"],
                                 r["ep"], page, rank, {"file_id": r["id"]}))
        out.sort(key=lambda c: c.rank)
        return out[:limit] if limit else out

    def fetch(self, cand: Candidate) -> bytes:
        if self._quota_closed():
            raise QuotaExceeded("квота скачиваний OpenSubtitles на сегодня исчерпана")
        if not self.token:
            self._login()
        for attempt in (1, 2):
            resp = self.http.post(f"{self.base}/download", headers=self._headers(auth=True),
                                  json_body={"file_id": int(cand.meta["file_id"])},
                                  ok=(200, 401, 406))
            if resp.status == 401 and attempt == 1:
                self._login()
                continue
            break
        try:
            info = resp.json()
        except ValueError:
            info = {}
        if resp.status == 406 or int(info.get("remaining", 1) or 0) < 0:
            self._close_quota(info.get("reset_time_utc", ""))
            raise QuotaExceeded("квота скачиваний OpenSubtitles на сегодня исчерпана")
        if resp.status != 200 or not info.get("link"):
            raise HttpError(resp.status, "opensubtitles download")
        link = str(info["link"])
        if urlsplit(link).scheme != "https":
            raise HttpError(0, "opensubtitles link")
        body = self.http.get(link).body   # временная ссылка — без наших заголовков
        if int(info.get("remaining", 1) or 0) == 0:
            self._close_quota(info.get("reset_time_utc", ""))
        return body
