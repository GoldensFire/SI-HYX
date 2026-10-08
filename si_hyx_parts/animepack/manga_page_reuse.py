# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Скачанные страницы тайтла переживают его повтор после временного сбоя.

Пауза или таймаут Gemini, исчерпанный бюджет подготовки — беда минуты, а не
тайтла: он уходит на повтор (trouble_mark). Его страницы при этом остаются
занятыми в _frames_used, и повтор выбирал и качал четыре новые. В прогоне
2026-10-07 манхва «Дисбаланс» так трижды по 3–5 минут готовила страницы
заново. Теперь повтор сразу отдаёт в Gemini уже скачанное."""

# Столько тайтлов держим одновременно: страницы вебтуна весят мегабайты.
KEEP_TITLES = 8


def _key(cand) -> str:
    return str((getattr(cand, "anime", None) or {}).get("id") or cand.title_ru)


def keep(generator, cand, value) -> None:
    with generator._manga_lock:
        pool = generator.__dict__.setdefault("_manga_kept_pages", {})
        pool.pop(_key(cand), None)
        pool[_key(cand)] = value
        while len(pool) > KEEP_TITLES:
            pool.pop(next(iter(pool)))


def take(generator, cand):
    """Сохранённое для тайтла (и забыть его) либо None."""
    pool = generator.__dict__.get("_manga_kept_pages")
    if not pool:
        return None
    with generator._manga_lock:
        return pool.pop(_key(cand), None)
