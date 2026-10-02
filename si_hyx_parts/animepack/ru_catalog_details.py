# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Ограниченный пул деталей; кэш меняет только поток сборки каталога."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import threading

DETAIL_GROUP = "ru_catalog_details_v1"


def usable_detail(detail, row):
    return (isinstance(detail, dict) and detail.get("id") == row["id"]
            and detail.get("slug") == row["slug"]
            and detail.get("metric") == row.get("metric")
            and detail.get("status") in ("NORMAL", "RIGHTS_RESTRICTED")
            and (detail["status"] == "RIGHTS_RESTRICTED"
                 or detail.get("raw_metric") is not None))


class CatalogDetails:
    def __init__(self, client, cache, ttl, stopped):
        self.client, self.cache, self.ttl = client, cache, ttl
        self.stopped = stopped
        self.workers = (min(8, max(1, int(getattr(client, "detail_workers", 1))))
                        if callable(getattr(client, "detail_client", None)) else 1)
        self._halt = threading.Event()
        self._local = threading.local()
        self._clients = []
        self._pool = None
        self._previous_stopped = getattr(client, "stopped", None)

    def cancelled(self):
        return self._halt.is_set() or self.stopped()

    def __enter__(self):
        if self._previous_stopped is not None:
            self.client.stopped = self.cancelled
        if self.workers > 1:
            self._pool = ThreadPoolExecutor(max_workers=self.workers,
                                            thread_name_prefix="ru-catalog")
        return self

    def __exit__(self, *exc):
        self._halt.set()
        if self._pool:
            self._pool.shutdown(wait=True, cancel_futures=True)
        for client in self._clients:
            session = getattr(client, "session", None)
            if session is not None:
                session.close()
        if self._previous_stopped is not None:
            self.client.stopped = self._previous_stopped

    def _details(self, row):
        if self.cancelled():
            return None
        if not hasattr(self._local, "client"):
            self._local.client = self.client.detail_client()
            self._clients.append(self._local.client)
        return self._local.client.details(row)

    def _remember(self, row, detail):
        if not usable_detail(detail, row):
            raise ValueError("catalog population field missing; snapshot discarded")
        self.cache.remember_memo(DETAIL_GROUP, self.client.source + ":" + row["id"], detail)
        return detail

    def rows(self, rows, idle=None):
        """Выдаёт (карточка, новый запрос, попадание в кэш), включая завершённое при stop."""
        todo = iter(rows)
        pending = {}
        exhausted = False
        error = None
        while pending or not exhausted:
            while not exhausted and not self.cancelled() and len(pending) < self.workers:
                row = next(todo, None)
                if row is None:
                    exhausted = True
                    break
                if row["status"] == "RIGHTS_RESTRICTED" or (
                        row["raw_metric"] is not None and row["status"] != "ERROR"):
                    yield row, 0, 0
                    continue
                detail = self.cache.memo(DETAIL_GROUP, self.client.source + ":" + row["id"], self.ttl)
                if usable_detail(detail, row):
                    yield detail, 0, 1
                elif self._pool is None:
                    try:
                        yield self._remember(row, self.client.details(row)), 1, 0
                    except Exception:
                        if self.stopped():
                            return
                        raise
                else:
                    pending[self._pool.submit(self._details, row)] = row
            if not pending:
                break
            finished, _ = wait(pending, timeout=.25, return_when=FIRST_COMPLETED)
            if not finished and idle:
                idle()
            for future in finished:
                row = pending.pop(future)
                try:
                    detail = future.result()
                    if detail is not None or not self.cancelled():
                        yield self._remember(row, detail), 1, 0
                except Exception as exc:
                    if error is None:
                        error = exc
                    self._halt.set()
            if self.cancelled():
                exhausted = True
        if error is not None and not self.stopped():
            raise error
