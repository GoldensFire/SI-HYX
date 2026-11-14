# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
"""Картинки от нейросети — во вкладку «Редактирование фото».

`photo_tool open <картинка>` (агент, MCP) записывает путь в журнал
JOURNAL_PATH; вкладка «Редактирование фото» следит за журналом и открывает
новую картинку на холсте, где пользователь правит её сам. Как
montage_handoff для «Монтажа». Без PyQt6: модуль берут и photo_tool, и
вкладка."""
import json
import os
import sys
import time
from pathlib import Path

if sys.platform.startswith("win"):
    _CONFIG_DIR = os.path.join(os.getenv('APPDATA') or str(Path.home()), "unified_media_tool")
else:
    _CONFIG_DIR = os.path.join(str(Path.home()), ".unified_media_tool")

# Та же папка, что config.CONFIG_DIR (config не импортируется: он тянет PyQt6).
JOURNAL_PATH = os.path.join(_CONFIG_DIR, "photo_ai_images.json")
JOURNAL_MAX = 30


def read_journal(path=None) -> list:
    """Записи журнала [{'path', 'time', 'note'}], старые первыми."""
    try:
        with open(path or JOURNAL_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    return [e for e in data if isinstance(e, dict) and e.get("path")] \
        if isinstance(data, list) else []


def publish(image_path, note="", journal=None) -> dict:
    """Добавляет картинку в журнал (вкладка откроет её сама)."""
    path = journal or JOURNAL_PATH
    entry = {"path": os.path.abspath(str(image_path)), "time": time.time(),
             "note": str(note or "")}
    entries = (read_journal(path) + [entry])[-JOURNAL_MAX:]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return entry


def journal_stamp(path=None) -> float:
    """Время изменения журнала (0 — журнала нет): дешёвая проверка «что-то новое»."""
    try:
        return os.path.getmtime(path or JOURNAL_PATH)
    except OSError:
        return 0.0
