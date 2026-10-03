"""Read Alloha's bnsi response in installed Edge/Chrome and preserve its session."""
from __future__ import annotations

import asyncio
from html import escape
import re
import time
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from .episode_alloha_proxy import Bridge
from .episode_ru_catalog import absolute, stream_from, subtitle_release


def russian_tracks(data, base):
    tracks = []
    for row in data.get("tracks") or []:
        language = str(row.get("language") or row.get("srclang") or "").casefold()
        label = str(row.get("label") or "").casefold()
        if row.get("kind") in ("captions", "subtitles") and (
                language in ("ru", "rus") or "русск" in label or re.search(r"\brussian\b", label)):
            target = absolute(row.get("src"), base)
            if target:
                tracks.append({"url": target, "name": urlsplit(target).path.rsplit("/", 1)[-1]})
    return tracks


def sources(data, row):
    tracks = russian_tracks(data, row["embed"])
    result = []
    for item in data.get("hlsSource") or []:
        label = str(item.get("label") or "")
        # translation identifies the selected release, audioId identifies its audio track.
        # Their numbers are unrelated; Japanese audio commonly has audioId=2.
        if not subtitle_release(label) and "japanese" not in label.casefold():
            continue
        if not tracks and not subtitle_release(label):
            continue
        for _quality, value in (item.get("quality") or {}).items():
            for url in str(value or "").split(" or "):
                target = absolute(url.strip(), row["embed"])
                if target:
                    result.append(stream_from(row, target, "hls", subtitles=tracks,
                                              hardsub=not bool(tracks), referer=row["embed"],
                                              audio_language="ja" if "japanese" in label.casefold() else ""))
    return result


class Session:
    def __init__(self, runtime, browser, bridge):
        self.runtime, self.browser, self.bridge = runtime, browser, bridge

    async def close(self):
        try:
            await self.bridge.close()
        finally:
            try:
                await self.browser.close()
            finally:
                await self.runtime.stop()


async def open_streams(row, scope, resources):
    # Playwright's driver is packaged; the user's installed browser supplies Chromium.
    from playwright.async_api import async_playwright
    runtime = await async_playwright().start()
    browser, bridge = None, None
    try:
        for channel in ("msedge", "chrome"):
            try:
                browser = await runtime.chromium.launch(channel=channel, headless=True)
                break
            except Exception:
                scope.check(budget=False)
        if browser is None:
            raise RuntimeError("Alloha: Edge или Chrome не установлен")
        context = await browser.new_context()
        page = await context.new_page()
        bridge = Bridge(context, scope, row["embed"])
        found = asyncio.Event()
        result, pending = [], set()

        async def response_received(response):
            if "/bnsi/" not in response.url or response.status != 200:
                return
            if int(response.headers.get("content-length") or 0) > 4 * 1024 * 1024:
                return
            payload = await response.body()
            if len(payload) > 4 * 1024 * 1024:
                return
            import json
            data = json.loads(payload)
            result.extend(sources(data, row))
            if result:
                found.set()

        async def request_sent(request):
            # The latest CDN request carries renewed controls. Don't replay borth nonce.
            if "/bnsi/" in request.url or ".m3u8" in request.url:
                bridge.headers.update(await request.all_headers())

        def schedule(coro):
            task = asyncio.create_task(coro)
            pending.add(task)
            def done(completed):
                pending.discard(completed)
                if not completed.cancelled():
                    completed.exception()  # Observe failures from closed pages and malformed data.
            task.add_done_callback(done)

        page.on("response", lambda response: schedule(response_received(response)))
        page.on("request", lambda request: schedule(request_sent(request)))
        # Alloha deliberately rejects top-level navigation, even with a Referer header.
        # Use a minimal parent at the actual site origin, without that site's ad scripts.
        parent = row["referer"]
        parts = urlsplit(row["embed"])
        params = parse_qs(parts.query)
        params["autoplay"] = ["1"]  # Requesting playback initializes Alloha's media session.
        embed = urlunsplit(parts._replace(query=urlencode(params, doseq=True)))
        async def parent_page(route):
            await route.fulfill(content_type="text/html", body=(
                '<!doctype html><style>html,body{margin:0;height:100%}iframe{width:100%;height:100%;border:0}</style>'
                '<iframe id="sihyx-player" allow="autoplay; encrypted-media" src="'
                + escape(embed, quote=True) + '"></iframe>'))
        await page.route(lambda url: url == parent, parent_page)
        await page.goto(parent, wait_until="domcontentloaded", timeout=25000)
        body = await page.frame_locator("#sihyx-player").locator("body").inner_text(timeout=10000)
        if re.search(r"контент.*(?:не найден|недоступен)", body, re.I):
            raise RuntimeError("Alloha: контент недоступен в текущем регионе или удалён")
        remaining = min(25, max(0.1, scope.deadline - time.monotonic()))
        await asyncio.wait_for(found.wait(), remaining)
        scope.check(budget=False)
        # Wait for browser request headers before FFmpeg begins its own requests.
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for stream in result:
            stream["url"] = bridge.url(stream["url"])
            stream["headers"] = {}
            stream["subtitles"] = [{**track, "url": bridge.url(track["url"])}
                                    for track in stream["subtitles"]]
        resources.append(Session(runtime, browser, bridge))
        return result
    except BaseException:
        if bridge is not None:
            await bridge.close()
        if browser is not None:
            await browser.close()
        await runtime.stop()
        raise
