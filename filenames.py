# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# filenames.py — как называть скачиваемые файлы. Общее правило: имя файла = имя
# с сайта, из которого убрано ТОЛЬКО то, что не разрешает файловая система
# (по просьбе — «пусть все файлы что скачиваются именуются так, как на сайте»).
# Раньше каждый загрузчик резал имя своим регулярным выражением по белому списку
# \w, и «Аниме пак(изи)» превращалось в «Аниме пак_изи_».
#
# Без единой зависимости (как siq_duration.py), чтобы модуль годился и там, где
# нет Qt.
from __future__ import annotations
import os
import re
from pathlib import Path
from urllib.parse import quote

# Символы, запрещённые в именах файлов Windows (и косая черта — в любой ОС).
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WS = re.compile(r"\s+")
# Имена устройств DOS: файл «CON.siq» создать нельзя даже сегодня.
_RESERVED = {"CON", "PRN", "AUX", "NUL",
             *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}
# Больше и не надо: полный путь в Windows ограничен 260 символами, а к имени
# ещё добавляются папка и расширение.
_MAX_LEN = 120


def safe_filename(name: str, fallback: str = "файл", max_len: int = _MAX_LEN) -> str:
    """Имя с сайта → имя файла: скобки, запятые, эмодзи и регистр сохраняются.

    Убираются только запрещённые символы (заменяются пробелом, чтобы «Пак:
    начало» не склеилось в «Пакначало»), концевые точки и пробелы (Windows их
    молча срезает сам) и имена DOS-устройств. Расширение сюда не передавать —
    точка внутри имени законна.
    """
    text = _WS.sub(" ", _FORBIDDEN.sub(" ", str(name or ""))).strip(" .")
    if len(text) > max_len:
        text = text[:max_len].strip(" .")
    if not text:
        return safe_filename(fallback, "файл", max_len) if fallback else "файл"
    if text.upper() in _RESERVED:
        text += "_"
    return text


def unique_path(path: Path) -> Path:
    """Свободное имя рядом с занятым: «Пак.siq» → «Пак (2).siq».

    Нужно там, где имя больше не уникально само по себе (раньше уникальность
    давал номер пакета в начале имени)."""
    path = Path(path)
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    for n in range(2, 1000):
        candidate = parent / f"{stem} ({n}){suffix}"
        if not candidate.exists():
            return candidate
    return parent / f"{stem} ({os.getpid()}){suffix}"  # практически недостижимо


# Символы, которые .NET Uri.EscapeUriString НЕ кодирует: к обычным «незаписанным»
# (буквы, цифры и -._~, их Python не трогает сам) добавлены «зарезервированные»
# RFC 3986 — ;/?:@&=+$,#[]!'()*
_URI_SAFE = "!#$&'()*+,/:;=?@[]"


def escape_uri_string(name: str) -> str:
    """Имя файла → имя записи в .siq, ровно как это делает SIGame.

    Внутри архива SIQuester пишет имена percent-кодированными, а SIGame ищет
    файл по имени из content.xml, прогоняя его через Uri.EscapeUriString
    (SIDocument.TryGetMedia). Эта функция кодирует ПРОБЕЛЫ и не-ASCII, но
    оставляет как есть скобки, запятые, восклицательный знак и прочие
    «зарезервированные» символы: «Kiss of Death (Darling in the FranXX OP).opus»
    → «Kiss%20of%20Death%20(Darling%20in%20the%20FranXX%20OP).opus».

    urllib.parse.quote(name, safe="") так не умеет: скобки он превращает в
    %28/%29, имя записи перестаёт совпадать с тем, что ищет игра, и вопрос
    падает с «File ... was not found in the game package!».
    """
    return quote(str(name or ""), safe=_URI_SAFE)
