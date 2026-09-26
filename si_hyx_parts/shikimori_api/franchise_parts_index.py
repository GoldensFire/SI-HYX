# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""franchise_parts_index. Public namespace: shikimori_api."""
from __future__ import annotations
import shikimori_api as _api


def franchise_parts_index(parts) -> float:
    """«Индекс популярности» франшизы по карточкам её частей.

    parts — карточки в GraphQL-форме (`statusesStats`, `airedOn { year }`,
    `releasedOn { year }`, `status`, `score`), обычно самые популярные части
    одной франшизы. База берётся у самой
    популярной части, а сверху две поправки:
      • штраф за возраст смягчается, если у франшизы есть заметное продолжение:
        свежесть считается СРЕДНИМ ГЕОМЕТРИЧЕСКИМ между свежестью самой
        популярной части и свежестью последнего заметного продолжения. Не
        подменяем год целиком нарочно — иначе «Наруто» 2002-го считался бы
        ровесником «Боруто» 2017-го;
      • за каждую заметную часть сверх первой идёт небольшая надбавка
        (FRANCHISE_SEASON_BONUS, не больше FRANCHISE_SEASON_BONUS_MAX): сериал с
        живыми сезонами узнают лучше одиночки с тем же числом зрителей.

    Пустой список или части без статистики — ноль."""
    rows = []
    for part in (parts or []):
        if not isinstance(part, dict):
            continue
        base = _api.index_base_from_statuses_stats(part.get("statusesStats"))
        if base <= 0:
            continue
        try:
            year = int((part.get("airedOn") or {}).get("year") or 0) or None
        except (TypeError, ValueError):
            year = None
        try:
            score = float(part.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        try:
            until = int((part.get("releasedOn") or {}).get("year") or 0) or None
        except (TypeError, ValueError):
            until = None
        going = str(part.get("status") or "").strip().lower() == "ongoing"
        rows.append((base, year, score, until, going))
    if not rows:
        return 0.0
    rows.sort(key=lambda r: r[0], reverse=True)
    top_base, top_year, top_score, top_until, top_going = rows[0]
    notable = [r for r in rows if r[0] >= top_base * _api.FRANCHISE_PART_SHARE]
    years = [r[1] for r in notable if r[1]]
    recency, score_factor = _api.index_factors(top_year, top_score,
                                               until=top_until,
                                               ongoing=top_going)
    if years:
        # У последнего продолжения смотрим только год выхода: кончилось оно или
        # нет, на «франшиза ещё на слуху» уже не влияет.
        late, _ = _api.index_factors(max(years), top_score)
        # max — на случай, когда самая популярная часть и есть самая свежая
        # («Стальной алхимик: Братство» 2009-го против частей 2003-го):
        # приплюсовывать ей старость предшественников нельзя.
        recency = max(recency, _api.math.sqrt(recency * late))
    bonus = 1.0 + min(_api.FRANCHISE_SEASON_BONUS_MAX,
                      _api.FRANCHISE_SEASON_BONUS * (len(notable) - 1))
    return top_base * recency * score_factor * bonus

franchise_parts_index.__module__ = _api.__name__
_api.franchise_parts_index = franchise_parts_index

def kinds_for(content_type: str):
    return _api.MANGA_KINDS if content_type == _api.CONTENT_MANGA else _api.KINDS

kinds_for.__module__ = _api.__name__
_api.kinds_for = kinds_for

def statuses_for(content_type: str):
    return _api.MANGA_STATUSES if content_type == _api.CONTENT_MANGA else _api.STATUSES

statuses_for.__module__ = _api.__name__
_api.statuses_for = statuses_for

def kind_label(content_type: str, kind: str) -> str:
    if content_type == _api.CONTENT_MANGA:
        return _api.MANGA_KIND_LABELS.get(kind, kind)
    return _api.KIND_LABELS.get(kind, kind)

kind_label.__module__ = _api.__name__
_api.kind_label = kind_label

def status_label(content_type: str, status: str) -> str:
    if content_type == _api.CONTENT_MANGA:
        return _api.MANGA_STATUS_LABELS.get(status, status)
    return _api.STATUS_LABELS.get(status, status)

status_label.__module__ = _api.__name__
_api.status_label = status_label
