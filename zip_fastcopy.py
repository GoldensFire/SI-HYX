# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# zip_fastcopy.py — перенос записи из архива в архив КАК ЕСТЬ, без распаковки.
#
# Пересборка .siq нужна почти на каждое действие редактора (правка вопроса,
# добавление и удаление медиа), а весит пак десятки-сотни мегабайт уже сжатого
# mp3/mp4/avif. Распаковать это и тут же сжать обратно тем же дефлейтом дороже
# всей остальной работы, а результат байт в байт тот же — этим и занимается
# copy_zip_entry.
#
# Общий модуль: одним и тем же приёмом пересобирают пак и «Апгрейд аниме-пака»
# (animepack_upgrade), и вкладка SiQuesterHYX (siquester/siq_package.py,
# siquester/widgets_question.py).
from __future__ import annotations

import copy
import struct
import zipfile
from typing import Optional

# Сколько байт за раз льём из архива в архив: запись бывает и в полсотни
# мегабайт (ролик), держать её в памяти целиком незачем.
_COPY_CHUNK = 1 << 20
# Флаги записи, при которых в чужие байты лучше не лезть: 0x01 — запись
# зашифрована, 0x08 — размеры лежат не в заголовке, а в дескрипторе за данными
# (второе мы чиним сами, размеры-то известны из центрального каталога).
_FLAG_ENCRYPTED, _FLAG_DESCRIPTOR = 0x01, 0x08


def copy_zip_entry(src: zipfile.ZipFile, dst: zipfile.ZipFile,
                   info: zipfile.ZipInfo, name: Optional[str] = None) -> bool:
    """Переносит запись из архива в архив КАК ЕСТЬ, не распаковывая.

    zipfile так не умеет: и writestr(info, src.read(...)), и связка
    src.open(info) → dst.open(info, 'w') честно разжимают запись и жмут её
    обратно тем же дефлейтом. В паке это сотня мегабайт уже сжатого mp3/mp4, и
    на них уходило больше времени, чем на всю остальную работу (замер на
    «Anime 3 season.siq», 75 МБ: 4,9 с против 0,11 с здесь; файл на выходе байт
    в байт тот же).

    Запись кладётся с теми же датой, атрибутами и способом сжатия, что были в
    исходном архиве; *name* задаёт другое имя в новом архиве (остальное
    берётся из *info*).

    False — по-быстрому не вышло (шифрованная запись, zip64, битый заголовок):
    зовущий кладёт её обычным путём."""
    if (info.flag_bits & _FLAG_ENCRYPTED
            or info.compress_size > zipfile.ZIP64_LIMIT
            or info.file_size > zipfile.ZIP64_LIMIT):
        return False
    src_fp, dst_fp = src.fp, dst.fp
    if src_fp is None or dst_fp is None:  # pragma: no cover — архив уже закрыт
        return False
    # Недописанную запись мы откатываем seek+truncate; если поток этого не
    # умеет (архив пишется в трубу), то и пробовать нельзя — оборвавшийся
    # перенос уже не убрать.
    seekable = getattr(dst_fp, "seekable", None)
    if not callable(seekable) or not seekable():  # pragma: no cover — не наш случай
        return False
    start = dst_fp.tell()
    try:
        src_fp.seek(info.header_offset)
        fields = struct.unpack(zipfile.structFileHeader,
                               src_fp.read(zipfile.sizeFileHeader))
        if fields[zipfile._FH_SIGNATURE] != zipfile.stringFileHeader:
            return False
        # Имя и «дополнительное поле» в локальном заголовке свои: их длина с
        # центральным каталогом совпадать не обязана, поэтому берём из него.
        src_fp.seek(fields[zipfile._FH_FILENAME_LENGTH]
                    + fields[zipfile._FH_EXTRA_FIELD_LENGTH], 1)
        zi = copy.copy(info)
        if name:
            zi.filename = name
        zi.flag_bits &= ~_FLAG_DESCRIPTOR
        zi.header_offset = start
        dst_fp.write(zi.FileHeader(False))
        left = int(info.compress_size)
        while left > 0:
            chunk = src_fp.read(min(_COPY_CHUNK, left))
            if not chunk:
                raise zipfile.BadZipFile(f"запись оборвалась: {info.filename}")
            dst_fp.write(chunk)
            left -= len(chunk)
    except Exception:  # noqa: BLE001 — не вышло по-быстрому, положат обычным путём
        dst_fp.seek(start)
        dst_fp.truncate()
        return False
    dst.start_dir = dst_fp.tell()
    dst.filelist.append(zi)
    dst.NameToInfo[zi.filename] = zi
    dst._didModify = True
    return True
