"""Only consecutive transport failures pause providers; probe recovery is bounded."""
import asyncio
from types import SimpleNamespace
import httpx
import pytest

from si_hyx_parts.kuhi.provider_health import ProviderHealth
from si_hyx_parts.kuhi import _race


@pytest.mark.parametrize("status, paused", [(429, True), (503, True), (404, False)])
def test_http_status_uses_response_even_when_error_message_has_no_status(status, paused):
    health = ProviderHealth()
    request = httpx.Request("GET", "https://provider.test/")
    error = httpx.HTTPStatusError("request failed", request=request,
                                 response=httpx.Response(status, request=request))
    for _ in range(3):
        assert health.allow("provider", "episodes")
        health.result("provider", "episodes", error=error)
    assert health.allow("provider", "episodes") is not paused


def test_missing_anime_and_404_never_pause():
    health = ProviderHealth()
    for _ in range(10):
        assert health.allow("provider", "episodes")
        assert not health.result("provider", "episodes", error=RuntimeError("HTTP 404"))
    assert health.snapshot()["provider", "episodes"]["missing"] == 10


def test_timeout_pauses_one_phase_and_recovers_after_single_probe():
    now = [1.0]
    health = ProviderHealth(clock=lambda: now[0])
    for n in range(3):
        assert health.allow("provider", "episodes")
        assert health.result("provider", "episodes", error=TimeoutError()) == (n == 2)
    assert not health.allow("provider", "episodes")
    assert health.allow("provider", "watch")
    now[0] += 121
    assert health.allow("provider", "episodes")
    assert not health.allow("provider", "episodes")
    health.cancelled("provider", "episodes")
    assert health.allow("provider", "episodes")
    health.result("provider", "episodes", ok=True)
    assert health.allow("provider", "episodes")


def test_race_skips_paused_network_provider_and_restores_it(monkeypatch):
    now, calls = [1.0], []
    health = ProviderHealth(clock=lambda: now[0])
    monkeypatch.setattr(_race, "HEALTH", health)
    async def episodes(*args):
        calls.append(1)
        if len(calls) <= 3:
            raise TimeoutError("outage")
        return {"episodes": {"sub": [1]}}
    mod = SimpleNamespace(get_episodes=episodes)
    async def run():
        for _ in range(4):
            assert await _race._episodes_one(mod, "test", 1, {}) == ("test", None)
        assert len(calls) == 3
        now[0] += 121
        assert (await _race._episodes_one(mod, "test", 2, {}))[1]
    asyncio.run(run())
