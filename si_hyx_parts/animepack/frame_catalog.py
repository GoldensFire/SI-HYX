# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Fetch independent frame metadata in parallel, preserving source order."""
from concurrent.futures import ThreadPoolExecutor


def extra_frames(generator, mal):
    if generator.stopped():
        return []
    sources = (generator.anilist, generator.kitsu, generator.anizip)
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="frame-catalog") as pool:
        futures = [pool.submit(source.frames, mal) for source in sources]
        result = []
        for future in futures:
            if generator.stopped():
                for pending in futures:
                    pending.cancel()
                break
            try:
                result.extend(future.result())
            except Exception:  # noqa: BLE001 — optional frame catalogue
                continue
        return result
