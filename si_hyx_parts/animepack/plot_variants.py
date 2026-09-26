# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Несколько вариантов вопроса по сюжету за ОДИН запрос к Gemini.

У бесплатного Flash двадцать запросов в сутки, а вопрос по сюжету стоил
запрос за КАЖДУЮ попытку: модель по правилам отвечает ok=false на невнятный
кусок пересказа, строгий разбор выкидывает вопрос без пояснения или с
ответом-организацией, — и на шестнадцать вопросов уходило двадцать с лишним
запросов (просьба пользователя: «как вообще Flash потратила 23 запроса»).
Теперь модель предлагает до VARIANTS вопросов по разным местам текста, и
берётся первый годный: отказ одного варианта больше не стоит нового запроса.
"""
from __future__ import annotations

from typing import Any, Iterator

# Сколько вариантов просим. Больше трёх — длиннее ответ и дольше рассуждение,
# а годный вопрос почти всегда находится среди первых двух.
VARIANTS = 3

PROMPT_TAIL = (
    "\n\nВерни в items до {n} РАЗНЫХ вопросов по разным местам текста, "
    "лучший первым. Каждый вариант подчиняется всем правилам выше и "
    "оценивается отдельно: негодный помечай ok=false, годные не трогай. "
    "Если по тексту не выходит ни одного вопроса — верни пустой список.")


def many(schema: dict, count: int = VARIANTS) -> dict:
    """Схема ответа: список из ``count`` вариантов прежнего вида."""
    return {
        "type": "object",
        "properties": {
            "items": {"type": "array", "items": schema,
                      "maxItems": int(count)},
        },
        "required": ["items"],
    }


def prompt_tail(count: int = VARIANTS) -> str:
    """Приписка к промпту: как именно просить несколько вариантов."""
    return PROMPT_TAIL.format(n=int(count))


def variants(data: Any) -> Iterator[Any]:
    """Варианты из ответа модели по порядку.

    Прежний одиночный ответ (словарь с «question») тоже понимается: так
    отвечают заглушки в тестах и так ответила бы модель, проигнорировав
    обёртку."""
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        yield from data["items"]
    elif isinstance(data, list):
        yield from data
    elif data is not None:
        yield data
