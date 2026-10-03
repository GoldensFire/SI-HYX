"""Completed providers become usable before slow fallback searches finish."""
import asyncio
from types import SimpleNamespace

from si_hyx_parts.kuhi import _race, batches, _transport


def test_completed_catalogue_is_yielded_before_an_unresponsive_provider(monkeypatch):
    cancelled = []
    async def slow(*args):
        try:
            await asyncio.sleep(30)
        finally:
            cancelled.append(True)
    async def fast(*args):
        return {"episodes": {"sub": [{"number": 7}]}}
    monkeypatch.setattr(_race, "providers", lambda: [
        ("slow", SimpleNamespace(get_episodes=slow)), ("fast", SimpleNamespace(get_episodes=fast))])
    async def run():
        source = batches.episode_batches(1, {})
        row = await asyncio.wait_for(anext(source), .5)
        assert list(row["providers"]) == ["fast"]
        await source.aclose()
    asyncio.run(run())
    assert cancelled


def test_slow_stream_fallback_remains_available_after_first_provider(monkeypatch):
    def provider(name, delay):
        async def watch(*args):
            await asyncio.sleep(delay)
            return [{"url": "https://" + name, "audio": "sub"}]
        return SimpleNamespace(watch=watch)
    monkeypatch.setattr(_race, "providers", lambda: [("fast", provider("fast", 0)),
                                                      ("slow", provider("slow", .03))])
    monkeypatch.setattr(_race, "_watch_cache", {})
    async def run():
        found = []
        async for batch in batches.watch_batches(1, 7, {}, {"fast": ["sub"], "slow": ["sub"]}):
            found.extend(row["provider"] for row in batch)
        assert found == ["fast", "slow"]
    asyncio.run(run())


def test_same_host_responses_overlap_but_starts_keep_the_rate_limit(monkeypatch):
    monkeypatch.setattr(_transport, "_gate", None)
    monkeypatch.setattr(_transport, "_host_locks", {})
    monkeypatch.setattr(_transport, "_next_request", {})
    async def run():
        starts, finishes = [], []
        async def request():
            async with _transport.connection("test.invalid", None):
                starts.append(asyncio.get_running_loop().time())
                await asyncio.sleep(.7)
                finishes.append(asyncio.get_running_loop().time())
        await asyncio.gather(request(), request())
        assert .3 <= starts[1] - starts[0] < .65
        assert starts[1] < finishes[0]
    asyncio.run(run())
