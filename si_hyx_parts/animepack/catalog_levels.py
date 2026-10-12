# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Заготовка уровней каталога: считается при «Обновить базу», читается генерацией.

Уровень тайтла (1…15) зависит только от базы: карточка, «в избранном», части
франшизы, экранизация книги и русская популярность. От настроек пака он не
зависит. Раньше каждая генерация считала его заново для всего каталога —
12 тысяч аниме и 55 тысяч книг: первый кандидат аниме появлялся через ~20 с
после старта, план книг был готов через ~40 с (замер 2026-10-08).

Заготовка нужна только для РАСКЛАДКИ каталога по уровням (CatalogPlan). Сам
кандидат по-прежнему собирается из живой базы, когда до него доходит очередь,
и средняя, рамки и доли считаются по его настоящему уровню. Устаревшая
заготовка поэтому ничего не ломает: карточка лишь попадёт в соседнюю по
уровню очередь. Карточки, которых в заготовке нет (новые), считаются на месте.

Там же лежит, какие книги нашлись в сохранённых каталогах ReManga и MangaLib
(manga_source_candidates): сопоставление названий 63 тысяч карточек стоило
~5 с на каждом старте.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time

VERSION = 1
NAME = "catalog_levels.json"
# Тот же срок, что у сохранённых каталогов ReManga/MangaLib: дольше уровни
# заметно расходятся с базой (возраст тайтлов, новые «в избранном»).
MAX_AGE = 30 * 86400

_lock = threading.Lock()
_loaded: dict = {}


def path(generator):
    where = getattr(getattr(generator, "db_cache", None), "path", None)
    return Path(where).parent / NAME if where else None


def entry(candidate) -> list:
    """[уровень, экранизована ли книга, неполный ли профиль].

    Уровень — по формуле, а не candidate.level: во время чужой генерации тот
    вернул бы прежнюю заготовку."""
    import animepack as ap
    return [int(ap.index_level(candidate.index)), int(bool(candidate.adapted_from)),
            int(bool(candidate._profile_incomplete))]


def _parse(raw):
    if not isinstance(raw, dict) or raw.get("version") != VERSION:
        return None
    try:
        data = {"made": float(raw["made"])}
        for target in ("anime", "manga"):
            data[target] = {int(k): (int(v[0]), bool(v[1]), bool(v[2]))
                            for k, v in (raw.get(target) or {}).items()}
        data["readers"] = {
            source: {verdict: set(map(int, found.get(verdict) or ()))
                     for verdict in ("ok", "adult")}
            for source, found in (raw.get("readers") or {}).items()}
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        return None
    return data


def load(generator):
    """Действующая заготовка или None (нет, испорчена, старше MAX_AGE)."""
    target = path(generator)
    if target is None:
        return None
    try:
        st = target.stat()
    except OSError:
        return None
    stamp = (st.st_mtime_ns, st.st_size)
    with _lock:
        known = _loaded.get(str(target))
        if known is not None and known[0] == stamp:
            data = known[1]
        else:
            try:
                data = _parse(json.loads(target.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                data = None
            _loaded[str(target)] = (stamp, data)
    if data is None or time.time() - data["made"] > MAX_AGE:
        return None
    return data


# Уровни идущей генерации: {книга ли: {id: (уровень, …)}}. Пока они заданы,
# SongCandidate.level берёт уровень отсюда и не считает его заново.
_active = None


def activate(generator) -> bool:
    """С начала генерации уровни тайтлов берутся из заготовки."""
    global _active
    data = load(generator)
    _active = {False: data["anime"], True: data["manga"]} if data else None
    if data:
        made = time.strftime("%d.%m %H:%M", time.localtime(data["made"]))
        generator.log(f"Уровни тайтлов — из заготовки «Обновить базу» от {made} "
                      f"(аниме {len(data['anime'])}, книги {len(data['manga'])}); "
                      "считаются только карточки, которых в ней нет.")
    return bool(data)


def deactivate() -> None:
    global _active
    _active = None


def ready_level(candidate):
    """Заготовленный уровень карточки кандидата или None."""
    table = _active
    if table is None:
        return None
    card = candidate.anime or {}
    try:
        ident = int(card.get("malId") or card.get("id") or 0)
    except (AttributeError, TypeError, ValueError):
        return None
    known = table[candidate.media == "manga"].get(ident)
    return known[0] if known else None


def _write(target: Path, payload: dict) -> None:
    tmp = target.with_name(target.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, target)


def rebuild(generator) -> bool:
    """Считает уровни всех карточек базы и сохраняет их (после «Обновить базу»)."""
    target = path(generator)
    if target is None:
        return False
    import animepack as ap
    from .catalog_profiles import CachedProfiles
    from .manga_source_candidates import reader_matches
    started = time.monotonic()
    ap.install_favorites_norms(generator.db_cache)
    payload = {"version": VERSION, "made": time.time()}
    cards = {}
    for name, manga in (("anime", False), ("manga", True)):
        index = CachedProfiles(generator, manga)
        rows = {}
        for ident in list(index.cards):
            if generator.stopped():
                return False
            candidate = index.get(ident)
            if candidate is not None:
                rows[str(ident)] = entry(candidate)
        index.flush()
        payload[name] = rows
        cards = index.cards
    readers = reader_matches(generator, cards)
    payload["readers"] = {source: {verdict: sorted(found[verdict]) for verdict in found}
                          for source, found in readers.items()}
    target.parent.mkdir(parents=True, exist_ok=True)
    _write(target, payload)
    generator.log(f"Уровни каталога заготовлены: аниме {len(payload['anime'])}, "
                  f"книги {len(payload['manga'])} за {time.monotonic() - started:.0f} с — "
                  "генерация больше не считает их на старте.")
    return True
