"""All upstream fallbacks, provider timing metadata and bounded transport."""
import asyncio
import time
from types import SimpleNamespace

import httpx
import pytest

import animepack as api
from si_hyx_parts.kuhi import _race, _transport, aniwaves, chapters, legacy
from si_hyx_parts.animepack import episode_generation as generation
from si_hyx_parts.animepack import episode_subtitles as subtitles
from test_animepack_episode import generator, stream
from test_animepack_new_kinds import make_anime


def test_vtt_chapters_exclude_op_and_ed_but_not_the_story():
    text = ("WEBVTT\n\n1\n00:00:00.000 --> 00:01:30.500\nOpening\n\n"
            "2\n00:01:30.500 --> 21:00.000\nEpisode\n\n"
            "3\n21:00.000 --> 22:30.000\nED\n")
    assert chapters.parse(text) == {"intro": {"start": 0, "end": 90.5},
                                    "outro": {"start": 1260, "end": 1350}}


def test_aniwaves_preserves_skip_times_and_extractor_headers(monkeypatch):
    async def series(*args):
        return {"slug": "title"}

    async def episodes(*args):
        return [{"number": 1, "sourceNumber": 1, "hasSub": True}]

    async def servers(*args):
        return [{"audio": "sub", "server": "server", "linkId": "link"}]

    async def source(*args):
        return {"url": "https://server/embed", "skip_data": {"intro": [10, 100], "outro": [1300, 1390]}}

    async def resolve(*args):
        return [{"url": "https://cdn/title.m3u8", "headers": {"Origin": "https://required"}}]

    monkeypatch.setattr(aniwaves, "resolve_series", series)
    monkeypatch.setattr(aniwaves, "_fetch_episodes", episodes)
    monkeypatch.setattr(aniwaves, "_align_episodes", lambda rows, *a: rows)
    monkeypatch.setattr(aniwaves, "_fetch_servers", servers)
    monkeypatch.setattr(aniwaves, "_fetch_source", source)
    monkeypatch.setattr(aniwaves, "_resolve_source", resolve)
    rows = asyncio.run(aniwaves.watch(1, "sub", 1, {"media": {"episodes": 1}}))
    assert rows[0]["headers"] == {"Origin": "https://required"}
    assert rows[0]["intro"] == {"start": 10, "end": 100}
    assert rows[0]["outro"] == {"start": 1300, "end": 1390}


def test_legacy_races_all_sub_providers_and_drops_dub(monkeypatch):
    calls = []

    async def pipe(path, query):
        calls.append(query)
        return {"sources": [{"url": "https://cdn/clip.m3u8"},
                             {"url": "https://cdn/dub.m3u8", "audio": "dub"}],
                "headers": {"Referer": "https://source/"},
                "intro": {"start": 0, "end": 90}}

    monkeypatch.setattr(legacy, "pipe", pipe)
    catalog = {"providers": {name: {"episodes": {
        "sub": [{"number": 7, "id": name + ":7"}],
        "dub": [{"number": 7, "id": name + ":dub:7"}]}}
        for name in legacy.RANKING}}
    sources = asyncio.run(legacy.streams(1, 7, catalog))
    assert len(sources) == len(legacy.RANKING)
    assert {s["provider"] for s in sources} == {"miruro/" + n for n in legacy.RANKING}
    assert all(q["category"] == "sub" for q in calls)
    assert all(s["audio"] == "sub" and s["intro"]["end"] == 90 for s in sources)
    assert all(s["headers"]["Referer"] == "https://source/" for s in sources)


def test_http_body_limit_aborts_large_response(monkeypatch):
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=b"x" * 65))
    monkeypatch.setattr(_transport.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=transport, **kw))
    monkeypatch.setattr(_transport, "MAX_RESPONSE_BYTES", 64)
    monkeypatch.setattr(_transport, "_gate", None)
    monkeypatch.setattr(_transport, "_host_locks", {})
    monkeypatch.setattr(_transport, "_next_request", {})
    scope = _transport.RequestScope(lambda: False, time.monotonic() + 5)

    async def request():
        try:
            async with _transport.AsyncClient() as client:
                await client.get("https://test.invalid/")
        finally:
            await scope.close()

    with pytest.raises(RuntimeError, match="ответ превысил"):
        asyncio.run(_transport.scoped(request(), scope))
    assert scope.requests == 1 and scope.client is None


def test_signed_watch_cache_is_bounded_and_expires(monkeypatch):
    async def watch(*args):
        return [{"url": "https://cdn/new.m3u8", "audio": "sub"}]

    now = time.time()
    expired = ("site", 1, 1, "sub")
    monkeypatch.setattr(_race, "WATCH_CACHE_LIMIT", 2)
    monkeypatch.setattr(_race, "_watch_cache", {
        expired: (now - 1, [{"url": "expired"}]),
        ("site", 2, 1, "sub"): (now + 60, [{}])})
    result = asyncio.run(_race._watch_one(SimpleNamespace(watch=watch), "site", 1, 1, "sub", {}))
    assert result[1][0]["url"] == "https://cdn/new.m3u8"
    asyncio.run(_race._watch_one(SimpleNamespace(watch=watch), "site", 3, 1, "sub", {}))
    assert len(_race._watch_cache) == 2


def test_native_failure_uses_legacy_but_missing_ru_rejects_question(generator, monkeypatch):
    gen = generator
    gen.s.episode_ru_subtitles = True
    gen.kuhi.close()
    calls = []
    catalog = {"providers": {"miruro/bee": {"episodes": {"sub": [{"number": 9}]}}}}
    gen.kuhi = SimpleNamespace(episodes=lambda *a: {},
        legacy_episodes=lambda *a: catalog,
        legacy_streams=lambda *a: calls.append("legacy") or [stream("miruro/bee", "sub")],
        close=lambda: None)
    monkeypatch.setattr(generation, "cut", lambda *a, **kw: 320)

    def failed_subtitles(*args):
        raise RuntimeError("Optional subtitle service failed")

    monkeypatch.setattr(subtitles, "find", failed_subtitles)
    candidate = api.SongCandidate({}, make_anime(), kind=api.EPISODE_KIND)
    assert not gen.download_episode(candidate)
    assert calls == ["legacy"]
    assert not candidate.episode_clip
    assert not candidate.has_video
