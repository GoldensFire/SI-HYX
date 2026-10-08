# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Bounded title/chapter/page selection shared by supplementary readers."""
import re
from network_attempt import single_attempt_session
from urllib.parse import urljoin, urlsplit

import animepack_api as _api
from .mangadex_api import page_skip, MIN_PANEL_PAGES


SOURCE_LABELS = {"mangadex": "MangaDex", "mangafire": "MangaFire",
                 "comix": "Comix.to", "weebcentral": "WeebCentral",
                 "remanga": "ReManga", "mangalib": "MangaLib"}


class MangaSourceUnavailable(_api.AnimePackApiError):
    """The reader refused access; try other readers during this run."""


class MangaSourceBlocked(MangaSourceUnavailable):
    """API источника ответил 403 — выключен для всех рабочих потоков прогона."""


class MangaSourceWalled(MangaSourceUnavailable):
    """CDN источника закрыт защитой от ботов — до конца генерации."""


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
        self._image_failures, self._image_blocked = {}, set()

    def _request(self, path, params=None):
        deadline = getattr(self, "deadline", None)
        if deadline is None:
            self.limiter.acquire()
        else:
            self.limiter.acquire(deadline=deadline)
        try:
            with single_attempt_session(self.session) as client:
                response = client.get(
                    self.base_url + path, params=params or {},
                    headers={"Referer": self.base_url + "/", "Accept": "*/*"},
                    timeout=(5, 10))
            if response.status_code == 403:
                raise MangaSourceBlocked(
                    f"{self.label}: HTTP 403; источник "
                    "недоступен до конца этой генерации")
            if response.status_code == 429:
                raise MangaSourceUnavailable(
                    f"{self.label}: HTTP 429; источник на паузе")
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
            free = [p for p in body if p["url"].split("?")[0] not in blocked
                    and (urlsplit(p["url"]).hostname, str(row["id"])) not in self._image_blocked
                    and (getattr(self, "_source_health", None) is None
                         or self._source_health.available(p["url"]))]
            if free:
                page = self.rng.choice(free)
                self.last_chapter = key
                self.last_source_link = chapter["link"]
                self.last_page_info = dict(page)
                self.last_page_info["_reader_title"] = str(row["id"])
                index = pages.index(page)
                self.last_page_info["neighbors"] = [
                    dict(pages[index + step], offset=step) for step in (-1, 1)
                    if 0 <= index + step < len(pages)]
                return page["url"]
        return ""

    def download_page(self, url, info):
        from .manga_image_download import download
        key = (urlsplit(url).hostname, str(info.get("_reader_title") or ""))
        health = getattr(self, "_source_health", None)
        if health is not None and not health.available(url):
            raise MangaSourceUnavailable(f"{self.label}: CDN временно недоступен")
        try:
            data = download(self.session, url, self.base_url + "/")
            if health is not None:
                health.record(url)
            self._image_failures.pop(key, None)
            ext = urlsplit(url).path.rsplit(".", 1)[-1].lower()
            return data, "." + ext if ext in (
                "jpg", "jpeg", "png", "webp", "avif") else ".png"
        except Exception as exc:
            if health is not None:
                health.record(url, exc, getattr(self, "_source_health_key", ""))
                wall = health.wall(url)
                if wall:
                    raise MangaSourceWalled(
                        f"{self.label}: картинки закрыты защитой от ботов ({wall}) — "
                        "источник выключен до конца генерации") from exc
            if key[1] and getattr(getattr(exc, "response", None), "status_code", 0) == 403:
                self._image_failures[key] = self._image_failures.get(key, 0) + 1
                if self._image_failures[key] >= 2:
                    self._image_blocked.add(key)
            raise _api._friendly(exc, self.label) from exc
