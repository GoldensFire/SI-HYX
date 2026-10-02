# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Bounded title/chapter/page selection shared by supplementary readers."""
import re
from urllib.parse import urljoin, urlsplit

import animepack_api as _api
from .mangadex_api import page_skip, MIN_PANEL_PAGES


SOURCE_LABELS = {"mangadex": "MangaDex", "mangafire": "MangaFire",
                 "comix": "Comix.to", "weebcentral": "WeebCentral",
                 "remanga": "ReManga", "mangalib": "MangaLib"}


class MangaSourceUnavailable(_api.AnimePackApiError):
    """The reader refused access; try other readers during this run."""


def names(card):
    out = []
    for key in ("name", "english", "japanese", "synonyms", "russian"):
        value = card.get(key)
        for title in value if isinstance(value, (list, tuple)) else [value]:
            if isinstance(title, str) and title.strip() and title.strip() not in out:
                out.append(title.strip())
    return out


def norm(value):
    return re.sub(r"[\W_]+", "", str(value or ""), flags=re.UNICODE).casefold()


def matches(card, row):
    wanted = str(card.get("malId") or "")
    linked = str(row.get("mal_id") or "")
    if wanted and linked:
        return wanted == linked
    return bool({norm(n) for n in names(card)} &
                {norm(n) for n in row.get("titles", []) if norm(n)})


def clean_sources(value=None):
    if not isinstance(value, dict):
        return dict.fromkeys(SOURCE_LABELS, True)
    return {key: bool(value.get(key, False)) for key in SOURCE_LABELS}


def web_url(base, value):
    url = urljoin(base + "/", str(value or ""))
    return url if urlsplit(url).scheme in ("https", "http") else ""


class MangaReaderBase:
    def __init__(self, session=None, *, language="", allow_erotica=False,
                 rng=None):
        self.session = session or _api.make_session()
        self.language = str(language or "")
        self.allow_erotica = bool(allow_erotica)
        self.rng = rng or _api.random.Random()
        self.limiter = _api.RateLimiter(0.5)
        self._titles = {}
        self._chapters = {}
        self._pages = {}
        self.last_titles = []
        self.last_chapter = ""
        self.last_source_link = ""
        self.last_page_info = {}

    def _request(self, path, params=None):
        self.limiter.acquire()
        try:
            response = self.session.get(
                self.base_url + path, params=params or {},
                headers={"Referer": self.base_url + "/", "Accept": "*/*"},
                timeout=(8, 25))
            if response.status_code in (403, 429):
                raise MangaSourceUnavailable(
                    f"{self.label}: HTTP {response.status_code}; источник "
                    "недоступен до конца этой генерации")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response
        except _api.AnimePackApiError:
            raise
        except Exception as exc:
            raise _api._friendly(exc, self.label) from exc

    def _allowed(self, row):
        rating = str(row.get("rating") or "safe").casefold()
        return rating in ("safe", "suggestive") or (
            self.allow_erotica and rating in ("erotica", "adult", "mature"))

    def manga(self, card):
        key = (str(card.get("malId") or ""), tuple(names(card)))
        if key not in self._titles:
            found = None
            queries = [n for n in names(card) if not re.search(r"[Ѐ-ӿ]", n)]
            for query in queries[:3]:
                for row in self.search(query)[:10]:
                    if not matches(card, row):
                        continue
                    detail = self.details(row)
                    if matches(card, detail) and self._allowed(detail):
                        found = detail
                        break
                if found:
                    break
            self._titles[key] = found
        return self._titles[key]

    def panel_url(self, card, excluded=()):
        self.last_chapter = self.last_source_link = ""
        self.last_titles, self.last_page_info = [], {}
        if self.language and self.language not in self.languages:
            return ""
        row = self.manga(card)
        if not row:
            return ""
        self.last_titles = list(row["titles"])
        chapter_key = (row["id"], self.language)
        if chapter_key not in self._chapters:
            self._chapters[chapter_key] = self.chapters(row)
        chapters = list(self._chapters[chapter_key])
        if self.language:
            chapters = [c for c in chapters
                        if c.get("language", self.language) == self.language]
        self.rng.shuffle(chapters)
        languages = list(dict.fromkeys(c.get("language", "") for c in chapters))
        if not self.language and len(languages) > 1:
            preferred = ("ru", "en", "uk")
            languages = [lang for lang in preferred if lang in languages]
            chapters = [chapter for lang in languages
                        for chapter in [c for c in chapters
                                        if c.get("language", "") == lang][:2]]
        blocked = {str(u).split("?")[0] for u in excluded}
        for chapter in chapters[:4]:
            key = chapter["id"]
            if key not in self._pages:
                self._pages[key] = self.pages(chapter)
            pages = self._pages[key]
            if len(pages) < MIN_PANEL_PAGES:
                continue
            skip = page_skip(len(pages))
            body = pages[skip:len(pages) - skip] if skip else pages
            free = [p for p in body if p["url"].split("?")[0] not in blocked]
            if free:
                page = self.rng.choice(free)
                self.last_chapter = key
                self.last_source_link = chapter["link"]
                self.last_page_info = dict(page)
                index = pages.index(page)
                self.last_page_info["neighbors"] = [
                    dict(pages[index + step], offset=step) for step in (-1, 1)
                    if 0 <= index + step < len(pages)]
                return page["url"]
        return ""

    def download_page(self, url, info):
        try:
            response = self.session.get(
                url, headers={"Referer": self.base_url + "/",
                              "Accept": "image/avif,image/webp,*/*"},
                timeout=(10, 45))
            response.raise_for_status()
            ext = urlsplit(url).path.rsplit(".", 1)[-1].lower()
            return response.content, "." + ext if ext in (
                "jpg", "jpeg", "png", "webp", "avif") else ".png"
        except Exception as exc:
            raise _api._friendly(exc, self.label) from exc
