# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Anonymous, rate-limited population clients. API evidence: docs/manga-ru.md."""
from urllib.parse import quote

import animepack_api as _api
from .ru_title_matching import normalized, title_names
from si_hyx_parts.animepack.ru_popularity_math import number
from .population_rate_limit import PopulationRateLimiter, request_with_backoff


class PublicSourceError(_api.AnimePackApiError):
    pass


def labels_kind(value):
    if isinstance(value, dict):
        value = value.get("label")
    return {"manga": "manga", "манга": "manga", "manhwa": "manhwa",
            "манхва": "manhwa", "manhua": "manhua", "маньхуа": "manhua"}.get(
                str(value or "").strip().casefold(), "")


def aliases(data, fields):
    result = []
    for field in fields:
        value = data.get(field)
        for title in value if isinstance(value, list) else [value]:
            if isinstance(title, str) and title.strip() and title.strip() not in result:
                result.append(title.strip())
    return result


def exact_search_hit(card, row, fields):
    return bool({normalized(name) for name in title_names(card)} &
                {normalized(name) for name in aliases(row, fields)})


def detail_client(self):
    """Отдельная сессия рабочего потока; темп и остановка общие для источника."""
    client = type(self)()
    client.limiter, client.stopped = self.limiter, self.stopped
    return client


class ReMangaPopulation:
    source = "remanga"
    metric = "count_bookmarks"
    detail_workers = 8
    catalog_limit = 40  # /api/titles/ clamps count to 40 (verified 2026-10-01).
    detail_client = detail_client
    # The public mirror proxies /api/ on its own origin; its api subdomain
    # still returns DDoS-Guard's geoblocked response outside the CIS.
    base_url = "https://xn--80aaig9ahr.xn--c1avg"

    def __init__(self, session=None):
        # Do not inherit retrying/cookie-bearing generator adapters.
        import requests
        self.session = session or requests.Session()
        self.limiter = PopulationRateLimiter(32)
        self.stopped = lambda: False

    def get(self, path, params=None):
        try:
            response = request_with_backoff(self.limiter, lambda: self.session.get(
                                        self.base_url + path, params=params or {},
                                        headers={"Accept": "application/json"},
                                        timeout=(5, 15)), self.stopped)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict) or "content" not in result:
                raise ValueError("ReManga response has no content")
            return result
        except Exception as exc:
            raise PublicSourceError(f"ReManga: {exc}") from exc

    def normalize(self, data, *, catalog=False):
        if not isinstance(data, dict) or not data.get("dir") or not data.get("id"):
            raise PublicSourceError("ReManga: title identity missing")
        raw_type = data.get("type")
        type_id = raw_type.get("id") if isinstance(raw_type, dict) else raw_type
        kind = ({1: "manga", 2: "manhwa", 3: "manhua",
                 4: "other", 5: "other", 6: "other", 7: "other"}.get(type_id)
                if isinstance(type_id, int) else labels_kind(raw_type))
        if isinstance(raw_type, str) and raw_type.strip() in (
                "Западный комикс", "Рукомикс", "Индонезийский комикс"):
            kind = "other"
        if not kind and catalog and isinstance(raw_type, str) and raw_type.strip():
            # Неизвестную метку проверяем по точному type.id из деталей.
            kind = ""
        elif not kind:
            raise PublicSourceError("ReManga: unknown/missing type id")
        licensed = data.get("is_licensed")
        forbidden = data.get("is_forbidden") is True
        status = ("RIGHTS_RESTRICTED" if licensed is True or forbidden else
                  "NORMAL" if licensed is False and kind else "ERROR")
        return {"id": str(data["id"]), "slug": data["dir"], "kind": kind,
                "titles": aliases(data, ("main_name", "secondary_name", "rus_name",
                                         "en_name", "another_name")),
                "year": data.get("issue_year"), "metric": self.metric,
                "raw_metric": number(data.get(self.metric)), "status": status,
                "fields": {k: data[k] for k in (self.metric, "total_views",
                           "total_votes", "count_chapters", "is_licensed",
                           "is_forbidden", "is_erotic", "is_yaoi") if k in data},
                "branches": data.get("branches") or []}

    def details(self, row):
        result = self.get("/api/titles/" + quote(str(row["slug"]), safe="") + "/")
        return self.normalize(result["content"]) if result else None

    def catalog_page(self, page):
        result = self.get("/api/titles/", {"page": page, "count": self.catalog_limit,
                          "ordering": "id", "content": "manga"})
        if result is None or not isinstance(result["content"], list):
            raise PublicSourceError("ReManga: invalid catalog page")
        return [self.normalize(row, catalog=True) for row in result["content"]]

    def search(self, card):
        rows = {}
        for query in title_names(card)[:3]:
            result = self.get("/api/search/", {"query": query, "count": 5,
                                               "page": 1, "field": "titles"})
            if result is None or not isinstance(result["content"], list):
                raise PublicSourceError("ReManga: invalid search response")
            for row in result["content"]:
                if (isinstance(row, dict) and row.get("dir") and exact_search_hit(
                        card, row, ("main_name", "secondary_name", "rus_name", "en_name"))):
                    rows.setdefault(row["dir"], {"slug": row["dir"]})
        # Enrich search results before matching; never accept the first hit.
        if len(rows) > 8:
            return []
        return [detail for row in rows.values() if (detail := self.details(row))]


class MangaLibPopulation:
    """HTTP/2 public API used by mangalib.org (verified 2026-10-01)."""
    source = "mangalib"
    metric = "rating.votes"
    detail_workers = 2
    catalog_limit = 60  # API accepts limit=10..60; per_page is ignored.
    detail_client = detail_client
    base_url = "https://api.cdnlibs.org"
    site_url = "https://mangalib.org"
    # Serializing the whole 300+ MB database each minute blocks memo writes
    # for ~9 seconds; incomplete cards can still require cached details.
    checkpoint_interval = 300

    def __init__(self, session=None):
        self.session = session
        self.limiter = PopulationRateLimiter(1.6, per_minute=100)
        self.stopped = lambda: False

    def get(self, path, params=None):
        try:
            if self.session is None:
                import httpx
                self.session = httpx.Client(http2=True, timeout=15,
                                            headers={"Accept": "application/json",
                                                     "Site-Id": "1",
                                                     "Referer": self.site_url + "/ru"})
            response = request_with_backoff(self.limiter, lambda: self.session.get(
                self.base_url + path, params=params or {}), self.stopped)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict) or "data" not in result:
                raise ValueError("MangaLib response has no data")
            return result
        except Exception as exc:
            raise PublicSourceError(f"MangaLib: {exc}") from exc

    def normalize(self, data, *, catalog=False):
        if not isinstance(data, dict) or not data.get("id") or not data.get("slug_url"):
            raise PublicSourceError("MangaLib: title identity missing")
        closed = data.get("close_view")
        status = ("RIGHTS_RESTRICTED" if closed in (1, True)
                  or data.get("is_licensed") is True else
                  "NORMAL" if closed in (0, False) else "ERROR")
        rating = data.get("rating")
        votes = number(rating.get("votes")) if isinstance(rating, dict) else None
        if catalog and closed is None and votes is not None and status == "ERROR":
            # Public catalog statistics do not grant access to chapters.
            # The reader separately checks licensing against live details.
            status = "NORMAL"
        # No numeric type-id guesses. Unknown types use one declared cohort
        # comprising the complete public site_id=1 catalog.
        kind = labels_kind(data.get("type"))
        year = str(data.get("releaseDate") or "")
        return {"id": str(data["id"]), "slug": data["slug_url"], "kind": kind,
                "titles": aliases(data, ("name", "rus_name", "eng_name", "otherNames")),
                "year": int(year) if year.isdigit() else None,
                "shiki_id": data.get("shiki_id"), "authors": data.get("authors") or [],
                "metric": self.metric, "raw_metric": votes,
                "status": status, "fields": {k: data[k] for k in
                    ("rating", "views", "rate", "rate_avg", "chap_count", "close_view", "type_id",
                     "is_licensed", "ageRestriction")
                    if k in data}}

    def details(self, row):
        result = self.get("/api/manga/" + quote(str(row["slug"]), safe=""),
                          {"fields[]": ["rate", "close_view", "eng_name", "otherNames",
                                        "releaseDate", "type_id", "authors", "chap_count"]})
        return self.normalize(result["data"]) if result else None

    def catalog_page(self, page):
        result = self.get("/api/manga", {"site_id[]": 1, "page": page,
                          "limit": self.catalog_limit,
                          "sort_by": "created_at", "sort_type": "asc",
                          "fields[]": ["releaseDate", "rate"]})
        if result is None or not isinstance(result["data"], list):
            raise PublicSourceError("MangaLib: invalid catalog page")
        return [self.normalize(row, catalog=True) for row in result["data"]]

    def search(self, card):
        rows = {}
        for query in title_names(card)[:3]:
            result = self.get("/api/manga", {"site_id[]": 1, "q": query,
                                           "fields[]": ["releaseDate"]})
            if result is None or not isinstance(result["data"], list):
                raise PublicSourceError("MangaLib: invalid search response")
            for row in result["data"]:
                if (isinstance(row, dict) and row.get("slug_url") and exact_search_hit(
                        card, row, ("name", "rus_name", "eng_name", "otherNames"))):
                    rows.setdefault(row["slug_url"], {"slug": row["slug_url"]})
        if len(rows) > 8:
            return []
        return [detail for row in rows.values() if (detail := self.details(row))]
