# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Чтение и запись базы Shikimori ПОРЦИЯМИ, чтобы окно не вставало.

База весит двести с лишним мегабайт. ``json.load`` разбирает её одним вызовом
на C, и все две секунды GIL у рабочего потока: главный поток не получает его
ни разу, окно висит, Windows пишет «Не отвечает» и подменяет его «призраком»
(просьба пользователя: панель базы замирала на открытии, на каждой вкладке и
при обновлении, а после «отвисания» оказывалась за главным окном). То же
самое — декодирование UTF-8 при чтении и ``json.dumps`` при сохранении.

Здесь те же операции идут кусками: словари верхних уровней (разделы, мешки
фильтров, карточки каталога) разбираются по одной записи, и между записями
интерпретатор успевает отдать GIL главному потоку. Результат тот же, что у
``json.loads``/``json.dumps``.

После чтения большой базы её объекты замораживаются (``gc.freeze``): иначе
сборщик мусора на каждом проходе обходил миллионы карточек и сам останавливал
программу на полсекунды — замерено по 0.2–0.45 с за проход, десятки раз.
Данные JSON циклов не образуют и освобождаются счётчиком ссылок и так.
"""
from __future__ import annotations

import codecs
import gc
import json
import re

# Сколько уровней словарей разбирать по записи: сам файл, разделы («anime»,
# «memo»…), мешки фильтров и группы memo, словарь карточек мешка. Сами
# карточки разбираются уже одним вызовом каждая.
DEPTH = 4
# Порция чтения файла: декодирование UTF-8 держит GIL, и мегабайт на раз —
# это миллисекунды, а не секунда на весь файл.
READ_CHUNK = 1 << 20
# С какого размера базу стоит замораживать от сборщика мусора. Маленькие
# файлы (тесты, первая генерация) не трогаем: заморозка касается ВСЕХ живых
# объектов программы, и без выгоды делать её незачем.
FREEZE_BYTES = 20 << 20

_DECODER = json.JSONDecoder()
_SPACE = re.compile(r"[ \t\n\r]*")


def read_text(path: str) -> str:
    """Весь файл как текст, декодируемый по мегабайту."""
    decoder = codecs.getincrementaldecoder("utf-8")()
    parts = []
    with open(path, "rb") as f:
        while True:
            chunk = f.read(READ_CHUNK)
            if not chunk:
                break
            parts.append(decoder.decode(chunk))
        parts.append(decoder.decode(b"", final=True))
    text = "".join(parts)
    return text[1:] if text.startswith("\ufeff") else text


def loads(text: str, depth: int = DEPTH):
    """Как ``json.loads``, но верхние словари — по одной записи."""
    keys: dict = {}
    value, end = _value(text, _skip(text, 0), depth, keys)
    if _skip(text, end) != len(text):
        raise ValueError(f"лишние данные после JSON (позиция {end})")
    return value


def load_file(path: str):
    """Прочитать базу: порциями, без сборщика мусора, с заморозкой в конце."""
    text = read_text(path)
    was_on = gc.isenabled()
    gc.disable()
    try:
        data = loads(text)
    finally:
        if was_on:
            gc.enable()
    if len(text) >= FREEZE_BYTES:
        gc.freeze()
    return data


def dump_parts(value, depth: int = DEPTH) -> list[str]:
    """Как ``json.dumps(..., ensure_ascii=False)``, но списком кусков."""
    out: list[str] = []
    _dump(value, depth, out)
    return out


def _skip(text: str, pos: int) -> int:
    return _SPACE.match(text, pos).end()


def _value(text: str, pos: int, depth: int, keys: dict):
    if depth > 0 and text.startswith("{", pos):
        return _object(text, pos + 1, depth - 1, keys)
    value, end = _DECODER.raw_decode(text, pos)
    if isinstance(value, dict):
        # Ключи карточек общие: один разбор json.loads хранил бы каждый ключ
        # в одном экземпляре, а разбор по записям — в своём у каждой карточки
        # (лишние ~70 МБ на базе). Верхнего уровня карточки для этого хватает.
        value = {keys.setdefault(k, k): v for k, v in value.items()}
    return value, end


def _object(text: str, pos: int, depth: int, keys: dict):
    out: dict = {}
    pos = _skip(text, pos)
    if text.startswith("}", pos):
        return out, pos + 1
    while True:
        if not text.startswith('"', pos):
            raise ValueError(f"ожидался ключ (позиция {pos})")
        key, pos = _DECODER.raw_decode(text, pos)
        pos = _skip(text, pos)
        if not text.startswith(":", pos):
            raise ValueError(f"ожидалось двоеточие (позиция {pos})")
        value, pos = _value(text, _skip(text, pos + 1), depth, keys)
        out[keys.setdefault(key, key)] = value
        pos = _skip(text, pos)
        if text.startswith(",", pos):
            pos = _skip(text, pos + 1)
            continue
        if text.startswith("}", pos):
            return out, pos + 1
        raise ValueError(f"ожидалась запятая или «}}» (позиция {pos})")


def _key(key) -> str:
    """Ключ словаря так, как его записал бы json.dumps."""
    if isinstance(key, str):
        return key
    if key is True or key is False or key is None:
        return json.dumps(key)
    if isinstance(key, float):
        return float.__repr__(key)
    return str(key)


def _dump(value, depth: int, out: list) -> None:
    if depth <= 0 or not isinstance(value, dict):
        out.append(json.dumps(value, ensure_ascii=False))
        return
    out.append("{")
    first = True
    for key, item in value.items():
        if not first:
            out.append(", ")
        first = False
        out.append(json.dumps(_key(key), ensure_ascii=False) + ": ")
        _dump(item, depth - 1, out)
    out.append("}")
