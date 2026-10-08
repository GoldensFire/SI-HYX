"""Каталог книг строится фоном, пока поток аниме уже отдаёт кандидатов.

План книг (уровни ~60 тысяч карточек манги) считается минуты. Раньше это шло
в единственном потоке, который подаёт кандидатов, и отбор стоял: в живом
прогоне — четыре минуты без единого нового тайтла аниме. Теперь план
строится отдельным потоком с самого старта, а поток книг, пока он не готов,
отвечает PENDING — и _merge_streams берёт кандидатов из остальных потоков.
"""
from __future__ import annotations

from concurrent.futures import Future
import threading

# Ответ потока книг «план ещё строится»: не кандидат и не конец потока.
PENDING = object()


def build(generator):
    """(пары id, CatalogPlan) — то, с чего начинается поток книг."""
    pairs = generator.collect_manga_ids()
    from .manga_candidate_plan import order
    pairs = order(generator, pairs)
    from .catalog_selection import CatalogPlan
    return pairs, CatalogPlan(generator, pairs, manga=True)


def start(generator) -> None:
    future = Future()

    def run():
        try:
            future.set_result(build(generator))
        except BaseException as error:  # noqa: BLE001 — отдаст поток книг
            future.set_exception(error)

    generator._manga_plan_future = future
    threading.Thread(target=run, name="manga-plan", daemon=True).start()


def take(generator):
    """Готовый план из фона; без фона (тесты, прямой вызов) — строим сразу.

    Генератор: пока план строится, отдаёт PENDING, затем — сам план."""
    future = getattr(generator, "_manga_plan_future", None)
    if future is None:
        yield build(generator)
        return
    while not future.done():
        if generator.stopped():
            return
        yield PENDING
    generator._manga_plan_future = None
    yield future.result()
