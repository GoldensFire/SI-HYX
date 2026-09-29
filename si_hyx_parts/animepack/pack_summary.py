# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Название пака с номером и описание его состава для поля «Комментарии».

Название: каждый следующий пак получает «№ 1», «№ 2» и так далее — собранные
подряд паки иначе не отличить друг от друга ни в списке SIGame, ни в папке.

Комментарии: вместо прежней отписки туда идёт настоящий состав — сколько в
паке вопросов какого рода и какая у них средняя сложность (просьба
пользователя).
Ни числа раундов и тем, ни разброса цен, ни предупреждения «собрано
автоматически» там больше нет: всё это пользователь и так знает про свой пак,
а комментарий читается в SIGame целиком. Обычный модуль с явными параметрами:
состояния пака он не касается.
"""
from __future__ import annotations

import re
from collections import Counter

from .test_packs import TEST_LIMIT


def numbered_title(title: str, number) -> str:
    """«Сгенерировано в SI-HYX» + номер → «Сгенерировано в SI-HYX № 3».

    Ноль, отрицательное и мусор номером не считаются — название остаётся как
    есть. Если номер уже приписан (пак пересобирают с тем же названием),
    второй раз не приписываем."""
    name = str(title or "").strip()
    try:
        value = int(number)
    except (TypeError, ValueError):
        return name
    if value <= 0 or not name:
        return name
    tail = f"№ {value}"
    return name if name.endswith(tail) else f"{name} {tail}"


# Приписка бывает и целой («Ур. 7» у паков, собранных раньше), и с десятыми.
_LEVEL_TAIL = re.compile(r"\s*\(Ур\.\s*\d+(?:[.,]\d+)?\)\s*$")


def average_level(songs) -> float:
    """Средняя сложность пака с точностью до десятых (0 — считать не по чему).

    Та же средняя, что в строке «Сложность (Ур.)» поля «Комментарии» и в
    журнале («Средняя сложность всего пака»): по всем вопросам пака. Целым
    числом её больше не округляем (просьба пользователя): «7» у пака со
    средней 6.6 и у пака со средней 7.4 ничего не говорило."""
    levels = [int(getattr(cand, "level", 0) or 0) for cand in songs or ()]
    levels = [value for value in levels if value > 0]
    if not levels:
        return 0
    return round(sum(levels) / len(levels) + 1e-9, 1)


def pack_title(title: str, number, songs, *, test_number=0,
               ignore_test_packs=False) -> str:
    """«Сгенерировано в SI-HYX № 56 (Ур. 4.3)» — и внутри пака, и в имени файла.

    Средняя сложность приписывается в конце (просьба пользователя): по списку
    паков сразу видно, какой из них лёгкий, а какой трудный. Прежняя приписка
    при пересборке заменяется, а не копится."""
    if ignore_test_packs and len(songs or ()) < TEST_LIMIT:
        return numbered_title("Тестовый", test_number)
    name = numbered_title(_LEVEL_TAIL.sub("", str(title or "")), number)
    level = average_level(songs)
    return f"{name} (Ур. {level:.1f})" if name and level else name


def composition_text(songs, settings, kind_titles: dict,
                     video_kind: str = "video") -> str:
    """Состав пака словами: роды вопросов, раунды и разброс сложности."""
    rows = list(songs or [])
    if not rows:
        return ""
    groups = {}
    counts = Counter()
    for cand in rows:
        kind = _kind(cand, video_kind)
        counts[kind] += 1
        groups.setdefault(kind, []).append(cand)
    lines = []
    for kind, count in counts.most_common():
        levels = _values(groups[kind], "level")
        detail = _average_text(levels)
        if kind in {"opening", "ending", "insert"}:
            amq = _values(groups[kind], "difficulty")
            if amq:
                detail += ((" / " if detail else "")
                           + f"AMQ - от {_number(min(amq))} "
                             f"до {_number(max(amq))}")
        suffix = f" ({detail})" if detail else ""
        lines.append(f"  • {kind_titles.get(kind, kind)}: {count}{suffix}")
    levels = [int(getattr(cand, "level", 0) or 0) for cand in rows]
    levels = [value for value in levels if value > 0]
    if levels:
        lines.append("")
        lines.append(f"Сложность (Ур.): от {min(levels)} до {max(levels)}, "
                     f"в среднем {sum(levels) / len(levels):.1f}.")
    return "\n".join(lines)


def _values(rows, attr: str) -> list[float]:
    values = []
    for row in rows:
        try:
            value = float(getattr(row, attr, 0) or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            values.append(value)
    return values


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def _average_text(values: list[float]) -> str:
    """«4.7 сложность в ср.» — разброс «от… до…» пользователю не нужен."""
    if not values:
        return ""
    average = sum(values) / len(values)
    return f"{average:.1f} сложность в ср."


def _kind(cand, video_kind: str) -> str:
    """Род вопроса так, как он выглядит в таблице состава.

    У ролика, не нашедшего видео, вопрос вышел обычной песней — и в составе
    он должен считаться песней, иначе числа не сойдутся с тем, что в паке."""
    kind = str(getattr(cand, "kind", "") or "")
    if kind == video_kind and not getattr(cand, "has_video", False):
        return str(getattr(cand, "base_kind", "") or kind)
    return kind
