# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Free published ReManga chapters in the existing page selection pipeline."""
from urllib.parse import quote, urlsplit
from datetime import datetime, timedelta, timezone

from .manga_reader_base import MangaReaderBase, MangaSourceUnavailable
from .ru_manga_clients import ReMangaPopulation, PublicSourceError
from .ru_title_matching import match_title, title_names


def publicly_released(row):
    for field in ("pub_date", "delay_pub_date"):
        value = row.get(field)
        if value:
            try:
                when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                # Live ReManga dates omit the zone. Use the latest possible
                # instant across civil time zones, so a delayed release stays
                # excluded until it is unambiguously in the past.
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone(timedelta(hours=-12)))
                if when > datetime.now(timezone.utc):
                    return False
            except ValueError:
                return False
    return True


class ReMangaApi(MangaReaderBase):
    label = "ReManga"
    base_url = ReMangaPopulation.base_url
    languages = ("ru",)

    def __init__(self, session=None, *, population=None, **options):
        super().__init__(session, **options)
        self.population = population or ReMangaPopulation()
        self.last_match_status = "NOT_FOUND"

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
                restricted = (fields.get("is_licensed") is not False
                              or fields.get("is_forbidden") is True)
                adult = fields.get("is_erotic") is True or fields.get("is_yaoi") is True
                if restricted or (adult and not self.allow_erotica):
                    row = None
            self._titles[key] = row
        return self._titles[key]

    def chapters(self, row):
        chapters = []
        for branch in row.get("branches", [])[:4]:
            if not isinstance(branch, dict) or not branch.get("id"):
                continue
            # Bounded public chapter pages; no auth, purchase, or unblocking.
            for page in range(1, 4):
                result = self.population.get("/api/titles/chapters/", {
                    "branch_id": branch["id"], "ordering": "-index", "page": page, "count": 40})
                if result is None or not isinstance(result.get("content"), list):
                    break
                rows = result["content"]
                for chapter in rows:
                    if not isinstance(chapter, dict) or chapter.get("is_paid") is not False:
                        continue
                    if not publicly_released(chapter):
                        continue
                    if not chapter.get("id"):
                        continue
                    chapters.append({"id": str(chapter["id"]), "language": "ru",
                                     "free": True, "link": self.base_url + "/manga/" +
                                     quote(row["slug"], safe="")})
                if len(rows) < 40:
                    break
        return chapters

    def pages(self, chapter):
        if chapter.get("free") is not True:
            return []
        result = self.population.get("/api/titles/chapters/" +
                                     quote(chapter["id"], safe="") + "/")
        data = (result or {}).get("content")
        if not isinstance(data, dict) or data.get("is_published") is not True:
            return []
        if not publicly_released(data):
            return []
        if str(data.get("id") or "") != str(chapter["id"]):
            return []
        if ("is_paid" in data and data["is_paid"] is not False
                or data.get("price") not in (None, "", "0", "0.00", 0)):
            return []
        pages = []
        for page in data.get("pages") or []:
            images = page if isinstance(page, list) else (
                page.get("images") if isinstance(page, dict) else None)
            if not isinstance(images, list):
                continue
            for image in images:
                if not isinstance(image, dict):
                    continue
                url = str(image.get("link") or "")
                if urlsplit(url).scheme in ("https", "http") and urlsplit(url).netloc:
                    pages.append({"url": url})
        return pages
