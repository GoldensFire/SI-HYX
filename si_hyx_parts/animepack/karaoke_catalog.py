# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Тайтлы с готовыми таймингами Karaoke Mugen — первыми под слоты караоке.

Прогоны 9 октября: опенингов вышло 11 и 13 из 16 ровно потому, что 5 и 3
слота караоке так и не дождались песни с готовыми таймингами. Песни шли из
каталога в порядке сложности, тайминги у них находились редко, и первые
песни для караоке доходили до загрузки к 13-й минуте.

Здесь путь обратный: каталог Karaoke Mugen (24 тыс. записей, у ~72 % есть
MAL id) раз в неделю сжимается в индекс «MAL id → песни с таймингами». Среди
тайтлов одного уровня сложности такие идут первыми (CatalogPlan), их не
отдают под кадры, пока свободны слоты караоке (AnimeCardFeed), а из песен
тайтла первой берётся та, что есть в индексе (song_supply.ordered_songs).
Тайминги песни по-прежнему проверяет candidate_availability.probe: индекс
только меняет порядок, ничего не пропускает и не отсеивает.
"""
import json
from pathlib import Path
import re
import threading
import time

import animepack as ap

BASE = "https://kara.moe/api/karas/search"
# 2000 записей — 0,75 МБ сжатого ответа и ~2,5 с; весь каталог — ~13 страниц.
PAGE = 2000
MAX_PAGES = 40
MAX_AGE = 7 * 86400
VERSION = 1
TYPES = {"OP": "opening", "ED": "ending", "IN": "insert"}
_LOCK = threading.Lock()


def _path():
    return Path(ap.SHIKI_CACHE_FILE).parent / "karaoke_mugen_index.json"


def _norm(text):
    return re.sub(r"[\W_]+", "", str(text or "").casefold())


def wanted(settings):
    return bool(getattr(settings, "karaoke_enabled", False)
                and getattr(settings, "karaoke_percent", 0)
                and getattr(settings, "karaoke_effect", "") != "reverse")


def _rows(content):
    """Строки ответа → (MAL id, песня) только для записей с .ass."""
    for row in content:
        lyrics = row.get("lyrics_infos") or []
        if not any(str(item.get("filename", "")).endswith(".ass") for item in lyrics):
            continue
        kinds = [TYPES[tag.get("name")] for tag in row.get("songtypes") or ()
                 if tag.get("name") in TYPES]
        if not kinds:
            continue
        names = {_norm(name) for name in [*(row.get("titles") or {}).values(),
                                          *(row.get("titles_aliases") or ())]}
        names.discard("")
        for mal in row.get("myanimelist_ids") or ():
            if str(mal).isdecimal():
                yield int(mal), {"kind": kinds[0], "names": sorted(names),
                                 "duration": int(row.get("duration") or 0)}


def _fetch(session, stopped):
    index, seen = {}, 0
    for page in range(MAX_PAGES):
        if stopped():
            raise RuntimeError("остановлено")
        response = session.get(BASE, params={"filter": "", "size": PAGE, "from": page * PAGE},
                               timeout=(10, 60))
        response.raise_for_status()
        data = response.json()
        content = data.get("content") or []
        for mal, song in _rows(content):
            index.setdefault(mal, []).append(song)
        seen += len(content)
        total = int((data.get("infos") or {}).get("count") or 0)
        if not content or seen >= total:
            break
    return index


def _load_file():
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, 0.0
    if data.get("version") != VERSION:
        return None, 0.0
    index = {int(mal): songs for mal, songs in (data.get("titles") or {}).items()}
    return index, float(data.get("saved") or 0)


def _save(index):
    target = _path()
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps({"version": VERSION, "saved": time.time(),
                                     "titles": index}, ensure_ascii=False),
                         encoding="utf-8")
    temporary.replace(target)


def start(generator):
    """Индекс — из файла сразу, свежий — фоном раз в неделю; прогон не ждёт."""
    if not wanted(generator.s) or getattr(generator, "_mugen_index_started", False):
        return
    generator._mugen_index_started = True
    index, saved = _load_file()
    if index:
        _apply(generator, index, saved, cached=True)
    if index and time.time() - saved < MAX_AGE:
        return

    def refresh():
        try:
            fresh = _fetch(generator.session, generator.stopped)
        except Exception as error:  # noqa: BLE001 — без индекса порядок прежний
            if not index:
                generator.log(f"Караоке: каталог Karaoke Mugen недоступен ({error}) — "
                              "тайтлы идут обычным порядком.")
            return
        if not fresh:
            return
        try:
            _save(fresh)
        except OSError:
            pass    # индекс — ускорение: без файла он живёт до конца прогона
        _apply(generator, fresh, time.time(), cached=False)

    threading.Thread(target=refresh, name="karaoke-mugen-index", daemon=True).start()


def _apply(generator, index, saved, cached):
    with _LOCK:
        generator._mugen_index = index
        generator._mugen_index_version = getattr(generator, "_mugen_index_version", 0) + 1
    songs = sum(len(rows) for rows in index.values())
    when = time.strftime("%d.%m %H:%M", time.localtime(saved))
    generator.log(f"Караоке: в каталоге Karaoke Mugen {len(index)} аниме с готовыми "
                  f"таймингами ({songs} песен; {'из файла от ' + when if cached else 'обновлён'}) "
                  "— такие тайтлы идут под караоке первыми.")


def index_of(generator):
    return getattr(generator, "_mugen_index", None) or {}


def has_timed(generator, mal):
    return int(mal or 0) in index_of(generator)


def song_timed(generator, mal, song):
    """Есть ли в индексе эта песня тайтла: тот же род и совпавшее название."""
    rows = index_of(generator).get(int(mal or 0))
    if not rows:
        return False
    kind = ap.song_kind(song.get("songType"))
    name = _norm(song.get("songName"))
    return bool(name) and any(row["kind"] == kind and name in row["names"] for row in rows)


def karaoke_free(generator):
    """Слоты караоке ещё ждут песню (свободны или освободились после неудачи)."""
    slots = getattr(generator, "_effect_slots", None)
    if slots is None:
        return wanted(generator.s)
    return any(slots.slots[slot] == "karaoke" for slot in slots.free)
