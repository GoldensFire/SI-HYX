# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""copy_zip_entry. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


def copy_zip_entry(src: _api.zipfile.ZipFile, dst: _api.zipfile.ZipFile,
                   info: _api.zipfile.ZipInfo, name: _api.Optional[str] = None) -> bool:
    """Переносит запись из архива в архив КАК ЕСТЬ, не распаковывая.

    zipfile так не умеет: writestr(info, src.read(...)) честно разжимает запись
    и жмёт её обратно тем же дефлейтом. В паке это сотня мегабайт уже сжатого
    mp3/mp4, и на них уходило больше времени, чем на всю остальную работу
    (замер на «Anime 3 season.siq», 75 МБ: 4,9 с против 0,11 с здесь; файл на
    выходе байт в байт тот же).

    False — по-быстрому не вышло (шифрованная запись, zip64, битый заголовок):
    зовущий кладёт её обычным путём."""
    if (info.flag_bits & _api._FLAG_ENCRYPTED
            or info.compress_size > _api.zipfile.ZIP64_LIMIT
            or info.file_size > _api.zipfile.ZIP64_LIMIT):
        return False
    src_fp, dst_fp = src.fp, dst.fp
    if src_fp is None or dst_fp is None:  # pragma: no cover — архив уже закрыт
        return False
    start = dst_fp.tell()
    try:
        src_fp.seek(info.header_offset)
        fields = _api.struct.unpack(_api.zipfile.structFileHeader,
                               src_fp.read(_api.zipfile.sizeFileHeader))
        if fields[_api.zipfile._FH_SIGNATURE] != _api.zipfile.stringFileHeader:
            return False
        # Имя и «дополнительное поле» в локальном заголовке свои: их длина с
        # центральным каталогом совпадать не обязана, поэтому берём из него.
        src_fp.seek(fields[_api.zipfile._FH_FILENAME_LENGTH]
                    + fields[_api.zipfile._FH_EXTRA_FIELD_LENGTH], 1)
        zi = _api.copy.copy(info)
        if name:
            zi.filename = name
        zi.flag_bits &= ~_api._FLAG_DESCRIPTOR
        zi.header_offset = start
        dst_fp.write(zi.FileHeader(False))
        left = int(info.compress_size)
        while left > 0:
            chunk = src_fp.read(min(_api._COPY_CHUNK, left))
            if not chunk:
                raise _api.zipfile.BadZipFile(f"запись оборвалась: {info.filename}")
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

copy_zip_entry.__module__ = _api.__name__
_api.copy_zip_entry = copy_zip_entry

def fmt_size(num: int) -> str:
    """«1,8 МБ», «412 КБ» — для отчёта об изменениях."""
    mb = float(num) / (1024 * 1024)
    if mb >= 1.0:
        return f"{mb:.1f} МБ".replace(".", ",")
    return f"{max(1, int(round(float(num) / 1024)))} КБ"

fmt_size.__module__ = _api.__name__
_api.fmt_size = fmt_size

def _temp_dir() -> str:
    """Куда класть промежуточные файлы кодирования (общая папка приложения)."""
    try:
        from config import TEMP_DIR
        _api.os.makedirs(TEMP_DIR, exist_ok=True)
        return str(TEMP_DIR)
    except Exception:  # pragma: no cover — модуль должен жить и без приложения
        import tempfile
        return tempfile.gettempdir()

_temp_dir.__module__ = _api.__name__
_api._temp_dir = _temp_dir

def question_price(q_el: _api.ET.Element) -> int:
    try:
        return int(q_el.get("price") or 0)
    except (TypeError, ValueError):
        return 0

question_price.__module__ = _api.__name__
_api.question_price = question_price

# ─────────────────────────────────────────────────────────────────────────────
# Функция 1: спецвопрос → обычный
# ─────────────────────────────────────────────────────────────────────────────
def special_key(q_el: _api.ET.Element) -> _api.Optional[str]:
    """Ключ спецвопроса (см. SPECIAL_TYPES) или None у обычного.

    v5 держит тип в атрибуте, v4 — в дочернем <type name="cat">."""
    kind = (q_el.get("type") or "").strip().lower()
    if not kind:
        t = _api.child(q_el, "type")
        kind = ((t.get("name") if t is not None else "") or "").strip().lower()
    return _api.SPECIAL_TYPES.get(kind)

special_key.__module__ = _api.__name__
_api.special_key = special_key

def has_question_content(q_el: _api.ET.Element) -> bool:
    """Есть ли у вопроса он сам — текст, картинка, звук или ролик.

    У «кота в мешке без вопроса» его нет вовсе (игрок просто получает деньги):
    обычным такой вопрос не станет, сколько тип ни снимай."""
    for params in _api.children(q_el, "params"):
        for param in _api.children(params, "param"):
            if (param.get("name") or "") != "question":
                continue
            if len(param) or (param.text or "").strip():
                return True
    scenario = _api.child(q_el, "scenario")             # формат v4
    if scenario is not None and (len(scenario) or (scenario.text or "").strip()):
        return True
    return False

has_question_content.__module__ = _api.__name__
_api.has_question_content = has_question_content

def make_simple(q_el: _api.ET.Element) -> None:
    """Снимает с вопроса всё, что делало его спецвопросом.

    v5: убираем атрибут type и параметры спецвопроса (тема/цена кота, минимум
    ставки, режим выбора). v4: убираем дочерний <type> целиком — вместе с его
    параметрами, они внутри. Сам вопрос, ответы и цена не трогаются."""
    if q_el.get("type") is not None:
        del q_el.attrib["type"]
    for params in _api.children(q_el, "params"):
        for param in list(params):
            if (param.get("name") or "") in _api.SPECIAL_PARAMS:
                params.remove(param)
    for type_el in _api.children(q_el, "type"):
        q_el.remove(type_el)

make_simple.__module__ = _api.__name__
_api.make_simple = make_simple
