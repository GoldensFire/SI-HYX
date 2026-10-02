# -*- coding: utf-8 -*-
"""Один запрос кандидата в фоне, пока координатор принимает готовое медиа."""
from concurrent.futures import ThreadPoolExecutor
import threading


class CandidateSource:
    def __init__(self, generator, candidates):
        self.generator = generator
        self.candidates = candidates
        self.pool = ThreadPoolExecutor(max_workers=1,
                                       thread_name_prefix="animepack-candidates")
        self.future = None
        self.closed = threading.Event()

    def _next(self):
        gen = self.generator
        with gen._runtime.worker():
            gen._runtime.local.candidate_stop = self.closed
            try:
                with gen._timed("поиск кандидатов"):
                    with gen._diagnostics.measure("поиск и запросы API"):
                        return next(self.candidates, None)
            finally:
                del gen._runtime.local.candidate_stop

    def request(self):
        if self.future is None:
            self.future = self.pool.submit(self._next)
        return self.future

    def take(self):
        future, self.future = self.future, None
        return future.result()

    def replace(self, candidates):
        self.candidates = iter(candidates)

    def close(self):
        self.closed.set()
        if self.future is not None:
            self.future.cancel()
        self.pool.shutdown(wait=True, cancel_futures=True)
        if self.future is not None and not self.future.cancelled():
            error = self.future.exception()
            if error is None:
                candidate = self.future.result()
                if candidate is not None:
                    self.generator._release_candidate(candidate)
        self.future = None
