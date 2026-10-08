"""One cancellable deadline across model queue, setup, separation and ASR."""
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
import time

_current = ContextVar("karaoke_attempt_budget", default=None)


def current_budget():
    return _current.get()


class Budget:
    def __init__(self, stopped, seconds, timed=nullcontext, clock=None):
        clock = clock or time.monotonic
        self.stopped, self.clock, self.timed = stopped, clock, timed
        self.seconds = max(30, float(seconds))
        self.deadline = clock() + self.seconds

    def __call__(self):
        return self.stopped() or self.clock() >= self.deadline

    def check(self):
        if self.stopped():
            raise RuntimeError("Караоке: остановлено.")
        if self.clock() >= self.deadline:
            raise TimeoutError(f"Караоке: исчерпан общий лимит AI-попытки ({self.seconds:g} с).")


@contextmanager
def attempt(stopped, seconds, timed=None):
    budget = Budget(stopped, seconds, timed or (lambda _: nullcontext()))
    token = _current.set(budget)
    try:
        budget.check()
        yield budget
        budget.check()
    except Exception:
        budget.check()  # A timeout is temporary and must not enter the weekly reject cache.
        raise
    finally:
        _current.reset(token)


def measured(name):
    budget = _current.get()
    return budget.timed(name) if budget is not None else nullcontext()


def run(name, runner, command, timeout, *, stopped):
    budget = _current.get()
    if budget is not None:
        budget.check()
        timeout = min(timeout, max(.1, budget.deadline - budget.clock()))
    with measured(name):
        result = runner(command, timeout, stopped=stopped)
    if budget is not None:
        budget.check()
    return result
