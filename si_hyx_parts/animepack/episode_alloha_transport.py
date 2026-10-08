"""Stream CDN bodies outside Playwright's full-body/base64 IPC transport."""
import asyncio
from weakref import WeakKeyDictionary

import httpx

MAX_BODY = 32 * 1024 * 1024
_gates = WeakKeyDictionary()


def media_gate():
    loop = asyncio.get_running_loop()
    return _gates.setdefault(loop, asyncio.Semaphore(4))


class MediaTransport:
    def __init__(self, context, scope, *, client=None):
        self.context, self.scope = context, scope
        self.client = client or httpx.AsyncClient(
            timeout=15, follow_redirects=True,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=4))

    async def fetch(self, target, headers):
        async with media_gate():
            self.scope.check()
            self.scope.remaining -= 1
            self.scope.requests += 1
            # Snapshot live browser cookies without moving media through its driver.
            for cookie in await self.context.cookies([target]):
                self.client.cookies.set(cookie["name"], cookie["value"],
                                        domain=cookie["domain"], path=cookie.get("path", "/"))
            async with self.client.stream("GET", target, headers=headers) as response:
                if not response.is_success:
                    raise RuntimeError(f"Alloha: HTTP {response.status_code}")
                declared = response.headers.get("content-length", "")
                if declared.isdecimal() and int(declared) > MAX_BODY:
                    raise RuntimeError("Alloha: media response exceeds 32 MiB")
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                    self.scope.check(budget=False)
                    if len(body) + len(chunk) > MAX_BODY:
                        raise RuntimeError("Alloha: media response exceeds 32 MiB")
                    body.extend(chunk)
                self.scope.check(budget=False)
                return bytes(body), response.headers.get("content-type", "application/octet-stream")

    async def close(self):
        await self.client.aclose()
