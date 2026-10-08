# -*- coding: utf-8 -*-
"""Измеренные загрузки, обработка, очереди и параллелизм генератора."""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager, nullcontext
from functools import wraps
import threading
import time

from .generation_priority import parallel_limit


class GenerationDiagnostics:
    def __init__(self):
        self.lock = threading.Lock()
        self.local = threading.local()
        self.spans = defaultdict(list)
        self.slowest = []
        self.active = self.peak = 0
        self.started = 0
        self.downloads = Counter()
        self.download_bytes = Counter()
        self.current = Counter()

    def transfer(self, size=None):
        stage = getattr(self.local, "stage", "прочее")
        with self.lock:
            if size is None:
                self.downloads[stage] += 1
            else:
                self.download_bytes[stage] += size

    @contextmanager
    def stage(self, name):
        previous = getattr(self.local, "stage", "прочее")
        self.local.stage = name
        self._move_active(previous, name)
        try:
            yield
        finally:
            self.local.stage = previous
            self._move_active(name, previous)

    def _move_active(self, old, new):
        """Innermost stage of every thread, for the live progress label."""
        with self.lock:
            if old != "прочее":
                self.current[old] -= 1
                if self.current[old] <= 0:
                    del self.current[old]
            if new != "прочее":
                self.current[new] += 1

    def active_stages(self):
        with self.lock:
            return self.current.most_common()

    @contextmanager
    def measure(self, operation):
        """Вложенная операция вычитается из родительской: без двойного счёта."""
        stage = getattr(self.local, "stage", "прочее")
        stack = getattr(self.local, "stack", [])
        self.local.stack = stack
        frame = [time.monotonic(), []]
        stack.append(frame)
        try:
            yield
        finally:
            end = time.monotonic()
            stack.pop()
            if stack:
                stack[-1][1].append((frame[0], end))
            # Записываем интервалы собственного времени, а не один большой
            # интервал с вычтенной длительностью: перекрытия потоков остаются
            # измеримыми и после вложенных операций.
            start = frame[0]
            own = []
            for left, right in frame[1]:
                if left > start:
                    own.append((start, left))
                start = right
            if end > start:
                own.append((start, end))
            with self.lock:
                self.spans[(stage, operation)].extend(own)
            task = getattr(self.local, "task", None)
            if task is not None:
                task[operation] += sum(b - a for a, b in own)

    def wrap(self, fetch, titles):
        @wraps(fetch)
        def measured(candidate):
            start = time.monotonic()
            queued = getattr(candidate, "_queued_at", start)
            label = titles.get(candidate.kind, candidate.kind)
            task = Counter()
            self.local.task = task
            with self.lock:
                self.active += 1
                self.started += 1
                self.peak = max(self.peak, self.active)
                self.spans[("очередь задач", "ожидание свободного потока")].append(
                    (queued, start))
            try:
                with self.stage(label):
                    return fetch(candidate)
            finally:
                elapsed = time.monotonic() - start
                with self.lock:
                    self.active -= 1
                    self.slowest.append((elapsed, candidate.title_ru, label,
                                         dict(task), start - queued))
                    self.slowest.sort(key=lambda row: row[0], reverse=True)
                    del self.slowest[5:]
                self.local.task = None
        return measured

    def report(self, generator):
        from animepack import fmt_elapsed
        log, fmt = generator.log, fmt_elapsed
        limit = parallel_limit(generator.s)
        log(f"Рабочие задачи: запрошено {generator.s.parallel}, "
            f"действующий лимит {limit}, максимум одновременно {self.peak}; "
            f"запущено {self.started}.")
        early = getattr(generator, "_early_repeats", 0)
        late = generator._late.get("тот же вопрос в выбранных паках", 0)
        log(f"Точные повторы: отсечено до подготовки медиа {early}, "
            f"по готовому вопросу {late}.")
        with self.lock:
            spans = [(key, list(value)) for key, value in self.spans.items()]
            slowest = list(self.slowest)
            transfers = [(stage, count, self.download_bytes[stage])
                         for stage, count in self.downloads.items()]
        if spans:
            log("Подробные замеры: время на часах / сумма по задачам. "
                "Разные этапы могут пересекаться.")
        for (stage, operation), rows in spans:
            wall = generator._merge_spans(rows)
            summed = sum(b - a for a, b in rows)
            log(f"  • {stage} — {operation}: {fmt(wall)} / {fmt(summed)}")
        for stage, count, size in transfers:
            log(f"  • {stage} — загрузка медиа: вызовов загрузки {count}, "
                f"получено {size / (1024 * 1024):.2f} МБ.")
        if slowest:
            log("Самые долгие попытки подготовки вопросов:")
        for elapsed, title, label, task, queue in slowest:
            parts = [f"{name} {fmt(value)}" for name, value in task.items()]
            parts.append(f"очередь {fmt(queue)}")
            log(f"  • {label}, «{title}»: {fmt(elapsed)}; " + "; ".join(parts))


def operation(name):
    """Декоратор метода генератора; поддерживает простые заглушки тестов."""
    def decorate(function):
        @wraps(function)
        def measured(generator, *args, **kwargs):
            tracker = getattr(generator, "_diagnostics", None)
            if tracker is None:
                return function(generator, *args, **kwargs)
            label = name(args, kwargs) if callable(name) else name
            with tracker.measure(label):
                return function(generator, *args, **kwargs)
        return measured
    return decorate


def measuring(generator, name):
    """Замер вложенной операции генератора; без трекера — пустой контекст."""
    tracker = getattr(generator, "_diagnostics", None)
    return tracker.measure(name) if tracker is not None else nullcontext()


def process_label(args, kwargs):
    command = args[0] if args else kwargs.get("cmd", [])
    executable = str(command[0]).casefold() if command else ""
    network = any(str(value).startswith(("http://", "https://")) for value in command)
    # ffprobe источника и кодирование с чтением из сети — разные узкие места.
    if "ffprobe" in executable:
        return "ffprobe по сети" if network else "анализ медиа"
    # Копия куска без перекодирования — это сеть, а не кодировщик: под старой
    # подписью она выглядела как AV1, ждущий сеть.
    copied = any(flag in ("-c", "-codec") and value == "copy"
                 for flag, value in zip(command, command[1:]))
    if network and copied:
        return "копия отрезка из сети"
    return "кодирование с чтением из сети" if network else "кодирование"


@contextmanager
def locked(generator, lock):
    tracker = getattr(generator, "_diagnostics", None)
    if tracker is None:
        with lock:
            yield
        return
    with tracker.measure("ожидание блокировки"):
        lock.acquire()
    try:
        yield
    finally:
        lock.release()


def peak_parallel(spans):
    events = [(point, delta) for start, end in spans if end > start
              for point, delta in ((start, 1), (end, -1))]
    current = peak = 0
    for _, delta in sorted(events):
        current += delta
        peak = max(peak, current)
    return peak
