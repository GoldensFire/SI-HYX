# -*- coding: utf-8 -*-
"""Изменяемый приоритет и отдельный лимит тяжёлых кодировщиков пака."""
from contextlib import contextmanager, nullcontext
from functools import wraps
import os
import threading

from .generation_priority import (
    apply_process_priority, current_thread_level, parallel_limit,
    set_thread_level, thread_level)


class GenerationRuntime:
    def __init__(self, settings, stopped=lambda: False):
        self.settings = settings
        self.stopped = stopped
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.processes = set()
        self.threads = {}
        self.active_tasks = self.active_encoders = 0
        self._draining = False
        self.local = threading.local()

    @property
    def worker_capacity(self):
        return max(1, min(16, int(self.settings.parallel)))

    @property
    def encoder_limit(self):
        if self.settings.generation_priority == "low":
            return 1
        return max(1, min(2, (os.cpu_count() or 1) // 4))

    def set_priority(self, value):
        value = value if value in {"low", "normal", "high"} else "normal"
        with self.condition:
            changed = self.settings.generation_priority != value
            self.settings.generation_priority = value
            for thread_id in self.threads:
                set_thread_level(thread_id, thread_level(self.settings))
            for process in tuple(self.processes):
                apply_process_priority(process, self.settings)
            self.condition.notify_all()
        return changed

    @contextmanager
    def worker(self):
        thread_id = threading.get_native_id()
        original = current_thread_level()
        with self.condition:
            self.threads[thread_id] = self.threads.get(thread_id, 0) + 1
            set_thread_level(thread_id, thread_level(self.settings))
        try:
            yield
        finally:
            with self.condition:
                self.threads[thread_id] -= 1
                if not self.threads[thread_id]:
                    del self.threads[thread_id]
                set_thread_level(thread_id, original)

    def begin_selection(self):
        with self.condition:
            self._draining = False

    def end_selection(self):
        with self.condition:
            self._draining = True
            self.condition.notify_all()

    def current_task_cancelled(self):
        return self._draining and getattr(self.local, "selection_task", False)

    def _acquire(self, counter, limit, *, selection=False):
        with self.condition:
            while getattr(self, counter) >= limit():
                if self.stopped() or (selection and self._draining):
                    raise RuntimeError("Отменено")
                self.condition.wait(.1)
            if self.stopped() or (selection and self._draining):
                raise RuntimeError("Отменено")
            setattr(self, counter, getattr(self, counter) + 1)

    def _release(self, counter):
        with self.condition:
            setattr(self, counter, getattr(self, counter) - 1)
            self.condition.notify_all()

    def wrap_task(self, function):
        @wraps(function)
        def run(*args, **kwargs):
            self._acquire("active_tasks", lambda: parallel_limit(self.settings),
                          selection=True)
            try:
                self.local.selection_task = True
                with self.worker():
                    return function(*args, **kwargs)
            finally:
                self.local.selection_task = False
                self._release("active_tasks")
        return run

    @contextmanager
    def encoding(self, tracker=None):
        # Подбор AVIF держит один слот на все пробы; его runner может снова
        # зайти в _run_capture. Повторный захват тем же потоком не нужен.
        depth = getattr(self.local, "encoding_depth", 0)
        if not depth:
            measure = (tracker.measure("ожидание кодировщика")
                       if tracker is not None else nullcontext())
            with measure:
                self._acquire("active_encoders", lambda: self.encoder_limit,
                              selection=getattr(self.local, "selection_task", False))
        self.local.encoding_depth = depth + 1
        try:
            yield
        finally:
            self.local.encoding_depth = depth
            if not depth:
                self._release("active_encoders")

    def track(self, process):
        with self.condition:
            self.processes.add(process)
            apply_process_priority(process, self.settings)

    def untrack(self, process):
        with self.condition:
            self.processes.discard(process)


def track_process(generator, process):
    runtime = getattr(generator, "_runtime", None)
    if runtime is not None:
        runtime.track(process)
    else:
        with generator._procs_lock:
            generator._procs.add(process)


def untrack_process(generator, process):
    runtime = getattr(generator, "_runtime", None)
    if runtime is not None:
        runtime.untrack(process)
    else:
        with generator._procs_lock:
            generator._procs.discard(process)


def encoding_operation(function):
    @wraps(function)
    def run(generator, *args, **kwargs):
        runtime = getattr(generator, "_runtime", None)
        command = args[0] if args else kwargs.get("cmd")
        # ffprobe, скачивание и Opus не должны занимать слот AV1.
        heavy = (function.__name__ != "_run_capture" or
                 any(value in {"libaom-av1", "libsvtav1"}
                     for value in (command or [])))
        slot = (runtime.encoding(getattr(generator, "_diagnostics", None))
                if runtime is not None and heavy else nullcontext())
        # Вложенные рабочие потоки (например, поиск каверов) тоже получают
        # живой приоритет на всё время выполнения процесса.
        thread_id = threading.get_native_id()
        worker = (runtime.worker() if runtime is not None
                  and thread_id not in runtime.threads else nullcontext())
        with worker:
            with slot:
                return function(generator, *args, **kwargs)
    return run
