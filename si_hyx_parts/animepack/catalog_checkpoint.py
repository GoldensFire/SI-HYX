# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""One background checkpoint; catalog requests continue during disk writes."""
from concurrent.futures import ThreadPoolExecutor


class CatalogCheckpoint:
    def __init__(self, cache):
        self.cache = cache
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="catalog-save")
        self._pending = None

    def schedule(self):
        if self._pending is not None:
            if not self._pending.done():
                return False
            self._pending.result()
        self._pending = self._pool.submit(self.cache.save)
        return True

    def close(self):
        try:
            if self._pending is not None:
                self._pending.result()
        finally:
            self._pool.shutdown(wait=True)
            # Include answers received while the previous checkpoint was written.
            self.cache.save()
