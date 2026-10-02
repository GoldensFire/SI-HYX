# -*- coding: utf-8 -*-
"""Source fallback, settings, UI persistence and generator provenance."""
import io
from PIL import Image

import animepack as ap
import animepack_tab
from animepack_api import MangaPageSources
from si_hyx_parts.animepack_api.manga_reader_base import (
    SOURCE_LABELS, MangaSourceUnavailable)
from test_animepack_manga_sakuga import generator, make_anime  # noqa: F401


class Reader:
    def __init__(self, result="", error=None):
        self.result, self.error = result, error
        self.last_chapter = "chapter"
        self.last_titles = ["Naruto"]
        self.last_source_link = "https://mangafire.to/title/n/7-chapter-1-en"
        self.last_page_info = {"legacy": False}
        self.calls = []

    def panel_url(self, card, excluded):
        self.calls.append(set(excluded))
        if self.error:
            raise self.error
        return self.result

    def download_page(self, url, info):
        self.downloaded = url, dict(info)
        stream = io.BytesIO()
        Image.new("RGB", (300, 500), "white").save(stream, "PNG")
        return stream.getvalue(), ".png"


def test_missing_and_blocked_sources_fall_back_with_correct_provenance():
    clients = {key: Reader() for key in SOURCE_LABELS}
    clients["mangadex"].error = MangaSourceUnavailable("HTTP 403")
    clients["comix"].result = "https://cdn.comix/p2.jpg"
    api = MangaPageSources(clients=clients)
    assert api.panel_url({"malId": 11}, {"old"}) == "https://cdn.comix/p2.jpg"
    assert api.last_client is clients["comix"]
    assert api.last_source == "Comix.to"
    assert api.last_source_link == clients["comix"].last_source_link
    assert api.last_titles == ["Naruto"]
    assert "HTTP 403" in api.last_errors[0]
    api.panel_url({"malId": 12})
    assert len(clients["mangadex"].calls) == 1
    assert not clients["weebcentral"].calls


def test_disabled_sources_are_not_queried_and_a_retry_can_change_reader():
    clients = {key: Reader("https://cdn/" + key) for key in SOURCE_LABELS}
    api = MangaPageSources(sources={"mangafire": True, "weebcentral": True},
                           language="en", clients=clients)
    assert api.panel_url({"malId": 11}) == "https://cdn/mangafire"
    assert api.panel_url({"malId": 11}) == "https://cdn/weebcentral"
    assert not clients["mangadex"].calls and not clients["comix"].calls


def test_old_settings_enable_new_sources_and_explicit_choices_survive_reload():
    assert all(ap.PackSettings.from_dict({}).manga_sources.values())
    settings = ap.PackSettings.from_dict({"manga_sources": {"comix": True, "unknown": True}})
    assert settings.manga_sources == dict.fromkeys(SOURCE_LABELS, False) | {"comix": True}
    assert ap.PackSettings.from_dict(settings.to_dict()).manga_sources == settings.manga_sources
    settings.manga_sources = {}
    settings.pack_manga, settings.pct_manga = True, 100
    assert any("источник страниц" in p for p in settings.validate())


def test_source_checkboxes_survive_reload(qapp):
    tab = animepack_tab.AnimePackTab()
    try:
        for key, checkbox in tab.chk_manga_sources.items():
            checkbox.setChecked(key == "weebcentral")
        settings = tab.collect()
        assert settings.manga_sources["weebcentral"]
        assert sum(settings.manga_sources.values()) == 1
        tab.apply_settings(settings.to_dict())
        assert {key: c.isChecked() for key, c in tab.chk_manga_sources.items()} == settings.manga_sources
    finally:
        tab.cleanup()


def test_generator_downloads_selected_reader_and_keeps_chapter_link(generator):
    client = Reader("https://cdn.mf/p2.jpg")
    generator.mangadex = MangaPageSources(
        sources={"mangafire": True}, clients={"mangafire": client})
    generator.s.manga_gemini_check = False
    cand = ap.SongCandidate({}, make_anime(malId=11), kind=ap.MANGA_KIND, media="manga")
    assert generator.download_manga_panel(cand)
    assert cand.source_link == client.last_source_link
    assert client.downloaded == (client.result, {"legacy": False})
    assert cand.frame_name.endswith(".png")
