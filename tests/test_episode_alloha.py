"""Alloha selection and live-session proxy correctness without external services."""
import asyncio
import time
import httpx
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from si_hyx_parts.animepack.episode_alloha_proxy import Bridge, rewrite_hls
from si_hyx_parts.animepack.episode_alloha_transport import MediaTransport
from si_hyx_parts.animepack.episode_ru_alloha import sources
from si_hyx_parts.kuhi._transport import RequestScope


def test_alloha_keeps_japanese_audio_and_every_cdn_fallback():
    row = {"source": "yummyanime", "player": "alloha", "embed": "https://alloha.yani.tv/?translation=79",
           "referer": "https://yummyani.me/catalog/item/title", "release": "Субтитры"}
    data = {"hlsSource": [
        {"audioId": "1", "label": "(Russian) Dub", "quality": {"1080": "https://cdn/dub.m3u8"}},
        {"audioId": "79", "label": "(Japanese) Original", "quality": {
            "1080": "https://cdn-a/master.m3u8 or //cdn-b/master.m3u8", "720": "https://cdn/low.m3u8"}}],
        "tracks": [{"kind": "captions", "language": "rus", "src": "//cdn/sub.vtt"},
                   {"kind": "captions", "language": "eng", "src": "https://cdn/eng.vtt"}]}
    result = sources(data, row)
    assert [s["url"] for s in result] == ["https://cdn-a/master.m3u8", "https://cdn-b/master.m3u8", "https://cdn/low.m3u8"]
    assert all(not s["hardsub"] and len(s["subtitles"]) == 1 for s in result)
    assert result[0]["subtitles"][0]["name"] == "sub.vtt"


def test_alloha_release_and_audio_track_ids_are_different_namespaces():
    row = {"source": "animego", "player": "alloha", "embed": "https://alloha.test/?translation=79",
           "referer": "https://animego.online/100-title.html", "release": "Субтитры"}
    data = {"hlsSource": [
        {"audioId": "79", "label": "(Russian) Dub", "quality": {"1080": "https://cdn/dub.m3u8"}},
        {"audioId": "2", "label": "(Japanese) Original", "quality": {"1080": "https://cdn/ja.m3u8"}}],
        "tracks": [{"kind": "captions", "label": "(Russian) Full", "src": "https://cdn/ru.vtt"}]}
    result = sources(data, row)
    assert [stream["url"] for stream in result] == ["https://cdn/ja.m3u8"]
    assert result[0]["audio_language"] == "ja"
    assert result[0]["subtitles"][0]["url"] == "https://cdn/ru.vtt"
    data["tracks"] = [{"kind": "captions", "language": "eng", "src": "https://cdn/en.vtt"}]
    assert sources(data, row) == []


def test_alloha_playlist_rewrites_external_audio_key_and_relative_segments():
    text = '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\n#EXT-X-MEDIA:TYPE=AUDIO,URI="../ja.m3u8"\n#EXTINF:4,\nseg.ts?token=a\n'
    targets = []
    def url(value):
        targets.append(value)
        return "http://127.0.0.1/media/" + str(len(targets))
    rewritten = rewrite_hls(text, "https://cdn/dir/episode.m3u8", url)
    assert targets == ["https://cdn/dir/key.bin", "https://cdn/ja.m3u8", "https://cdn/dir/seg.ts?token=a"]
    assert rewritten.endswith("http://127.0.0.1/media/3\n")
    assert 'URI="http://127.0.0.1/media/1"' in rewritten


def test_bridge_keeps_controls_but_never_replays_one_time_nonce_or_stale_range():
    calls = []
    def get(request):
        calls.append(dict(request.headers))
        return httpx.Response(200, content=b"#EXTM3U\n#EXTINF:4,\nsegment.ts\n",
                              headers={"content-type": "application/vnd.apple.mpegurl"})
    async def cookies(urls):
        return [{"name": "session", "value": "live", "domain": "cdn.test", "path": "/"}]
    async def run():
        scope = RequestScope(lambda: False, time.monotonic() + 10)
        context = SimpleNamespace(cookies=cookies)
        client = httpx.AsyncClient(transport=httpx.MockTransport(get))
        bridge = Bridge(context, scope, "https://alloha.yani.tv/",
                        transport=MediaTransport(context, scope, client=client))
        try:
            bridge.headers.update({"accepts-controls": "renewed", "authorizations": "session",
                                   "borth": "one-time", "range": "bytes=0-10", "user-agent": "Chrome"})
            target = "https://cdn.test/dir/episode.m3u8"
            local = bridge.url(target)
            assert parse_qs(urlsplit(local).query)["url"] == [target]
            body, _type = await bridge.fetch(target)
            assert b"127.0.0.1" in body and scope.requests == 1
        finally:
            await bridge.close()
    asyncio.run(run())
    assert len(calls) == 1
    assert calls[0]["accepts-controls"] == "renewed"
    assert calls[0]["authorizations"] == "session"
    assert calls[0]["user-agent"] == "Chrome"
    assert calls[0]["referer"] == "https://alloha.yani.tv/"
    assert calls[0]["cookie"] == "session=live"
    assert "borth" not in calls[0] and "range" not in calls[0]
