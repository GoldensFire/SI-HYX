"""Клиент SIStatistics — статистика реально сыгранных игр.

Эндпоинт games/packages/stats матчит пакет по ТОЧНОМУ совпадению name + authors
(регистрозависимо). Пустые авторы почти всегда дают 404 — поэтому передаём
авторов из карточки sibrowser как есть.
"""
from __future__ import annotations
import time
import urllib.parse
from typing import Iterable

import requests

from . import config


def _name_variants(name: str) -> list[str]:
    """Кандидаты написания названия для матчинга со статистикой.

    sibrowser обрезает пробелы в заголовке, а SIStatistics сверяет ВНУТРЕННЕЕ имя
    пакета из content.xml — буква-в-букву, включая хвостовой/ведущий пробел
    (авторы часто оставляют «… от Автор »). Перебираем разумные варианты, чтобы
    не терять статистику из-за таких расхождений — без скачивания .siq.
    """
    import re
    base = name or ""
    variants = [
        base,
        base + " ",            # хвостовой пробел (самый частый случай)
        " " + base,
        " " + base + " ",
        base.rstrip(),
        re.sub(r"\s+", " ", base).strip(),   # схлопнутые пробелы
    ]
    seen: set[str] = set()
    out: list[str] = []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _query(session: requests.Session, name: str, authors_q: str) -> dict | None:
    url = (
        f"{config.STATS_BASE}/games/packages/stats"
        f"?name={urllib.parse.quote(name)}&hash={authors_q}"
    )
    try:
        resp = session.get(url, timeout=config.REQUEST_TIMEOUT)
    except requests.RequestException:
        return None
    if resp.status_code == 404 or not resp.ok:
        return None
    try:
        return resp.json()
    except ValueError:
        return None


def get_package_stats(
    session: requests.Session,
    name: str,
    authors: Iterable[str],
) -> dict | None:
    """Возвращает {'topLevelStats':..., 'questionStats':...} или None, если пакет
    не найден в статистике (404).

    Если точное имя из sibrowser не находится, пробуем варианты с пробелами —
    sibrowser обрезает пробелы, а статистика хранит имя как есть (см. _name_variants).
    """
    authors_q = "".join(
        f"&authors={urllib.parse.quote(a)}" for a in (authors or []) if a
    )
    variants = _name_variants(name)
    for i, nm in enumerate(variants):
        data = _query(session, nm, authors_q)
        if data is not None:
            return data
        if i + 1 < len(variants):
            throttle()   # вежливая пауза между попытками
    return None


def summarize(stats: dict | None) -> dict:
    """Короткая сводка верхнего уровня."""
    if not stats:
        return {"has_stats": False, "started": 0, "completed": 0, "rate": None}
    top = stats.get("topLevelStats", {}) or {}
    started = top.get("startedGameCount") or 0
    completed = top.get("completedGameCount") or 0
    return {
        "has_stats": True,
        "started": started,
        "completed": completed,
        "rate": (completed / started) if started else None,
    }


def throttle() -> None:
    time.sleep(config.STATS_DELAY)
