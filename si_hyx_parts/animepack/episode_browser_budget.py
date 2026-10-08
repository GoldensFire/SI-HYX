"""At most two live Alloha browsers per Kuhi event loop, including extraction."""
import asyncio
import time
from weakref import WeakKeyDictionary

_gates = WeakKeyDictionary()


async def acquire(scope):
    gate = _gates.setdefault(asyncio.get_running_loop(), asyncio.BoundedSemaphore(2))
    while True:
        scope.check(budget=False)
        try:
            await asyncio.wait_for(gate.acquire(), min(.2, max(.01, scope.deadline - time.monotonic())))
        except TimeoutError:
            continue
        try:
            scope.check(budget=False)
        except BaseException:
            gate.release()
            raise
        return gate
