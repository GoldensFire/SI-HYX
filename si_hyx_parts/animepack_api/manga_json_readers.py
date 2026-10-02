# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""MangaFire and Comix.to: signed unofficial title, chapter and page APIs."""
from .manga_reader_base import MangaReaderBase, web_url
from .manga_request_signing import (
    MANGAFIRE, COMIX, canonical_params, sign, decode_comix)


def _title(row):
    extra = row.get("altTitles") or row.get("alt_titles") or []
    links = row.get("links") or {}
    return {"id": str(row.get("hid") or ""),
            "titles": [row.get("title") or ""] + list(extra),
            "mal_id": str(row.get("malId") or links.get("mal") or ""),
            "rating": row.get("contentRating") or row.get("content_rating"),
            "path": row.get("url") or "/title/" + str(row.get("hid") or "")}


class MangaFireApi(MangaReaderBase):
    label = "MangaFire"
    base_url = "https://mangafire.to"
    languages = ("ru", "en", "uk", "ja", "ko", "zh", "fr", "es", "es-la", "pt-br")

    def _json(self, path, params=None):
        entries = canonical_params(params or {})
        token = sign(path.removeprefix("/api"), entries, MANGAFIRE)
        response = self._request(path, entries + [("vrf", token)])
        return response.json() if response is not None else {}

    def search(self, query):
        data = self._json("/api/titles", {"keyword": query, "limit": 10,
                                         "content_rating[]": self.ratings})
        return [_title(r) for r in data.get("items", []) if r.get("hid")]

    @property
    def ratings(self):
        return ["safe", "suggestive"] + (["erotica"] if self.allow_erotica else [])

    def details(self, row):
        data = self._json("/api/titles/" + row["id"]).get("data") or {}
        return _title(data) if data.get("hid") else row

    def chapters(self, row):
        out = []
        for language in ([self.language] if self.language else ["ru", "en", "uk"]):
            data = self._json("/api/titles/" + row["id"] + "/chapters", {
                "language": language, "sort": "number", "order": "asc",
                "limit": 100, "page": 1})
            for chapter in data.get("items", []):
                if not chapter.get("id"):
                    continue
                if chapter.get("language", language) != language:
                    continue
                key = str(chapter["id"])
                number = str(chapter.get("number") or 0)
                link = row["path"] + f"/{key}-chapter-{number}-{language}"
                out.append({"id": key, "link": web_url(self.base_url, link),
                            "language": language})
        return out

    def pages(self, chapter):
        data = self._json("/api/chapters/" + chapter["id"]).get("data") or {}
        return [{"url": web_url(self.base_url, p["url"])}
                for p in data.get("pages", []) if p.get("url")]


class ComixApi(MangaReaderBase):
    label = "Comix.to"
    base_url = "https://comix.to"
    languages = ("en",)

    def _json(self, path, params=None):
        entries = canonical_params(params or {})
        token = sign(path.removeprefix("/api/v1"), entries, COMIX)
        response = self._request(path, entries + [("_", token)])
        data = response.json() if response is not None else {}
        if data.get("e"):
            data = decode_comix(data["e"])
        return data.get("result") or {}

    def search(self, query):
        ratings = ["safe", "suggestive"] + (["erotica"] if self.allow_erotica else [])
        data = self._json("/api/v1/manga", {"keyword": query, "limit": 10,
                                           "content_rating[]": ratings})
        return [_title(r) for r in data.get("items", []) if r.get("hid")]

    def details(self, row):
        data = self._json("/api/v1/manga/" + row["id"])
        return _title(data) if data.get("hid") else row

    def chapters(self, row):
        data = self._json("/api/v1/manga/" + row["id"] + "/chapters", {
            "limit": 100, "order[number]": "asc", "page": 1})
        out = []
        for chapter in data.get("items", []):
            if not chapter.get("id") or chapter.get("language", "en") != "en":
                continue
            key = str(chapter["id"])
            link = chapter.get("url") or (
                row["path"] + f"/{key}-chapter-{chapter.get('number', 0)}")
            out.append({"id": key, "link": web_url(self.base_url, link)})
        return out

    def pages(self, chapter):
        data = self._json("/api/v1/chapters/" + chapter["id"])
        pages = data.get("pages") or {}
        base = str(pages.get("baseUrl") or self.base_url)
        out = []
        for index, page in enumerate(pages.get("items", [])):
            if not page.get("url"):
                continue
            url = web_url(base, page["url"])
            grid = page.get("s") == 1 or "?v3" in url
            if grid and "v3" not in url.split("?")[-1].split("&"):
                url += ("&" if "?" in url else "?") + "v3"
            out.append({"url": url, "legacy": not grid and (index + 1) % 4 == 0})
        return out

    def download_page(self, url, info):
        from .comix_image import decode_image
        headers = {"Referer": self.base_url + "/", "Accept": "image/webp,*/*"}
        if info.get("legacy"):
            headers["Origin"] = self.base_url
        response = self.session.get(url, headers=headers, timeout=(10, 45))
        response.raise_for_status()
        return decode_image(response.content, response.headers), ".png"
