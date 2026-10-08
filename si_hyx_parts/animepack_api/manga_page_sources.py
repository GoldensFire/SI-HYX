# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Try enabled page sources without changing the generator's client API."""
import animepack_api as _api
import threading
from .manga_reader_pool import ReaderHealth
from .manga_reader_base import (
    SOURCE_LABELS, MangaSourceBlocked, MangaSourceUnavailable, clean_sources, names)

SOURCE_LANGUAGES = {
    "remanga": ("ru",), "mangalib": ("ru",),
    "mangadex": None, "mangafire": ("ru", "en", "uk", "ja", "ko", "zh",
                                   "fr", "es", "es-la", "pt-br"),
    "comix": ("en",), "weebcentral": ("en",)}


class MangaPageSources:
    def __init__(self, session=None, *, sources=None, language="",
                 allow_erotica=False, rng=None, clients=None):
        enabled = clean_sources(sources)
        self._injected = clients is not None
        self._worker_local = threading.local()
        self._workers_lock = threading.Lock()
        self._workers = []
        self._health = ReaderHealth()
        self._worker_options = dict(sources=enabled, language=language,
                                    allow_erotica=allow_erotica, rng=rng)
        self.language = str(language or "").strip()
        options = dict(language=language, allow_erotica=allow_erotica, rng=rng)
        factories = {"mangadex": _api.MangaDexApi,
                     "mangafire": _api.MangaFireApi, "comix": _api.ComixApi,
                     "weebcentral": _api.WeebCentralApi,
                     "remanga": _api.ReMangaApi, "mangalib": _api.MangaLibApi}
        self.clients = [(key, clients[key] if clients is not None else
                         factory(session, **options))
                        for key, factory in factories.items() if enabled[key]]
        self._disabled = set()
        self._failures = {}
        self._next = {}
        self.last_chapter = self.last_source_link = self.last_source = ""
        self.last_titles, self.last_errors, self.last_page_info = [], [], {}
        self.last_client = None
        self.last_language = ""

    def select_page(self, card, excluded=(), *, deadline=None, stopped=lambda: False):
        from .manga_reader_pool import select_page
        return select_page(self, card, excluded, deadline, stopped)

    def close(self):
        from .manga_reader_pool import close
        close(self)

    def _order(self, cache_key):
        languages = [self.language] if self.language else ["ru", "en", "uk"]
        for language in languages:
            groups = ([("remanga", "mangalib"), ("mangadex", "mangafire")]
                      if language == "ru" else
                      [("mangadex", "mangafire", "comix", "weebcentral")])
            for tier, group in enumerate(groups):
                clients = [(key, client) for key in group
                           for name, client in self.clients if name == key
                           and (SOURCE_LANGUAGES[key] is None
                                or language in SOURCE_LANGUAGES[key])]
                cursor = (cache_key, language, tier)
                start = self._next.get(cursor, 0)
                for key, client in clients[start:] + clients[:start]:
                    yield key, client, language, cursor, clients

    def panel_url(self, card, excluded=()):
        self.last_chapter = self.last_source_link = self.last_source = ""
        self.last_titles, self.last_errors, self.last_page_info = [], [], {}
        self.last_client = None
        self.last_language = ""
        cache_key = (str(card.get("malId") or ""), tuple(names(card)))
        failed = set()
        for key, client, language, cursor, group in self._order(cache_key):
            if key in self._disabled or key in failed or not self._health.provider_available(key):
                continue
            original = getattr(client, "language", "")
            try:
                client.language = language
                url = client.panel_url(card, excluded)
            except Exception as exc:
                failed.add(key)
                self._failures[key] = self._failures.get(key, 0) + 1
                if isinstance(exc, MangaSourceUnavailable) or self._failures[key] >= 3:
                    self._disabled.add(key)
                    # 403 API выключает источник всем рабочим потокам: прежде
                    # каждый поток после 90 с паузы снова получал тот же 403
                    # (Comix.to — 33 отказа за прогон).
                    if isinstance(exc, MangaSourceBlocked):
                        self._health.disable_provider(key)
                    else:
                        self._health.defer_provider(key)
                self.last_errors.append(f"{SOURCE_LABELS[key]}: {exc}")
                continue
            finally:
                client.language = original
            self._failures[key] = 0
            if not url:
                continue
            self.last_source = SOURCE_LABELS[key]
            self.last_language = language
            self.last_chapter = str(getattr(client, "last_chapter", "") or "")
            self.last_titles = list(getattr(client, "last_titles", []) or [])
            self.last_source_link = str(getattr(client, "last_source_link", "") or "")
            self.last_page_info = dict(getattr(client, "last_page_info", {}) or {})
            if key == "mangadex":
                self.last_source_link = _api.mangadex_chapter_link(self.last_chapter)
            else:
                self.last_client = client
            # Rotate within a language/priority tier: an English edition
            # cannot displace another available Russian page on a retry.
            index = next(i for i, (name, _) in enumerate(group) if name == key)
            self._next[cursor] = (index + 1) % len(group)
            return url
        return ""
