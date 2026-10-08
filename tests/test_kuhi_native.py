"""Native provider completeness, crypto, race fallback and bounded HTTP."""
import asyncio
import gzip
import time
from types import SimpleNamespace

import httpx
import pytest

from si_hyx_parts.kuhi import _race, _transport, anikoto, mkissa, reanime
from si_hyx_parts.kuhi.client import KuhiClient


def test_all_native_providers_are_importable():
    assert [name for name, _ in _race.providers()] == _race.RANKING
    assert len(_race.providers()) == 5


@pytest.mark.parametrize("provider", [anikoto, reanime])
def test_split_providers_keep_aes256_nist_vector(provider):
    key = bytes.fromhex("603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4")
    iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    ciphertext = bytes.fromhex("f58c4c04d6e5f1ba779eabfb5f7bfbd6")
    assert provider._decrypt_block(ciphertext, provider._expand_key_256(key)) == bytes(
        x ^ y for x, y in zip(bytes.fromhex("6bc1bee22e409f96e93d7e117393172a"), iv))


def test_mkissa_native_aes_and_js_parser():
    ciphertext, tag = mkissa.aes_gcm_encrypt(bytes(16), bytes(12), b"")
    assert ciphertext == b"" and tag.hex() == "58e2fccefa7e3061367f1d57a4e7455a"
    assert mkissa.aes_gcm_decrypt(bytes(16), bytes(12), ciphertext, tag) == b""
    assert mkissa._js_eval_str("parseInt('12') + 3", {}) == 15
    mkissa._session_cookies["probe"] = "yes"
    try:
        assert "probe=yes" in mkissa.cookie_header()
    finally:
        mkissa._session_cookies.pop("probe")


def test_mkissa_raw_is_an_actual_mode(monkeypatch):
    called = []

    async def series(*args):
        return {"show_id": "show", "show": {}}

    async def page(*args):
        pass

    async def sources(show, episode, audio, captcha):
        called.append(audio)
        return {"sourceUrls": []}

    monkeypatch.setattr(mkissa, "resolve_series", series)
    monkeypatch.setattr(mkissa, "warm_watch_page", page)
    monkeypatch.setattr(mkissa, "get_episode_sources", sources)
    monkeypatch.setattr(mkissa, "_watch_cache", {})
    assert asyncio.run(mkissa.watch(1, "raw", 3, {"media": {}})) == []
    assert called == ["raw"]
    rows = mkissa._build_lists(1, {}, [1], [2], {}, None, [3])
    assert [e["number"] for e in rows["raw"]] == [3]


def test_mkissa_never_matches_a_different_explicit_anilist_id():
    row = {"_id": "wrong", "name": "Death Note", "aniListId": 2}
    assert mkissa.find_best_match([row], ["Death Note"], 2006, 1) is None


def test_race_keeps_later_providers_and_never_requests_dub(monkeypatch):
    calls = []

    def provider(name):
        async def watch(aid, audio, episode, ctx):
            calls.append((name, audio))
            await asyncio.sleep(0.01 if name == "slow" else 0)
            return [{"url": f"https://{name}/stream.m3u8", "type": "hls", "audio": audio}]
        return SimpleNamespace(watch=watch)

    monkeypatch.setattr(_race, "providers", lambda: [(n, provider(n)) for n in ("fast", "slow", "mkissa")])
    monkeypatch.setattr(_race, "_watch_cache", {})
    streams = asyncio.run(_race.all_watch(1, 1, {"media": {}},
                         {"fast": ["sub", "dub"], "slow": ["sub"], "mkissa": ["raw", "sub"]}))
    assert len(streams) == 2
    assert ("slow", "sub") in calls
    assert not any(name == "mkissa" for name, _ in calls)
    assert all(audio != "dub" for _, audio in calls)


def test_http_compression_budget_and_body_limit(monkeypatch):
    real_client = httpx.AsyncClient
    payload = gzip.compress(b'{"ok":true}')
    transport = httpx.MockTransport(lambda req: httpx.Response(
        200, headers={"Content-Encoding": "gzip"}, content=payload))
    monkeypatch.setattr(_transport.httpx, "AsyncClient", lambda **kw: real_client(transport=transport, **kw))
    monkeypatch.setattr(_transport, "_gate", None)
    monkeypatch.setattr(_transport, "_host_locks", {})
    monkeypatch.setattr(_transport, "_next_request", {})
    scope = _transport.RequestScope(lambda: False, time.monotonic() + 5, remaining=1)

    async def request():
        async with _transport.AsyncClient() as client:
            return await client.get("https://test.invalid/")
    response = asyncio.run(_transport.scoped(request(), scope))
    assert response.json() == {"ok": True} and scope.requests == 1
    with pytest.raises(RuntimeError, match="бюджет"):
        asyncio.run(_transport.scoped(request(), scope))
    asyncio.run(scope.close())


def test_client_stop_cancels_pending_provider():
    import threading
    stop = threading.Event()
    cancelled = threading.Event()
    client = KuhiClient(stop.is_set)

    async def slow():
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()
    timer = threading.Timer(0.1, stop.set)
    timer.start()
    started = time.monotonic()
    try:
        assert client.call(slow(), _transport.RequestScope(stop.is_set, started + 60), 60) is None
        assert time.monotonic() - started < 2
        assert cancelled.wait(2)
    finally:
        client.close()
        timer.cancel()
