"""Alloha failures seen in long pack generations: size, queue and disconnect."""
import asyncio
from http.server import BaseHTTPRequestHandler
import time
from types import SimpleNamespace

import pytest
import httpx

from si_hyx_parts.animepack.episode_alloha_proxy import Bridge, Handler, MAX_BODY
from si_hyx_parts.animepack.episode_alloha_transport import MediaTransport
from si_hyx_parts.kuhi._transport import RequestScope


@pytest.mark.parametrize("error", [BrokenPipeError, ConnectionResetError, ConnectionAbortedError])
def test_timeout_cancels_fetch_when_ffmpeg_has_already_disconnected(monkeypatch, error):
    cancelled = []

    class Future:
        def result(self, timeout):
            raise TimeoutError()

        def cancel(self):
            cancelled.append(True)

    async def fetch(target):
        return b"", "text/plain"

    def submit(coro, loop):
        coro.close()
        return Future()

    def disconnected(*args, **kwargs):
        raise error("FFmpeg left")

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", submit)
    monkeypatch.setattr(BaseHTTPRequestHandler, "send_error", disconnected)
    handler = Handler.__new__(Handler)
    handler.path = "/?url=https%3A%2F%2Fcdn%2Fmedia"
    handler.server = SimpleNamespace(bridge=SimpleNamespace(
        urls={"https://cdn/media"}, fetch=fetch, loop=None))
    handler.do_GET()
    assert cancelled == [True]
    assert handler.close_connection


def test_declared_oversized_body_is_disposed_without_transfer_over_browser_ipc():
    disposed = []
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError("Must reject before loading the body")
            yield b""
        async def aclose(self):
            disposed.append(True)
    async def cookies(urls):
        return []
    async def run():
        scope = RequestScope(lambda: False, time.monotonic() + 10)
        context = SimpleNamespace(cookies=cookies)
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(
            200, headers={"content-length": str(MAX_BODY + 1)}, stream=Stream())))
        bridge = Bridge(context, scope, "https://player/",
                        transport=MediaTransport(context, scope, client=client))
        try:
            with pytest.raises(RuntimeError, match="exceeds 32 MiB"):
                await bridge.fetch("https://cdn/media")
        finally:
            await bridge.close()

    asyncio.run(run())
    assert disposed == [True]


@pytest.mark.parametrize("reason", ["stop", "deadline", "budget"])
def test_queued_fetch_rechecks_scope_before_starting_network(reason):
    async def get(*args, **kwargs):
        raise AssertionError("Expired queued request must not contact CDN")

    async def run():
        stopped = [False]
        scope = RequestScope(lambda: stopped[0], time.monotonic() + 10)
        bridge = Bridge(SimpleNamespace(request=SimpleNamespace(get=get)), scope, "https://player/")
        bridge.gate = asyncio.Semaphore(0)
        task = asyncio.create_task(bridge.fetch("https://cdn/media"))
        try:
            await asyncio.sleep(0)
            if reason == "stop":
                stopped[0] = True
            elif reason == "deadline":
                scope.deadline = time.monotonic() - 1
            else:
                scope.remaining = 0
            bridge.gate.release()
            exception = RuntimeError if reason == "budget" else asyncio.CancelledError
            with pytest.raises(exception):
                await task
            assert scope.requests == 0
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await bridge.close()

    asyncio.run(run())
