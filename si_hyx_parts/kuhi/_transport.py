"""Bounded, cancellable HTTP transport shared by every native Kuhi provider."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import time
from urllib.parse import urlsplit

import httpx

MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_CONNECTIONS = 8
_scope = ContextVar("kuhi_request_scope", default=None)
_gate = None
_next_request = {}
_host_locks = {}


@asynccontextmanager
async def connection(host, scope):
    """Rate-limit request starts, without serializing slow responses per host."""
    global _gate
    if _gate is None:
        _gate = asyncio.Semaphore(MAX_CONNECTIONS)
    host_lock = _host_locks.setdefault(host, asyncio.Lock())
    while True:
        if scope:
            scope.check()
        await _gate.acquire()
        acquired = False
        try:
            async with host_lock:
                now = time.monotonic()
                pause = max(0, _next_request.get(host, now) - now)
                if not pause:
                    if scope:
                        scope.check()
                    _next_request[host] = now + (1.0 if host == "graphql.anilist.co" else 1 / 3)
                    acquired = True
            if acquired:
                yield
                return
        finally:
            _gate.release()
        # Throttled hosts occupy neither a connection nor another host's slot.
        await asyncio.sleep(min(pause, 0.2))


@dataclass
class RequestScope:
    stopped: object
    deadline: float
    remaining: int = 300
    requests: int = 0
    errors: dict = field(default_factory=dict)
    client: object = field(default=None, repr=False)

    async def close(self):
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    def check(self, budget=True):
        if self.stopped() or time.monotonic() >= self.deadline:
            raise asyncio.CancelledError()
        if budget and self.remaining <= 0:
            raise RuntimeError("Kuhi: исчерпан сетевой бюджет тайтла")


async def scoped(coro, scope):
    token = _scope.set(scope)
    try:
        try:
            scope.check()
        except BaseException:
            coro.close()
            raise
        return await coro
    finally:
        _scope.reset(token)


class AsyncClient:
    """httpx-compatible subset used by Kuhi, with no unbounded response reads."""
    def __init__(self, timeout=20.0, **kwargs):
        self.timeout = min(20.0, float(timeout))
        self.options = kwargs
        self.shared = False
        self.client = None

    async def __aenter__(self):
        scope = _scope.get()
        if scope is not None:
            if scope.client is None:
                scope.client = httpx.AsyncClient(timeout=20, follow_redirects=True,
                    limits=httpx.Limits(max_connections=MAX_CONNECTIONS, max_keepalive_connections=MAX_CONNECTIONS))
            self.client = scope.client
            self.shared = True
        else:
            self.client = httpx.AsyncClient(timeout=self.timeout, **self.options)
            await self.client.__aenter__()
        return self

    async def __aexit__(self, *args):
        if not self.shared:
            return await self.client.__aexit__(*args)
        return False

    async def get(self, url, **kwargs):
        return await self.request("GET", url, **kwargs)

    async def post(self, url, **kwargs):
        return await self.request("POST", url, **kwargs)

    async def request(self, method, url, **kwargs):
        scope = _scope.get()
        kwargs.setdefault("timeout", self.timeout)
        kwargs.setdefault("follow_redirects", self.options.get("follow_redirects", False))
        if scope:
            scope.check()
        host = urlsplit(str(url)).hostname or ""
        async with connection(host, scope):
            if scope:
                scope.check()
                scope.remaining -= 1
                scope.requests += 1
            headers_only = kwargs.pop("headers_only", False)
            limit = kwargs.pop("max_bytes", MAX_RESPONSE_BYTES)
            async with self.client.stream(method, url, **kwargs) as response:
                chunks, size = [], 0
                if not headers_only:
                    async for chunk in response.aiter_bytes():
                        if scope:
                            scope.check(budget=False)
                        size += len(chunk)
                        if size > limit:
                            raise RuntimeError(f"Kuhi: ответ превысил {limit // (1024 * 1024)} МиБ")
                        chunks.append(chunk)
                if response.status_code == 429:
                    try:
                        pause = min(60, max(1, float(response.headers.get("Retry-After", 5))))
                    except ValueError:
                        pause = 5
                    _next_request[host] = max(_next_request.get(host, 0), time.monotonic() + pause)
                headers = [(k, v) for k, v in response.headers.multi_items()
                           if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")]
                return httpx.Response(response.status_code, headers=headers,
                                      content=b"".join(chunks), request=response.request)
