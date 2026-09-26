# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Анонсированный тайтл. Public namespace: animepack.

Из анонсов пак не берёт НИЧЕГО (просьба пользователя): ни кадров, ни песен,
ни персонажей, ни кадров для студии. У анонса нет ни серий, ни зрителей —
игроки его не смотрели, а кадры с постером у него рекламные.

Статус приходит и из GraphQL (`status: "anons"`), и из REST
(`/api/characters/:id` — строки произведений). У карточек из старой базы
поля status нет вовсе — тогда анонсом считается тайтл, чей показ начнётся
позже сегодняшнего дня (по airedOn / aired_on).
"""
from __future__ import annotations

import datetime as _dt

import animepack as _api

ANNOUNCED_STATUSES = frozenset({"anons", "announced"})


def is_announced(card) -> bool:
    """Карточка Shikimori (GraphQL или REST) — анонс, а не вышедший тайтл."""
    if not isinstance(card, dict):
        return False
    status = str(card.get("status") or "").strip().lower()
    if status:
        return status in ANNOUNCED_STATUSES
    start = _start_date(card)
    return start is not None and start > _dt.date.today()


def _start_date(card: dict):
    """Дата начала показа или None, если она неизвестна."""
    aired = card.get("airedOn")
    if isinstance(aired, dict):
        try:
            year = int(aired.get("year") or 0)
        except (TypeError, ValueError):
            return None
        if not year:
            return None
        try:
            return _dt.date(year, int(aired.get("month") or 1),
                            int(aired.get("day") or 1))
        except (TypeError, ValueError):
            return _dt.date(year, 1, 1)
    text = str(card.get("aired_on") or "")
    try:
        return _dt.date.fromisoformat(text[:10]) if text else None
    except ValueError:
        return None


is_announced.__module__ = _api.__name__
_api.is_announced = is_announced
