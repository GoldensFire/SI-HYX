# -*- coding: utf-8 -*-
"""Ранний отсев известных вопросов с бронью на время параллельной загрузки."""
from __future__ import annotations

from .exact_repeat import candidate_keys, known_keys
from .character_repeat import stable_keys


def reserve(generator, candidate) -> bool:
    """Проверяет известные ключи; собственная бронь кандидату не мешает."""
    if not generator._exact_keys:
        return True
    keys = known_keys(candidate)
    with generator._exact_lock:
        candidate._exact_waiting = False
        occupied = generator._exact_keys | generator._exact_seen
        if keys & occupied:
            if not getattr(candidate, "_exact_duplicate", False):
                generator._early_repeats += 1
            candidate._exact_duplicate = True
            return False
        pending_keys = stable_keys(keys)
        if any(key in generator._exact_pending
               and generator._exact_pending[key] is not candidate for key in pending_keys):
            # Работающая попытка ещё может сорваться. Её возможный дубль
            # ждёт результата, а не сгорает как заведомо повторный вопрос.
            candidate._exact_waiting = True
            return False
        obsolete = [key for key, owner in generator._exact_pending.items()
                    if owner is candidate and key not in pending_keys]
        for key in obsolete:
            del generator._exact_pending[key]
        for key in pending_keys:
            generator._exact_pending[key] = candidate
    return True


def release(generator, candidate) -> None:
    with generator._exact_lock:
        keys = [key for key, owner in generator._exact_pending.items()
                if owner is candidate]
        for key in keys:
            del generator._exact_pending[key]


def accept(generator, candidate) -> bool:
    """Финальная страховка: хеши медиа можно сравнить только после записи."""
    keys = candidate_keys(candidate, generator.folder)
    with generator._exact_lock:
        if keys & (generator._exact_keys | generator._exact_seen):
            return False
        generator._exact_seen.update(stable_keys(keys))
    return True
