# -*- coding: utf-8 -*-
"""Unofficial reader protocols, title identity and page selection."""
import base64
import json
import random

import pytest

from animepack_api import MangaFireApi, ComixApi, WeebCentralApi
from si_hyx_parts.animepack_api.manga_reader_base import MangaSourceUnavailable
from si_hyx_parts.animepack_api.manga_request_signing import (
    COMIX, MANGAFIRE, canonical_params, decode_comix, sign)


CARD = {"malId": 11, "name": "Naruto", "english": "Naruto"}


def _api(cls, session):
    client = cls(session, language="en", rng=random.Random(3))
    client.limiter.acquire = lambda: None
    return client


def _encrypted(data):
    token = sign(json.dumps(data, separators=(",", ":")), [], COMIX)
    return {"e": token}


def test_signing_matches_the_current_web_reader_vectors():
    entries = canonical_params({"limit": 5, "keyword": "Naruto"})
    assert sign("/manga", entries, COMIX) == "IZ-P1pUtzgErcs07iuxJt6jmScuSnT4cVb9QZVE"
    assert decode_comix(_encrypted({"result": {"items": [1, 2]}})["e"]) == {
        "result": {"items": [1, 2]}}
    for stages in (COMIX, MANGAFIRE):
        for table, key, _ in stages:
            assert set(base64.b64decode(table)) == set(range(256))
            assert base64.b64decode(key)
    assert canonical_params({"b[]": ["en", "ja"], "a": " 日本語 "}) == [
        ("a", "日本語"), ("b[0]", "en"), ("b[1]", "ja")]


def test_mangafire_signed_search_detail_and_page_cache(fake_session, fake_response):
    title = {"hid": "n", "title": "Naruto", "url": "/title/n-naruto"}
    session = fake_session([
        ("/api/chapters/7", fake_response(json_data={"data": {"pages": [
            {"url": f"https://cdn.mf/p{i}.jpg"} for i in range(16)]}})),
        ("/api/titles/n/chapters", fake_response(json_data={"items": [
            {"id": 7, "number": 12, "language": "en"}]})),
        ("/api/titles/n", fake_response(json_data={"data": dict(
            title, malId="11", contentRating="safe")})),
        ("/api/titles", fake_response(json_data={"items": [title]})),
    ])
    api = _api(MangaFireApi, session)
    first = api.panel_url(CARD)
    assert first in [f"https://cdn.mf/p{i}.jpg" for i in range(5, 11)]
    assert api.last_source_link == "https://mangafire.to/title/n-naruto/7-chapter-12-en"
    second = api.panel_url(CARD, {first})
    assert second and second != first
    assert len(session.calls) == 4
    for _, url, kwargs in session.calls:
        params = kwargs["params"]
        assert params[-1] == ("vrf", sign(url.split("/api", 1)[1], params[:-1], MANGAFIRE))


@pytest.mark.parametrize("detail", [
    {"malId": "99", "contentRating": "safe"},
    {"malId": "11", "contentRating": "pornographic"},
    {"malId": "11", "contentRating": "erotica"},
])
def test_matching_title_does_not_override_identity_or_rating(
        detail, fake_session, fake_response):
    row = {"hid": "n", "title": "Naruto"}
    session = fake_session([
        ("/api/titles/n", fake_response(json_data={"data": dict(row, **detail)})),
        ("/api/titles", fake_response(json_data={"items": [row]}))])
    api = _api(MangaFireApi, session)
    assert api.panel_url(CARD) == ""
    assert not any("/chapters" in url for _, url, _ in session.calls)
    api.allow_erotica = True
    assert api._allowed({"rating": "erotica"})
    assert not api._allowed({"rating": "pornographic"})


def test_comix_encrypted_responses_and_scrambled_page_flags(fake_session, fake_response):
    row = {"hid": "n", "title": "Naruto", "links": {"mal": "11"}}
    session = fake_session([
        ("/api/v1/chapters/7", fake_response(json_data=_encrypted({"result": {
            "pages": {"baseUrl": "https://cdn.cx", "items": [
                {"url": f"p{i}.webp", "s": int(i == 2)} for i in range(6)]}}}))),
        ("/api/v1/manga/n/chapters", fake_response(json_data=_encrypted({"result": {
            "items": [{"id": 7, "number": 5,
                       "url": "/title/n-naruto/7-chapter-5"}]}}))),
        ("/api/v1/manga/n", fake_response(json_data={"result": row})),
        ("/api/v1/manga", fake_response(json_data={"result": {"items": [row]}})),
    ])
    api = _api(ComixApi, session)
    assert api.panel_url(CARD).startswith("https://cdn.cx/")
    assert api.last_source_link == "https://comix.to/title/n-naruto/7-chapter-5"
    pages = api.pages({"id": "7"})
    assert pages[2]["url"] == "https://cdn.cx/p2.webp?v3"
    assert pages[3]["legacy"]
    assert not pages[2]["legacy"]


def test_english_only_readers_do_not_override_explicit_language(fake_session):
    for cls in (ComixApi, WeebCentralApi):
        session = fake_session()
        api = cls(session, language="ru")
        assert api.panel_url(CARD) == ""
        assert not session.calls


def test_mangafire_tries_ukrainian_when_russian_and_english_pages_are_empty(
        fake_session, fake_response):
    title = {"hid": "n", "title": "Naruto", "malId": "11"}

    def chapters(url, **kwargs):
        language = dict(kwargs["params"])["language"]
        return fake_response(json_data={"items": [{
            "id": 2 if language == "uk" else 1, "language": language, "number": 1}]})

    session = fake_session([
        ("/api/chapters/1", fake_response(json_data={"data": {"pages": []}})),
        ("/api/chapters/2", fake_response(json_data={"data": {"pages": [
            {"url": f"https://cdn.mf/uk{i}.jpg"} for i in range(6)]}})),
        ("/api/titles/n/chapters", chapters),
        ("/api/titles/n", fake_response(json_data={"data": title})),
        ("/api/titles", fake_response(json_data={"items": [title]})),
    ])
    api = _api(MangaFireApi, session)
    api.language = ""
    assert "/uk" in api.panel_url(CARD)
    assert api.last_source_link.endswith("-uk")


def test_weebcentral_fragments_match_tracker_and_only_reader_images(
        fake_session, fake_response):
    session = fake_session([
        ("/search/data", fake_response(text='''<article><section>
          <a href="/series/abc/Naruto"><div>Naruto</div></a>
          </section></article>''')),
        ("/series/abc/full-chapter-list", fake_response(text='''<div x-data="{}">
          <a href="/chapters/ch1"><span>Chapter 1</span></a></div>''')),
        ("/series/abc/Naruto", fake_response(text='''<h1>Naruto</h1>
          <a href="https://myanimelist.net/manga/11/Naruto">MAL</a>
          <li><strong>Associated Name(s)</strong><ul><li>ナルト</li></ul></li>''')),
        ("/chapters/ch1/images", fake_response(text='''<section x-data="scroll">
          <img src="https://cdn.wc/p0.png"><img src="https://cdn.wc/p1.png">
          <img src="https://cdn.wc/p2.png"><img src="https://cdn.wc/p3.png">
          </section><img src="https://cdn.wc/ad.png">''')),
    ])
    api = _api(WeebCentralApi, session)
    assert api.panel_url(CARD) in ("https://cdn.wc/p1.png", "https://cdn.wc/p2.png")
    assert api.last_source_link == "https://weebcentral.com/chapters/ch1"
    assert "ナルト" in api.last_titles
    assert session.calls[-1][2]["params"]["reading_style"] == "long_strip"


def test_blocked_reader_reports_unavailability(fake_session, fake_response):
    client = _api(WeebCentralApi, fake_session(default=fake_response(status_code=403)))
    with pytest.raises(MangaSourceUnavailable):
        client.panel_url(CARD)
