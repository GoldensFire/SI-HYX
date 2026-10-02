# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Public MangaLib chapters and server-provided image hosts; docs/manga-ru.md."""
from urllib.parse import quote, urlsplit

from .manga_reader_base import MangaReaderBase, MangaSourceUnavailable
from .remanga_reader import publicly_released
from .ru_manga_clients import MangaLibPopulation, PublicSourceError
from .ru_title_matching import match_title, title_names


def free_chapter(row):
    return (isinstance(row, dict) and row.get("expired_type") == 0
            and row.get("bundle_id") is None and row.get("bundle") is None
            and publicly_released({"pub_date": row.get("publish_at"),
                                   "delay_pub_date": row.get("created_at")}))


class MangaLibApi(MangaReaderBase):
    label = "MangaLib"
    base_url = MangaLibPopulation.site_url
    languages = ("ru",)

    def __init__(self, session=None, *, population=None, **options):
        super().__init__(session, **options)
        self.population = population or MangaLibPopulation()
        self.last_match_status = "NOT_FOUND"
        self._image_server = None

    def _get(self, path, params=None):
        try:
            return self.population.get(path, params)
        except PublicSourceError as exc:
            raise MangaSourceUnavailable(str(exc)) from exc

    def manga(self, card):
        key = (str(card.get("id") or ""), tuple(title_names(card)))
        if key not in self._titles:
            try:
                status, row = match_title(card, self.population.search(card))
            except PublicSourceError as exc:
                raise MangaSourceUnavailable(str(exc)) from exc
            self.last_match_status = status
            if row is not None:
                fields = row["fields"]
                age = fields.get("ageRestriction") or {}
                adult = isinstance(age, dict) and str(age.get("label", "")).startswith("18")
                if (row["status"] != "NORMAL" or fields.get("is_licensed") is not False
                        or (adult and not self.allow_erotica)):
                    row = None
            self._titles[key] = row
        return self._titles[key]

    def chapters(self, row):
        slug = quote(row["slug"], safe="")
        result = self._get("/api/manga/" + slug + "/chapters")
        data = (result or {}).get("data")
        if not isinstance(data, list):
            return []
        chapters = []
        for item in data[-120:]:
            if not isinstance(item, dict) or item.get("bundle_id") is not None:
                continue
            if item.get("volume") is None or item.get("number") is None:
                continue
            for branch in (item.get("branches") or [])[:4]:
                if not free_chapter(branch) or not branch.get("id"):
                    continue
                chapters.append({"id": str(branch["id"]), "manga_id": row["id"],
                    "slug": slug, "volume": str(item["volume"]),
                    "number": str(item["number"]), "branch_id": branch.get("branch_id"),
                    "language": "ru", "free": True,
                    "link": self.base_url + "/ru/" + slug})
        return chapters

    def _server(self):
        if self._image_server is None:
            result = self._get("/api/constants", {"fields[]": ["imageServers"]})
            servers = ((result or {}).get("data") or {}).get("imageServers") or []
            self._image_server = ""
            for server in servers:
                if (not isinstance(server, dict) or server.get("id") != "main"
                        or 1 not in (server.get("site_ids") or [])):
                    continue
                url = str(server.get("url") or "")
                if urlsplit(url).scheme == "https" and urlsplit(url).netloc:
                    self._image_server = url.rstrip("/")
                    break
        return self._image_server

    def pages(self, chapter):
        if chapter.get("free") is not True:
            return []
        params = {"volume": chapter["volume"], "number": chapter["number"]}
        if chapter.get("branch_id") is not None:
            params["branch_id"] = chapter["branch_id"]
        result = self._get("/api/manga/" + chapter["slug"] + "/chapter", params)
        data = (result or {}).get("data")
        if (not free_chapter(data) or str(data.get("id")) != chapter["id"]
                or str(data.get("manga_id")) != chapter["manga_id"]):
            return []
        server = self._server()
        if not server:
            return []
        pages = []
        for page in data.get("pages") or []:
            if (not isinstance(page, dict) or page.get("external") != 0
                    or page.get("chunks") != 0):
                continue
            path = str(page.get("url") or "")
            # This is the frontend's literal server.url + page.url rule.
            # //manga/... is a resource path, not a protocol-relative hostname.
            if path.startswith(("//manga/", "/manga/")) and ".." not in path.split("/"):
                pages.append({"url": server + path})
        return pages
