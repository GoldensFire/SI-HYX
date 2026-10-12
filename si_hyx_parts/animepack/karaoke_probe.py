# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Параллельная проверка готовых таймингов для песен, ждущих слот караоке.

Когда в паке свободны одни слоты караоке, а у песни доступность таймингов
неизвестна (она пришла из запаса или со скамейки средней сложности, где
CandidateSource её не проверял), песня занимала последний слот и проверялась
уже в загрузке. Слот один — песни шли строго по одной, по 10–30 с каждая:
пак № 130 перебирал так тридцать песен десять минут. Теперь такая песня ждёт
в запасе, а тайминги нескольких песен проверяются параллельно; слот получает
та, у которой они нашлись.
"""
from concurrent.futures import ThreadPoolExecutor
import threading
import time

WORKERS = 4
# Источник не ответил («неизвестно») — столько раз проверяем снова, потом
# песня идёт прежним путём: в слот и проверку при загрузке.
MAX_PROBES = 2
# Верхняя граница ожидания проверки, если пул проверок занят очередью.
WAIT_SECONDS = 120.0
_LOCK = threading.Lock()


def _only_karaoke_free(slots):
    return bool(slots.free) and all(slots.slots[slot] == "karaoke" for slot in slots.free)


def defer(generator, slots, cand, reserve):
    """Отправляет песню с неизвестными таймингами на проверку в запас.

    True — песня отложена (слот не занят); False — пусть идёт обычным путём."""
    if (reserve is None or not slots.timed_only or not _only_karaoke_free(slots)
            or getattr(cand, "_authored_available", None) is not None
            or getattr(cand, "_probe_count", 0) >= MAX_PROBES
            or generator.s.karaoke_effect == "reverse"):
        return False
    fresh = reserve.park(cand)
    if fresh is None:
        return False
    fresh._probe_pending = True
    fresh._probe_count = getattr(cand, "_probe_count", 0) + 1
    fresh._retry_after = time.monotonic() + WAIT_SECONDS
    with _LOCK:
        pool = getattr(generator, "_karaoke_probe_pool", None)
        if pool is None:
            pool = generator._karaoke_probe_pool = ThreadPoolExecutor(
                max_workers=WORKERS, thread_name_prefix="karaoke-probe")
    pool.submit(_probe, generator, fresh, reserve)
    return True


def _probe(generator, cand, reserve):
    available = None
    try:
        if generator.stopped():
            return
        from karaoke.budget import attempt
        from karaoke.search import context
        from .karaoke_processing import catalog_duration, instrumental, known_rejection
        if known_rejection(generator, cand) or instrumental(cand):
            available = False
            return
        with generator._runtime.worker():
            with generator._timed("караоке: поиск готовых таймингов"), \
                    attempt(generator.stopped, 30):
                available = generator.karaoke_resolver.authored_available(
                    cand.song_name, cand.artist,
                    context(cand.song, cand.anime, cand.kind),
                    duration=catalog_duration(cand))
    except Exception as error:  # noqa: BLE001 — «неизвестно», песня пойдёт позже
        generator._log_rare("Караоке: проверка таймингов", f"«{cand.song_name}»: {error}")
    finally:
        cand._authored_available = available
        if available is False:
            from .karaoke_processing import rejection_key
            generator.karaoke_resolver.rejections.put(
                rejection_key(generator, cand, source=True),
                "Готовых таймингов этой песни нет ни в одном источнике.")
        cand._retry_after = time.monotonic() + (60.0 if available is None else 0.0)
        cand._probe_pending = False
        reserve.touch()


def close(generator):
    with _LOCK:
        pool = getattr(generator, "_karaoke_probe_pool", None)
        generator._karaoke_probe_pool = None
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)
