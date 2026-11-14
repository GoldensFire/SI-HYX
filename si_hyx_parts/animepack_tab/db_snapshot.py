# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Снимок таблиц панели базы на диске: панель открывается сразу.

Каждое открытие панели заново разбирало базу (270+ МБ) и считало индекс,
уровень и цену у всех ~100 тысяч тайтлов — две-три минуты «Собираю
таблицу…» (просьба пользователя: «Обновить базу» открывалась слишком долго).
Показ по 200 строк тут не помогал: долго шёл счёт, а не вывод.

Теперь посчитанные строки (без карточек и кандидатов — только то, что видно
в таблице, и имена для поиска) кладутся рядом с базой. Открытие панели
показывает снимок за секунды, а полный пересчёт идёт в фоне, только если с
тех пор менялись файлы базы или памяти (или нажали «Перечитать с диска»).

Формат — JSON Lines: первая строка — заголовок с отметкой файлов базы и
именами полей, дальше по строке на строку таблицы: [родитель, значения полей
по порядку заголовка, поля сверх них]. Имена не повторяются в каждой строке —
файл меньше и разбирается быстрее. Разбор по строке отдаёт GIL главному
потоку между записями, и окно на чтении не замирает.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# Меняется вместе с формулами индекса/цены или составом строк: старый снимок
# тогда не показывается вовсе.
VERSION = 2
FOLDER = "db_panel_snapshot"
TARGETS = ("anime", "manga", "chars", "counts")
# Тяжёлые объекты строки: в снимок не идут (подсказки появятся после
# фонового пересчёта, когда строки снова будут живыми).
_HEAVY = ("card", "candidate")
_NAME_KEYS = ("russian", "name", "english", "japanese", "licenseNameRu")


def _folder(cache) -> Path | None:
    where = getattr(cache, "path", None)
    return Path(where).parent / FOLDER if where else None


def _file(cache, target: str) -> Path | None:
    if target not in TARGETS:
        raise ValueError(f"неизвестная часть снимка: {target}")
    folder = _folder(cache)
    return folder / f"{target}.jsonl" if folder is not None else None


def stamp(cache) -> list:
    """Отметка файлов, из которых считаются таблицы: база и её память."""
    where = getattr(cache, "path", None)
    if not where:
        return []
    out = []
    for name in (where, f"{where}.memo.sqlite", f"{where}.memo.sqlite-wal"):
        try:
            st = os.stat(name)
            out.append([int(st.st_mtime_ns), int(st.st_size)])
        except OSError:
            out.append(None)
    return out


def row_names(row) -> list:
    """Названия тайтла для поиска (русское, английское, синонимы…)."""
    names = row.get("_names")
    if isinstance(names, list):
        return names
    card = row.get("card") or getattr(row.get("candidate"), "anime", {})
    if not isinstance(card, dict):
        return []
    out = [card.get(key) for key in _NAME_KEYS]
    out.extend(card.get("synonyms") or [])
    return [str(name) for name in out if name]


def _light(row) -> dict:
    out = {key: value for key, value in row.items() if key not in _HEAVY}
    out["_names"] = row_names(row)
    return out


def save_page(cache, target: str, made_stamp, rows, parents=None,
              sort_by: int = 0) -> bool:
    """Записать посчитанную вкладку. made_stamp — отметка ДО начала счёта:
    если база менялась, пока считали, снимок сразу окажется устаревшим."""
    path = _file(cache, target)
    if path is None:
        return False
    rows = [_light(row) for row in rows]
    keys = list(rows[0]) if rows else []
    header_keys = set(keys)
    header = {"version": VERSION, "stamp": made_stamp, "target": target,
              "sort_by": int(sort_by), "tree": parents is not None,
              "keys": keys}
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(header, ensure_ascii=False) + "\n")
            for number, row in enumerate(rows):
                parent = int(parents[number]) if parents is not None else -1
                line = [parent, [row.get(key) for key in keys]]
                # Поля сверх заголовка (у строки-франшизы) — отдельным словарём.
                extra = {key: value for key, value in row.items()
                         if key not in header_keys}
                if extra:
                    line.append(extra)
                stream.write(json.dumps(line, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except (OSError, TypeError, ValueError):
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True


def save_counts(cache, made_stamp, counts: dict) -> bool:
    path = _file(cache, "counts")
    if path is None:
        return False
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps({"version": VERSION, "stamp": made_stamp,
                                     "target": "counts"}) + "\n")
            stream.write(json.dumps(counts, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except (OSError, TypeError, ValueError):
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True


def _header(stream, target: str):
    try:
        header = json.loads(stream.readline())
    except ValueError:
        return None
    if (not isinstance(header, dict) or header.get("version") != VERSION
            or header.get("target") != target):
        return None
    return header


def load_page(cache, target: str):
    """(строки, родители или None, колонка сортировки, устарел ли) или None."""
    path = _file(cache, target)
    if path is None:
        return None
    rows, parents = [], []
    try:
        with open(path, "r", encoding="utf-8") as stream:
            header = _header(stream, target)
            if header is None:
                return None
            keys = [str(key) for key in header.get("keys") or []]
            for line in stream:
                parent, values, *extra = json.loads(line)
                row = dict(zip(keys, values))
                if extra and isinstance(extra[0], dict):
                    row.update(extra[0])
                parents.append(int(parent))
                rows.append(row)
    except (OSError, ValueError, TypeError):
        return None
    stale = header.get("stamp") != stamp(cache)
    return (rows, parents if header.get("tree") else None,
            int(header.get("sort_by") or 0), stale)


def load_counts(cache):
    """(счётчики частей, устарели ли) или None."""
    path = _file(cache, "counts")
    if path is None:
        return None
    try:
        with open(path, "r", encoding="utf-8") as stream:
            header = _header(stream, "counts")
            if header is None:
                return None
            counts = json.loads(stream.readline())
    except (OSError, ValueError):
        return None
    if not isinstance(counts, dict):
        return None
    return counts, header.get("stamp") != stamp(cache)
