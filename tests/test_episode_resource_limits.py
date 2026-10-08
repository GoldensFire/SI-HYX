"""Streaming caps and browser permits work across separate player sessions."""
import asyncio
import time
from types import SimpleNamespace

import httpx
import pytest

from si_hyx_parts.animepack import episode_alloha_transport as transport
from si_hyx_parts.animepack.episode_browser_budget import acquire
from si_hyx_parts.animepack.episode_ru_alloha import Session
from si_hyx_parts.animepack.episode_alloha_proxy import Bridge
from si_hyx_parts.kuhi._transport import RequestScope


async def cookies(urls):
    return []


def test_stream_cap_without_content_length_closes_response(monkeypatch):
    monkeypatch.setattr(transport, "MAX_BODY", 65536)
    closed, reads = [], []
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(5):
                reads.append(1)
                yield b"x" * 65536
        async def aclose(self):
            closed.append(1)
    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, stream=Stream())))
        scope = RequestScope(lambda: False, time.monotonic() + 10)
        media = transport.MediaTransport(SimpleNamespace(cookies=cookies), scope, client=client)
        try:
            with pytest.raises(RuntimeError, match="exceeds"):
                await media.fetch("https://cdn/media", {})
        finally:
            await media.close()
    asyncio.run(run())
    assert closed == [1] and len(reads) == 2


def test_media_concurrency_is_shared_by_all_players():
    active, peak = [0], [0]
    async def get(request):
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        await asyncio.sleep(.01)
        active[0] -= 1
        return httpx.Response(200, content=b"segment")
    async def run():
        media = [transport.MediaTransport(SimpleNamespace(cookies=cookies),
            RequestScope(lambda: False, time.monotonic() + 10),
            client=httpx.AsyncClient(transport=httpx.MockTransport(get))) for _ in range(8)]
        try:
            await asyncio.gather(*(item.fetch("https://cdn/media", {}) for item in media))
        finally:
            await asyncio.gather(*(item.close() for item in media))
    asyncio.run(run())
    assert peak[0] == 4


def test_browser_queue_cancellation_does_not_leak_permit():
    async def run():
        scope = RequestScope(lambda: False, time.monotonic() + 10)
        first, second = await acquire(scope), await acquire(scope)
        expired = RequestScope(lambda: True, time.monotonic() + 10)
        with pytest.raises(asyncio.CancelledError):
            await acquire(expired)
        queued = asyncio.create_task(acquire(scope))
        await asyncio.sleep(0)
        assert not queued.done()
        first.release()
        third = await queued
        third.release()
        second.release()
    asyncio.run(run())


def test_session_releases_permit_even_when_browser_close_fails():
    calls = []
    async def bridge_close():
        calls.append("bridge")
    async def browser_close():
        calls.append("browser")
        raise RuntimeError("crashed")
    async def stop():
        calls.append("runtime")
    session = Session(SimpleNamespace(stop=stop), SimpleNamespace(close=browser_close),
        SimpleNamespace(close=bridge_close), SimpleNamespace(release=lambda: calls.append("permit")))
    async def run():
        with pytest.raises(RuntimeError):
            await session.close()
        await session.close()
    asyncio.run(run())
    assert calls == ["bridge", "browser", "runtime", "permit"]


def test_bridge_close_cancels_queued_media():
    async def run():
        scope = RequestScope(lambda: False, time.monotonic() + 10)
        bridge = Bridge(SimpleNamespace(cookies=cookies), scope, "https://player/")
        bridge.gate = asyncio.Semaphore(0)
        queued = asyncio.create_task(bridge.fetch("https://cdn/media"))
        await asyncio.sleep(0)
        await bridge.close()
        assert queued.cancelled() and not bridge.pending
    asyncio.run(run())
