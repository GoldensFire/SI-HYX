# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Keep completed provider results when a sibling exceeds the stage budget."""
import asyncio
import time


async def collect(coroutines, scope, seconds):
    tasks = [asyncio.create_task(coro) for coro in coroutines]
    if not tasks:
        return []
    budget = max(0, min(seconds, scope.deadline - time.monotonic()) - 1)
    try:
        done, pending = await asyncio.wait(tasks, timeout=budget)
        results = []
        for task in tasks:
            if task not in done:
                results.append(TimeoutError("источник превысил бюджет этапа"))
            elif task.cancelled():
                results.append(asyncio.CancelledError())
            else:
                try:
                    results.append(task.result())
                except Exception as error:  # noqa: BLE001 — one provider may fail
                    results.append(error)
        return results
    finally:
        pending = [task for task in tasks if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
