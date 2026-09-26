# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Из чего сложилась цена вопроса — человеческими строками.

Цена собирается в assign_prices несколькими слагаемыми и множителями, и по
одному числу в таблице не видно ни того, что вопрос подорожал за редкого
персонажа, ни того, что песню трудно угадать. Здесь та же арифметика
записывается словами — их показывает подсказка на ячейке «Цена» (просьба
пользователя). Обычный модуль с явными параметрами: к состоянию пака он
отношения не имеет.
"""
from __future__ import annotations

def start(level: int, base: int) -> list[str]:
    """Первая строка разбивки: каждый из 15 уровней даёт свою цену."""
    return [f"Уровень тайтла {int(level)}: базовая цена {base}"]


def add_mult(lines: list, label: str, before: int, after: int) -> None:
    """Строка про множитель — только когда он и правда что-то поменял."""
    if after != before:
        lines.append(f"{label}: {before} → {after}")


def add_step(lines: list, label: str, step: int) -> None:
    """Строка про надбавку («Эндинг: +2»). Ноль не пишем."""
    if step:
        lines.append(f"{label}: {step:+d}")


def finish(lines: list, price: int, floor: int) -> list:
    """Замыкает разбивку итогом и, если цену подняли до пола, говорит об этом."""
    if price <= floor:
        lines.append(f"Ниже {floor} цены не бывает.")
    lines.append(f"Итого: {price}")
    return lines
