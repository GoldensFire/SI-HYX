"""Share short-lived public release metadata, retaining every parent fallback."""
import asyncio
from copy import deepcopy
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_GUARD = threading.Lock()
_CACHE = {}
_LOCKS = {}
TTL = 120
LIMIT = 16


def identity(embed):
    parts = urlsplit(embed)
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if key not in ("episode", "translation", "autoplay")]
    return urlunsplit(parts._replace(query=urlencode(sorted(query)), fragment=""))


async def public_metadata(embed, load):
    key = identity(embed)
    lock_key = (id(asyncio.get_running_loop()), key)
    with _GUARD:
        lock = _LOCKS.setdefault(lock_key, asyncio.Lock())
    try:
        async with lock:
            with _GUARD:
                hit = _CACHE.get(key)
            if hit and hit[0] > time.monotonic():
                return deepcopy(hit[1])
            value = await load()
            with _GUARD:
                if len(_CACHE) >= LIMIT:
                    _CACHE.pop(next(iter(_CACHE)))
                _CACHE[key] = (time.monotonic() + TTL, deepcopy(value))
            return value
    finally:
        with _GUARD:
            if not lock.locked() and _LOCKS.get(lock_key) is lock:
                _LOCKS.pop(lock_key, None)
