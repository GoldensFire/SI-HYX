"""Twenty candidates ahead, with independent cached availability probes."""
from concurrent.futures import Future, ThreadPoolExecutor
import threading
from .candidate_availability import probe, rank

WINDOW = 20


class CandidateSource:
    def __init__(self, generator, candidates):
        self.generator = generator
        self.candidates = iter(candidates)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='candidate-feed')
        self.probes = ThreadPoolExecutor(max_workers=6, thread_name_prefix='candidate-check')
        self.closed = threading.Event()
        self.condition = threading.Condition(threading.RLock())
        self.pending = []
        self.future = None
        self.finished = False
        self.error = None
        self.producer = self.pool.submit(self._produce)

    def _check(self, candidate):
        gen = self.generator
        with gen._runtime.worker():
            gen._runtime.local.candidate_stop = self.closed
            try:
                probe(gen, candidate)
            except Exception as error:
                candidate._availability_error = str(error)
                candidate._authored_available = None
            finally:
                gen._runtime.local.candidate_stop = None

    def _produce(self):
        gen = self.generator
        try:
            with gen._runtime.worker():
                gen._runtime.local.candidate_stop = self.closed
                try:
                    while not self.closed.is_set() and not gen.stopped():
                        with self.condition:
                            while len(self.pending) >= WINDOW and not self.closed.is_set():
                                self.condition.wait(.1)
                        if self.closed.is_set():
                            break
                        with gen._timed('поиск кандидатов'):
                            candidate = next(self.candidates, None)
                        if candidate is None:
                            break
                        checked = self.probes.submit(self._check, candidate)
                        with self.condition:
                            self.pending.append((candidate, checked))
                        checked.add_done_callback(lambda _: self._deliver())
                        self._deliver()
                finally:
                    gen._runtime.local.candidate_stop = None
        except Exception as error:
            self.error = error
        finally:
            with self.condition:
                self.finished = True
            self._deliver()

    def _deliver(self):
        with self.condition:
            if self.future is None or self.future.done():
                return
            ready = [(c, f) for c, f in self.pending if f.done()]
            if ready:
                selected = min(ready, key=lambda item: rank(self.generator, item[0]))
                self.pending.remove(selected)
                self.future.set_result(selected[0])
                self.condition.notify_all()
            elif self.finished and not self.pending:
                if self.error is not None:
                    self.future.set_exception(self.error)
                else:
                    self.future.set_result(None)

    def request(self):
        with self.condition:
            if self.future is None:
                self.future = Future()
            self._deliver()
            return self.future

    def take(self):
        candidate = self.future.result()
        with self.condition:
            self.future = None
        return candidate

    def replace(self, candidates):
        self.producer.result()
        with self.condition:
            self.candidates = iter(candidates)
            self.finished = False
            self.error = None
            self.future = None
        self.producer = self.pool.submit(self._produce)

    def close(self):
        self.closed.set()
        with self.condition:
            self.condition.notify_all()
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.probes.shutdown(wait=True, cancel_futures=True)
        with self.condition:
            leftovers = [c for c, _ in self.pending]
            self.pending.clear()
            if self.future is not None and self.future.done() and not self.future.exception():
                candidate = self.future.result()
                if candidate is not None:
                    leftovers.append(candidate)
            self.future = None
        for candidate in leftovers:
            self.generator._release_candidate(candidate)
