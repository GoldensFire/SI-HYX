# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
"""Проекты видео, собранных нейросетью, — во вкладку «Монтаж».

montage_tool render (агент, MCP) после сборки кладёт рядом с итогом проект
этого видео — `<итог>.montage.json` (тот же формат montage_project, пути
файлов абсолютные) — и записывает его в журнал JOURNAL_PATH. Вкладка
«Монтаж» следит за журналом: новый проект открывается на таймлайне сам
(пустой проект) или по кнопке в полосе над таймлайном, правки пользователя
сохраняются обратно в этот файл (прежняя версия — `<итог>.bak.montage.json`,
она тоже открывается проектом).

Без PyQt6: модуль берут и headless montage_tool, и вкладка."""
import json
import os
import sys
import time
from pathlib import Path

import montage_project

if sys.platform.startswith("win"):
    _CONFIG_DIR = os.path.join(os.getenv('APPDATA') or str(Path.home()), "unified_media_tool")
else:
    _CONFIG_DIR = os.path.join(str(Path.home()), ".unified_media_tool")

# Та же папка, что config.CONFIG_DIR (config не импортируется: он тянет PyQt6).
JOURNAL_PATH = os.path.join(_CONFIG_DIR, "montage_ai_projects.json")
JOURNAL_MAX = 30
PROJECT_SUFFIX = montage_project.PROJECT_SUFFIX


def _norm(path):
    return os.path.normcase(os.path.abspath(str(path)))


def project_path_for(output):
    """Файл проекта для итога: `D:/clip.mp4` → `D:/clip.montage.json`."""
    stem, _ext = os.path.splitext(os.path.abspath(str(output)))
    return stem + PROJECT_SUFFIX


def absolute_project(project, base=None):
    """Копия проекта с абсолютными путями файлов клипов: относительные
    считаются от base (по умолчанию — текущей папки, как их понял render)."""
    p = project.copy()
    base = os.path.abspath(base or os.getcwd())
    for c in p.clips:
        if c.src and not os.path.isabs(c.src):
            c.src = os.path.normpath(os.path.join(base, c.src))
        if c.audio_path and not os.path.isabs(c.audio_path):
            c.audio_path = os.path.normpath(os.path.join(base, c.audio_path))
    return p


def read_journal(path=None):
    """Записи журнала по времени (старые первыми); битый файл — пустой список."""
    path = path or JOURNAL_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    items = data.get("projects") if isinstance(data, dict) else None
    out = []
    for e in items if isinstance(items, list) else []:
        if not isinstance(e, dict) or not isinstance(e.get("project"), str):
            continue
        try:
            e["time"] = float(e.get("time") or 0.0)
        except (TypeError, ValueError):
            continue
        out.append(e)
    out.sort(key=lambda e: e["time"])
    return out


def _write_journal(entries, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "projects": entries}, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def publish(project, output, source="", preview=False, journal=None):
    """Проект итога output — в `<итог>.montage.json` и в журнал. Запись
    журнала (dict) с полями project, output, source, time, preview, duration."""
    proj_path = project_path_for(output)
    montage_project.save_project(absolute_project(project), proj_path)
    entry = {"project": proj_path, "output": os.path.abspath(str(output)),
             "source": os.path.abspath(str(source)) if source else "",
             "time": time.time(), "preview": bool(preview),
             "duration": round(project.duration(), 3), "clips": len(project.clips)}
    journal = journal or JOURNAL_PATH
    key = _norm(proj_path)
    entries = [e for e in read_journal(journal) if _norm(e["project"]) != key]
    entries.append(entry)
    _write_journal(entries[-JOURNAL_MAX:], journal)
    return entry


def journal_stamp(path=None):
    """Отметка изменения журнала (st_mtime_ns, размер) или None — вкладка
    перечитывает журнал, только когда она сменилась."""
    try:
        st = os.stat(path or JOURNAL_PATH)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size
