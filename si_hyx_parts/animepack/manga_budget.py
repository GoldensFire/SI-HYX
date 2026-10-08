"""A bounded preparation budget shared by source, page and scene attempts."""
import time


def start(generator, candidate):
    seconds = max(30, int(getattr(generator.s, "manga_candidate_seconds", 180)))
    candidate._manga_deadline = time.monotonic() + seconds
    runtime = getattr(generator, "_runtime", None)
    if runtime is not None:
        runtime.local.manga_deadline = candidate._manga_deadline


def check(generator, candidate):
    if generator.stopped():
        raise RuntimeError("Генерация остановлена")
    if time.monotonic() >= getattr(candidate, "_manga_deadline", float("inf")):
        raise TimeoutError("Истекло общее время подготовки страницы комикса")
