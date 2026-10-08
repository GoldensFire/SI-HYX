"""Short-lived HLS bridge: keep Alloha's browser session alive during FFmpeg seeks."""
from __future__ import annotations

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
import threading
from urllib.parse import parse_qs, quote, urljoin, urlsplit
from .episode_alloha_transport import MAX_BODY as MAX_BODY, MediaTransport

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

    def send_error(self, *args, **kwargs):
        try:
            super().send_error(*args, **kwargs)
        except ConnectionError:
            # FFmpeg may abandon a slow request before its error response arrives.
            self.close_connection = True

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
        except ConnectionError:
            future.cancel()
            self.close_connection = True
        except Exception:
            future.cancel()
            self.send_error(502)


class Bridge:
    def __init__(self, context, scope, referer, *, transport=None):
        self.context, self.scope, self.referer = context, scope, referer
        self.loop = asyncio.get_running_loop()
        self.headers, self.urls = {}, set()
        self.gate = asyncio.Semaphore(4)
        self.transport = transport or MediaTransport(context, scope)
        self.pending = set()
        self.closed = False
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.server.bridge = self
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name="Alloha HLS")
        self.thread.start()

    def url(self, target):
        if urlsplit(target).scheme not in ("http", "https"):
            raise ValueError("Alloha: unsupported media URL")
        self.urls.add(target)
        return f"http://127.0.0.1:{self.server.server_port}/?url=" + quote(target, safe="")

    async def fetch(self, target):
        if self.closed:
            raise RuntimeError("Alloha: bridge closed")
        task = asyncio.current_task()
        self.pending.add(task)
        try:
            self.scope.check()
            async with self.gate:
                self.scope.check()
                if self.closed:
                    raise RuntimeError("Alloha: bridge closed")
                headers = {k: v for k, v in self.headers.items() if k.casefold() not in DROP_HEADERS}
                headers.setdefault("referer", self.referer)
                body, content_type = await self.transport.fetch(target, headers)
                if body.lstrip().startswith(b"#EXTM3U"):
                    body = rewrite_hls(body.decode("utf-8-sig"), target, self.url).encode("utf-8")
                    content_type = "application/vnd.apple.mpegurl"
                return body, content_type
        finally:
            self.pending.discard(task)

    async def close(self):
        if self.closed:
            return
        self.closed = True
        pending = list(self.pending)
        for task in pending:
            task.cancel()
        try:
            await asyncio.gather(*pending, return_exceptions=True)
        finally:
            try:
                await asyncio.to_thread(self.server.shutdown)
            finally:
                self.server.server_close()
                await self.transport.close()
                await asyncio.to_thread(self.thread.join, 2)
