# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# ffmpeg_faststart.py — «-movflags +faststart» у любого видео в MP4/MOV.
#
# Без него индекс (moov) пишется в КОНЕЦ файла, и плеер — SIGame, браузер,
# QtMultimedia — не может начать показ, пока не дочитает файл целиком. С ним
# ffmpeg после записи переносит индекс в начало. Стоит это одного
# дополнительного прохода по уже готовому файлу (просьба пользователя: по
# умолчанию во всей программе).
#
# Применяется там, где команда уходит в процесс: оттуда видно выходной файл, и
# ни один построитель команды не может про флаг забыть.
from __future__ import annotations

import os

# Контейнеры семейства MP4 (muxer mov/mp4): флаг понимают только они. Для MKV
# и WebM он бессмыслен — там индекс устроен иначе.
FASTSTART_EXTS = (".mp4", ".m4v", ".mov", ".3gp", ".3g2")


def with_faststart(cmd) -> list:
    """Команда ffmpeg с «-movflags +faststart» перед выходным файлом.

    Выходной файл — последний аргумент (так строятся все команды программы).
    Команду не трогаем, если флаги mov уже заданы явно (в том числе другие,
    например фрагментированный MP4), если выход — труба («-», «pipe:») или
    контейнер не из семейства MP4."""
    args = list(cmd or ())
    if len(args) < 3 or "-movflags" in args:
        return args
    out = str(args[-1])
    if out.startswith("-") or out.startswith("pipe:"):
        return args
    if os.path.splitext(out)[1].lower() not in FASTSTART_EXTS:
        return args
    return args[:-1] + ["-movflags", "+faststart", args[-1]]
