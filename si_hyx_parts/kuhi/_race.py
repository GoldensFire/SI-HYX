# Native Kuhi/anime-api, MIT, Copyright (c) 2026 aryaniiil. See LICENSE.
import asyncio
import importlib
import time

from si_hyx_parts.kuhi._media import build_ctx

RANKING = [
    "anineko", "anizone", "anikoto", "reanime", "aniwaves",
    "kaa", "anibd", "animegg", "mkissa", "animeonsen",
]

WATCH_TIMEOUT = 75.0
EPISODES_TIMEOUT = 60.0
WATCH_CACHE_TTL = 45.0
WATCH_CACHE_LIMIT = 512

_latency: dict = {}
_ep_latency: dict = {}
_failures: dict = {}
_watch_cache: dict = {}


def _load(name):
    try:
        return importlib.import_module(f"si_hyx_parts.kuhi.{name}")
    except Exception as e:
        print(f"[RACE] provider {name} unavailable: {e}")
        return None


def providers():
    mods = []
    for name in RANKING:
        mod = _load(name)
        if mod is not None:
            mods.append((name, mod))
    return mods


def record_latency(name: str, seconds: float, ok: bool, kind: str = "watch"):
    table = _latency if kind == "watch" else _ep_latency
    if ok:
        prev = table.get(name)
        table[name] = seconds if prev is None else round(0.7 * prev + 0.3 * seconds, 3)
        _failures[name] = 0
    else:
        _failures[name] = _failures.get(name, 0) + 1


def default_provider():
    if not _latency:
        return RANKING[0]
    return sorted(_latency.items(), key=lambda kv: kv[1])[0][0]


def latency_table() -> dict:
    return {name: {"avg_seconds": _latency.get(name),
                   "episodes_seconds": _ep_latency.get(name),
                   "failures": _failures.get(name, 0)}
            for name in RANKING}


async def _watch_one(mod, name, anilist_id, ep, audio, ctx):
    key = (name, anilist_id, ep, audio)
    hit = _watch_cache.get(key)
    if hit and hit[0] > time.time():
        return name, hit[1], 0.0, True
    t0 = time.time()
    try:
        streams = await asyncio.wait_for(mod.watch(anilist_id, audio, ep, ctx), WATCH_TIMEOUT)
        dt = round(time.time() - t0, 3)
        if streams:
            if len(_watch_cache) >= WATCH_CACHE_LIMIT:
                now = time.time()
                for old in [k for k, value in _watch_cache.items() if value[0] <= now]:
                    _watch_cache.pop(old, None)
                if len(_watch_cache) >= WATCH_CACHE_LIMIT:
                    _watch_cache.pop(next(iter(_watch_cache)))
            _watch_cache[key] = (time.time() + WATCH_CACHE_TTL, streams)
            return name, streams, dt, True
        return name, None, dt, False
    except Exception as e:
        return name, None, round(time.time() - t0, 3), False


async def race_watch(anilist_id: int, ep: int, audio: str = "sub",
                     preferred: str | None = None) -> dict | None:
    mods = providers()
    if not mods:
        return None
    ctx = await build_ctx(anilist_id)
    if preferred:
        pick = next((m for m in mods if m[0] == preferred), None)
        if pick is not None:
            name, streams, dt, ok = await _watch_one(pick[1], pick[0], anilist_id, ep, audio, ctx)
            record_latency(name, dt, ok)
            if ok:
                return {"provider": name, "streams": streams,
                        "requestedProvider": preferred,
                        "timings": {name: {"seconds": dt, "ok": True}},
                        "defaultProvider": default_provider()}
            mods = [m for m in mods if m[0] != preferred]
            if not mods:
                return None
    pending = {asyncio.ensure_future(_watch_one(mod, name, anilist_id, ep, audio, ctx))
               for name, mod in mods}
    timings: dict = {}
    winner = None
    try:
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                name, streams, dt, ok = task.result()
                timings[name] = {"seconds": dt, "ok": ok}
                record_latency(name, dt, ok)
                if ok and winner is None:
                    winner = {"provider": name, "streams": streams}
            if winner is not None:
                break
    finally:

        if pending:
            try:
                done2, pending2 = await asyncio.wait(pending, timeout=8.0)
                for task in done2:
                    try:
                        name, streams, dt, ok = task.result()
                        timings[name] = {"seconds": dt, "ok": ok}
                        record_latency(name, dt, ok)
                    except Exception:
                        pass
                pending = pending2
            finally:
                for task in pending:
                    task.cancel()
    if winner is None:
        return None
    winner["timings"] = timings
    winner["defaultProvider"] = default_provider()
    if preferred:
        winner["requestedProvider"] = preferred
    return winner


async def _episodes_one(mod, name, anilist_id, ctx):
    t0 = time.time()
    try:
        data = await asyncio.wait_for(mod.get_episodes(anilist_id, ctx), EPISODES_TIMEOUT)
        eps = (data.get("episodes") or {})
        count = sum(len(v) for v in eps.values() if isinstance(v, list))
        record_latency(name, time.time() - t0, count > 0, kind="episodes")
        return name, data if count > 0 else None
    except Exception as e:
        print(f"[RACE] {name} episodes failed: {type(e).__name__}: {str(e)[:120]}")
        record_latency(name, time.time() - t0, False, kind="episodes")
        return name, None


async def merged_episodes(anilist_id: int, ctx=None) -> dict | None:
    mods = providers()
    if not mods:
        return None
    ctx = ctx or await build_ctx(anilist_id)
    results = await asyncio.gather(
        *[_episodes_one(mod, name, anilist_id, ctx) for name, mod in mods])
    merged = {name: data for name, data in results if data}
    if not merged:
        return None
    return {"anilistId": anilist_id, "source": "native", "providers": merged}


async def all_watch(anilist_id, ep, ctx, eligible):
    """Race every eligible provider and retain alternatives for failed media cuts.

    A winner in the web API is only a URL. SI-HYX needs a validated video, so
    cancelling slower providers at the first URL would discard its fallback.
    No dub request is issued; MKissa raw is ranked before all sub sources.
    """
    jobs = []
    for name, mod in providers():
        audios = eligible.get(name, ())
        for audio in audios:
            if audio in ("sub", "raw") and (audio != "raw" or name == "mkissa"):
                jobs.append(_watch_one(mod, name, anilist_id, ep, audio, ctx))
    results = await asyncio.gather(*jobs)
    out = []
    for name, streams, dt, ok in results:
        record_latency(name, dt, ok)
        if ok:
            out.extend({**stream, "provider": name} for stream in streams
                       if stream.get("audio") in ("raw", "sub"))
    return out


def merge_subtitles(streams: list) -> list:
    seen, out = set(), []
    for s in streams or []:
        for sub in s.get("subtitles") or []:
            url = sub.get("url")
            if url and url not in seen:
                seen.add(url)
                out.append(sub)
    return out


def providers_status() -> dict:
    return {
        "defaultProvider": default_provider(),
        "ranking": RANKING,
        "available": [name for name, _ in providers()],
        "latency": latency_table(),
    }
