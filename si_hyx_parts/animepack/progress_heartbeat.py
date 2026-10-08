# -*- coding: utf-8 -*-
"""Прогресс между готовыми вопросами: чем рабочие потоки заняты сейчас.

Подпись обновлялась только при принятии вопроса, и при долгом караоке
полоса минутами показывала одно и то же. Теперь раз в INTERVAL секунд
выводятся роды вопросов и самые людные этапы: «ожидание ML-обработчика ×3»."""
from __future__ import annotations

import time

INTERVAL = 15.0


def beat(generator, done: int, total: int, inflight) -> None:
    now = time.monotonic()
    if now - getattr(generator, "_progress_beat", 0.0) < INTERVAL:
        return
    generator._progress_beat = now
    from si_hyx_parts.animepack.generator_selection import _busy
    label = _busy(inflight)
    diagnostics = getattr(generator, "_diagnostics", None)
    stages = diagnostics.active_stages() if diagnostics is not None else []
    if stages:
        text = ", ".join(name if count == 1 else f"{name} ×{count}"
                         for name, count in stages[:3])
        label = f"{label} · {text}" if label else text
    generator._progress(done, total, label)
