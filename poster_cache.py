# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# poster_cache.py — ОБЩАЯ кладовая обложек на диске.
#
# Постер тайтла нужен обоим аниме-вкладкам сразу: генератор кладёт его в ответ
# каждого вопроса, апгрейд — в ответы чужого пака. Раньше каждая из них качала
# его заново, хотя картинка у тайтла одна и та же и не меняется годами. Теперь
# скачанное складывается сюда, и оба места берут обложки ОТСЮДА (просьба
# пользователя: «пусть оба тянут с одного и того же места»).
#
# Хранятся ИСХОДНЫЕ байты (jpg/png/webp), а не готовый AVIF: лимит по весу и
# скорость кодирования у вкладок свои, и одно и то же изображение они ужимают
# по-разному. Ключ — вид записи плюс её номер («anime:20»), а не ссылка: у
# Shikimori и TMDB ссылки разные, а обложка нужна одна.
#
# Qt здесь нет нарочно: модуль зовут и генератор, и апгрейд, и тесты.
from __future__ import annotations

import os
import re
import threading
from typing import Optional

try:
    from config import CONFIG_DIR
except Exception:  # pragma: no cover — модуль должен жить и без приложения
    CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".si-hyx")

# Папка с обложками лежит рядом с настройками — там же, где кэш каталога
# Shikimori и память о показанных кадрах.
POSTER_CACHE_DIR = os.path.join(CONFIG_DIR, "animepack_posters")

# Сколько всего мегабайт держим. Постер весит 100–400 КБ, так что даже сотня
# мегабайт — это несколько сотен тайтлов; вылезли за потолок — выбрасываем самые
# давние по времени последнего ОБРАЩЕНИЯ (не скачивания): часто нужные обложки
# так остаются, а разовые уходят.
POSTER_CACHE_MB = 200

_LOCK = threading.Lock()
_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
_SAFE = re.compile(r"[^a-z0-9_-]+")


def anime_key(mal_id, book: bool = False) -> str:
    """Ключ обложки тайтла. Номера у аниме и манги свои, поэтому вид записи
    входит в ключ: иначе манга №20 забрала бы себе постер аниме №20."""
    num = str(mal_id or "").strip()
    if not num or num == "0":
        return ""
    return f"{'manga' if book else 'anime'}_{num}"


def character_key(char_id) -> str:
    """Ключ портрета персонажа (вопрос-персонаж и вопрос по манге)."""
    num = str(char_id or "").strip()
    if not num or num == "0":
        return ""
    return f"character_{num}"


def cache_dir() -> str:
    """Папка кэша (создаётся при первом обращении)."""
    try:
        os.makedirs(POSTER_CACHE_DIR, exist_ok=True)
    except OSError:  # pragma: no cover — некуда писать, работаем без кэша
        pass
    return POSTER_CACHE_DIR


def _name(key: str, ext: str) -> str:
    safe = _SAFE.sub("_", str(key or "").strip().lower()).strip("_")
    return f"{safe}{ext}" if safe else ""


def find(key: str) -> tuple[bytes, str]:
    """Обложка из кладовой: (байты, расширение). Нет такой — (b"", "").

    Заодно подновляется время обращения к файлу: по нему потом решается, кого
    выбрасывать при переполнении."""
    if not key:
        return b"", ""
    for ext in _EXTS:
        name = _name(key, ext)
        if not name:
            return b"", ""
        path = os.path.join(POSTER_CACHE_DIR, name)
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            continue
        if not data:
            continue
        try:
            os.utime(path, None)
        except OSError:  # pragma: no cover — файл мог исчезнуть между делом
            pass
        return data, ext
    return b"", ""


def put(key: str, data: bytes, ext: str = ".jpg") -> str:
    """Кладёт обложку в кладовую и возвращает путь («» — не вышло).

    Не вышло — не беда: кэш только ускоряет работу, и вкладка обойдётся без
    него."""
    if not key or not data:
        return ""
    ext = str(ext or ".jpg").lower()
    if ext not in _EXTS:
        ext = ".jpg"
    name = _name(key, ext)
    if not name:
        return ""
    path = os.path.join(cache_dir(), name)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with _LOCK:
        try:
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        except OSError:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            return ""
    return path


def _rows() -> list[tuple[str, int, float]]:
    """Всё, что лежит в кладовой: (путь, размер, время обращения)."""
    out = []
    try:
        entries = list(os.scandir(POSTER_CACHE_DIR))
    except OSError:
        return out
    for entry in entries:
        if not entry.is_file():
            continue
        if os.path.splitext(entry.name)[1].lower() not in _EXTS:
            continue
        try:
            st = entry.stat()
        except OSError:  # pragma: no cover
            continue
        out.append((entry.path, int(st.st_size), float(st.st_atime or st.st_mtime)))
    return out


def size_bytes() -> int:
    """Сколько всего занимает кладовая."""
    return sum(size for _p, size, _t in _rows())


def count() -> int:
    return len(_rows())


def prune(limit_mb: Optional[int] = None) -> int:
    """Выбрасывает самые давние обложки, пока кладовая не влезет в потолок.
    Возвращает, сколько файлов удалено."""
    limit = int(limit_mb if limit_mb is not None else POSTER_CACHE_MB)
    if limit <= 0:
        return 0
    rows = _rows()
    total = sum(size for _p, size, _t in rows)
    cap = limit * 1024 * 1024
    if total <= cap:
        return 0
    gone = 0
    for path, size, _t in sorted(rows, key=lambda r: r[2]):
        if total <= cap:
            break
        try:
            os.remove(path)
        except OSError:  # pragma: no cover — файл мог быть занят
            continue
        total -= size
        gone += 1
    return gone


def clear() -> int:
    """Забыть все обложки (кнопка «Очистить кэш обложек»). Возвращает, сколько
    файлов удалено."""
    gone = 0
    for path, _size, _t in _rows():
        try:
            os.remove(path)
            gone += 1
        except OSError:  # pragma: no cover
            continue
    return gone


def stats() -> tuple[int, int]:
    """(сколько обложек, сколько байт) — для подписи в настройках."""
    rows = _rows()
    return len(rows), sum(size for _p, size, _t in rows)


# ─────────────────────────────────────────────────────────────────────────────
# Ключ TMDB
# ─────────────────────────────────────────────────────────────────────────────
def settings_tmdb_key() -> str:
    """Ключ TMDB из настроек программы («» — не введён).

    Вводится он один раз в Настройках программы (раздел «Ключи API»), а нужен
    и генератору, и апгрейду: обложки оба берут из одного и того же места,
    значит и запасной источник у них общий. Читаем прямо из файла настроек,
    чтобы не тащить сюда Qt. Старое место (animepack.tmdb_key) читаем запасным
    вариантом — ради настроек, сделанных до переезда ключей."""
    try:
        from utils import load_settings
        data = load_settings() or {}
    except Exception:  # noqa: BLE001 — без настроек просто нет ключа
        return ""
    if not isinstance(data, dict):
        return ""
    keys = data.get("api_keys")
    if isinstance(keys, dict):
        key = str(keys.get("tmdb") or "").strip()
        if key:
            return key
    pack = data.get("animepack")
    if not isinstance(pack, dict):
        return ""
    return str(pack.get("tmdb_key") or "").strip()
