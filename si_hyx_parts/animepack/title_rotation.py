# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Порядок каталога: сначала франшиза, затем её часть; недавние части реже.

Перемешанный список карточек давал франшизе столько шансов, сколько у неё
частей в пуле: десяток фильмов и спешлов «Повелителя» тянули его в пак чаще
одиночек и вытесняли основную историю. Здесь каждая франшиза получает одно
место в круге: круг первый — по одной части от каждой франшизы в случайном
порядке, круг второй — следующие части и так далее. Часть внутри франшизы
выбирается жребием с весами: основной сезон весомее короткого ответвления,
популярная часть — весомее малоизвестной, недавно бывшая в паке — легче.

Память точных вопросов («не повторять») не мешает задать тот же тайтл другим
кадром. Память тайтлов хранит номер пака, в котором часть была последний
раз: любимая франшиза остаётся в игре, а её сезоны и фильмы чередуются.
"""
from __future__ import annotations

import json
import os
import time

import animepack as _api
from .franchise_part_weight import is_main_part

HISTORY_NAME = "animepack_title_history.json"
MAX_TITLES = 20000
MAIN_WEIGHT = 4.0
SIDE_WEIGHT = 1.0
# Вес части, бывшей в паке n паков назад: 1 − RECENT_CUT·RECENT_DECAY^(n−1).
RECENT_CUT = 0.85
RECENT_DECAY = 0.6


def history_path() -> str:
    """Рядом с кэшем каталога: тесты подменяют его путь, и историю туда же."""
    return os.path.join(os.path.dirname(_api.SHIKI_CACHE_FILE), HISTORY_NAME)


def load() -> dict:
    try:
        with open(history_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {"seq": 0, "titles": {}}
    if not isinstance(data, dict) or not isinstance(data.get("titles"), dict):
        return {"seq": 0, "titles": {}}
    return data


def record(songs: list) -> int:
    """Запоминает аниме-тайтлы собранного пака; отдаёт номер пака в истории."""
    titles = {}
    for cand in songs:
        if cand.is_manga or not cand.mal_id:
            continue
        titles.setdefault(str(cand.mal_id), []).append(cand.kind)
    if not titles:
        return 0
    data = load()
    seq = int(data.get("seq") or 0) + 1
    now = time.time()
    store = data["titles"]
    for mal, kinds in titles.items():
        store[mal] = {"seq": seq, "time": now, "kinds": sorted(set(kinds))}
    if len(store) > MAX_TITLES:
        keep = sorted(store, key=lambda k: store[k].get("seq", 0))[-MAX_TITLES:]
        store = {k: store[k] for k in keep}
    path = history_path()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"seq": seq, "titles": store}, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        return 0
    return seq


def recency(entry, seq: int) -> float:
    """Множитель веса части, бывшей в паке (1 — давно или никогда)."""
    if not isinstance(entry, dict):
        return 1.0
    ago = seq - int(entry.get("seq") or 0)
    if ago < 0:
        return 1.0
    return 1.0 - RECENT_CUT * RECENT_DECAY ** max(0, ago - 1)


def _base(card) -> float:
    return _api.index_base_from_statuses_stats((card or {}).get("statusesStats"))


def part_weight(card: dict, top_base: float, entry, seq: int) -> float:
    kind = MAIN_WEIGHT if is_main_part(card) else SIDE_WEIGHT
    share = _base(card) / top_base if top_base > 0 else 0.0
    return kind * (0.5 + min(1.0, share)) * recency(entry, seq)


def franchise_first(ids: list, cards: dict, rng, history=None) -> list:
    """Порядок id: круги по франшизам, внутри — части по весам."""
    history = load() if history is None else history
    seq = int(history.get("seq") or 0)
    titles = history.get("titles") or {}
    groups: dict[str, list] = {}
    order: list[str] = []
    for mal in ids:
        card = cards.get(mal) or {}
        key = str(card.get("franchise") or "").strip() or f"#{mal}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(mal)
    rounds: list[list] = []
    for key in order:
        members = groups[key]
        top = max((_base(cards.get(m)) for m in members), default=0.0)
        # Взвешенная выборка без возвращения (ключ u^(1/w)).
        keyed = []
        for mal in members:
            weight = max(1e-6, part_weight(cards.get(mal) or {}, top,
                                           titles.get(str(mal)), seq + 1))
            keyed.append((rng.random() ** (1.0 / weight), mal))
        keyed.sort(reverse=True)
        for depth, (_key, mal) in enumerate(keyed):
            if depth == len(rounds):
                rounds.append([])
            rounds[depth].append(mal)
    out = []
    for layer in rounds:
        rng.shuffle(layer)
        out.extend(layer)
    return out
