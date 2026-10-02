# -*- coding: utf-8 -*-
"""AniList: optional frames fail quickly; required lists retry explicitly."""
import threading

import pytest
import requests

import animepack_api as ap


def client(session):
    api = ap.AniListApi(session)
    api.limiter.acquire = lambda: None
    return api


def test_anilist_adapter_does_not_multiply_explicit_retries():
    session = ap.make_session()
    try:
        ap.AniListApi(session)
        retry = session.get_adapter(ap.ANILIST_BASE + "/").max_retries
        assert retry.total == 0
        assert session.get_adapter("https://anisongdb.com/api").max_retries.read == 4
    finally:
        session.close()


def test_frame_timeout_cools_down_without_blocking_other_titles(
        fake_session, fake_response):
    calls = []

    def timeout(url, **kwargs):
        calls.append(kwargs)
        raise requests.ReadTimeout("slow server")

    session = fake_session([(ap.ANILIST_BASE, timeout)])
    api = client(session)
    log = []
    api._log = log.append
    assert api.frames(1) == []
    assert api.frames(2) == []
    assert len(calls) == 1
    assert calls[0]["timeout"] == (5, 15)
    assert len(log) == 1 and "остальных источников" in log[0]

    session.routes = [(ap.ANILIST_BASE, fake_response(json_data={"data": {
        "Media": {"bannerImage": "https://cdn/banner.jpg",
                  "streamingEpisodes": [None, {"thumbnail": "https://cdn/1.jpg"}]}
    }}))]
    api._frames_retry_at = 0
    assert api.frames(3) == ["https://cdn/1.jpg", "https://cdn/banner.jpg"]


def test_parallel_frames_share_one_failed_probe(fake_session):
    started, release = threading.Event(), threading.Event()

    def timeout(url, **kwargs):
        started.set()
        assert release.wait(3)
        raise requests.ReadTimeout("slow server")

    session = fake_session([(ap.ANILIST_BASE, timeout)])
    api = client(session)
    results = []
    first = threading.Thread(target=lambda: results.append(api.frames(1)))
    second = threading.Thread(target=lambda: results.append(api.frames(2)))
    first.start()
    assert started.wait(3)
    second.start()
    release.set()
    first.join(3)
    second.join(3)
    assert not first.is_alive() and not second.is_alive()
    assert results == [[], []] and len(session.calls) == 1


def test_user_list_retries_timeout_but_is_not_hidden_by_frame_cooldown(
        fake_session, fake_response):
    responses = [requests.ReadTimeout("slow"), fake_response(json_data={"data": {
        "MediaListCollection": {"lists": [{"entries": [
            {"status": "COMPLETED", "media": {"idMal": 7}}]}]}}})]

    def reply(url, **kwargs):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    session = fake_session([(ap.ANILIST_BASE, reply)])
    api = client(session)
    api._frames_retry_at = float("inf")
    pauses = []
    api.limiter.penalize = pauses.append
    assert api.user_anime_ids("user", ["completed"]) == [7]
    assert len(session.calls) == 2 and pauses == [1]
    assert all(call[2]["timeout"] == (10, 45) for call in session.calls)


def test_exhausted_user_timeout_remains_a_visible_error(fake_session):
    def timeout(url, **kwargs):
        raise requests.ReadTimeout("slow")

    session = fake_session([(ap.ANILIST_BASE, timeout)])
    api = client(session)
    api.limiter.penalize = lambda seconds: None
    with pytest.raises(ap.AnimePackApiError, match="не ответил вовремя"):
        api.user_anime_ids("user", ["completed"])
    assert len(session.calls) == 2


def test_rate_limit_retry_respects_server_delay(fake_session, fake_response):
    limited = requests.Response()
    limited.status_code = 429
    limited.headers["Retry-After"] = "7"
    replies = [limited, fake_response(json_data={"data": {"ok": True}})]
    session = fake_session([(ap.ANILIST_BASE, lambda url, **kw: replies.pop(0))])
    api = client(session)
    pauses = []
    api.limiter.penalize = pauses.append
    assert api._graphql("query { ok }", {}) == {"ok": True}
    assert pauses == [7] and len(session.calls) == 2
