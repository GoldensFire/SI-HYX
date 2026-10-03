"""Short-lived HLS bridge: keep Alloha's browser session alive during FFmpeg seeks."""
from __future__ import annotations

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
import threading
from urllib.parse import parse_qs, quote, urljoin, urlsplit

MAX_BODY = 32 * 1024 * 1024
DROP_HEADERS = {"host", "connection", "content-length", "transfer-encoding",
                "accept-encoding", "borth", "range", "cookie"}


def rewrite_hls(text, base, make_url):
    lines = []
    for line in text.splitlines():
        if line.startswith("#"):
            line = re.sub(r'URI="([^"]+)"', lambda m: 'URI="' + make_url(urljoin(base, m[1])) + '"', line)
        elif line.strip():
            line = make_url(urljoin(base, line.strip()))
        lines.append(line)
    return "\n".join(lines) + "\n"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        bridge = self.server.bridge
        target = (parse_qs(urlsplit(self.path).query).get("url") or [""])[0]
        if target not in bridge.urls:
            self.send_error(404)
            return
        future = asyncio.run_coroutine_threadsafe(bridge.fetch(target), bridge.loop)
        try:
            body, content_type = future.result(timeout=20)
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            future.cancel()
            self.send_error(502)


class Bridge:
    def __init__(self, context, scope, referer):
        self.context, self.scope, self.referer = context, scope, referer
        self.loop = asyncio.get_running_loop()
        self.headers, self.urls = {}, set()
        self.gate = asyncio.Semaphore(4)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.bridge = self
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name="Alloha HLS")
        self.thread.start()

    def url(self, target):
        if urlsplit(target).scheme not in ("http", "https"):
            raise ValueError("Alloha: unsupported media URL")
        self.urls.add(target)
        return f"http://127.0.0.1:{self.server.server_port}/?url=" + quote(target, safe="")

    async def fetch(self, target):
        self.scope.check()
        async with self.gate:
            self.scope.remaining -= 1
            self.scope.requests += 1
            headers = {k: v for k, v in self.headers.items() if k.casefold() not in DROP_HEADERS}
            headers.setdefault("referer", self.referer)
            response = await self.context.request.get(target, headers=headers, timeout=15000)
            try:
                if not response.ok:
                    raise RuntimeError(f"Alloha: HTTP {response.status}")
                body = await response.body()
                if len(body) > MAX_BODY:
                    raise RuntimeError("Alloha: media response exceeds 32 MiB")
                self.scope.check(budget=False)
                content_type = response.headers.get("content-type", "application/octet-stream")
                if body.lstrip().startswith(b"#EXTM3U"):
                    body = rewrite_hls(body.decode("utf-8-sig"), target, self.url).encode("utf-8")
                    content_type = "application/vnd.apple.mpegurl"
                return body, content_type
            finally:
                await response.dispose()

    async def close(self):
        await asyncio.to_thread(self.server.shutdown)
        self.server.server_close()
        await asyncio.to_thread(self.thread.join, 2)
