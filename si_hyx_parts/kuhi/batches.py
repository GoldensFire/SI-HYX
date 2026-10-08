"""Deliver completed providers while retaining pending fallback searches."""
from __future__ import annotations

import asyncio
from queue import Empty, Queue
import time

from . import _race
from ._transport import scoped
from .provider_policy import START_DELAY


async def episode_batches(aid, ctx):
    async def start(mod, name):
        delay = START_DELAY.get(name, 0)
        if delay:
            await asyncio.sleep(delay)
        return await _race._episodes_one(mod, name, aid, ctx)
    jobs = [asyncio.create_task(start(mod, name))
            for name, mod in _race.providers()]
    try:
        for done in asyncio.as_completed(jobs):
            name, data = await done
            if data:
                yield {"providers": {name: data}}
    finally:
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)


async def watch_batches(aid, episode, ctx, eligible):
    jobs = [asyncio.create_task(_race._watch_one(mod, name, aid, episode, audio, ctx))
            for name, mod in _race.providers() for audio in eligible.get(name, ())
            if audio in ("sub", "raw") and (audio != "raw" or name == "mkissa")]
    try:
        for done in asyncio.as_completed(jobs):
            name, streams, seconds, ok = await done
            _race.record_latency(name, seconds, ok)
            if ok:
                yield [{**stream, "provider": name} for stream in streams
                       if stream.get("audio") in ("raw", "sub")]
    finally:
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)


class ProviderBatches:
    """A closeable synchronous iterator; the coroutine owns provider cleanup."""
    def __init__(self, client, batches, scope, loop):
        self.client, self.scope = client, scope
        self.queue = Queue()
        self.closed = False

        async def collect():
            try:
                async for batch in batches:
                    self.queue.put(batch)
            finally:
                await batches.aclose()
                self.queue.put(None)

        self.future = asyncio.run_coroutine_threadsafe(scoped(collect(), scope), loop)
        with client._lock:
            client._futures.add(self.future)
        self.future.add_done_callback(self._done)

    def _done(self, future):
        with self.client._lock:
            self.client._futures.discard(future)

    def __iter__(self):
        return self

    def __next__(self):
        while not self.closed and not self.client.closed and not self.client.stopped():
            if time.monotonic() >= self.scope.deadline:
                break
            try:
                batch = self.queue.get(timeout=0.2)
            except Empty:
                if self.future.done():
                    break
                continue
            if batch is None:
                break
            return batch
        self.close()
        raise StopIteration

    def close(self):
        if not self.closed:
            self.closed = True
            if not self.future.done():
                self.future.cancel()

