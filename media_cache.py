# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Bounded on-disk cache for reusable anime-pack media.

Only immutable inputs and deterministic derived files belong here. Random
Pixiv/MangaDex/Sakugabooru choices deliberately stay out: the frame
history prevents their reuse, so caching them would mostly waste disk space.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
from typing import Callable, Optional

try:
    from config import CONFIG_DIR
except Exception:  # pragma: no cover - standalone tests/tools
    CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".unified_media_tool")


MEDIA_CACHE_DIR = os.path.join(CONFIG_DIR, "animepack_media")
# Together with poster_cache's 5 GiB this keeps the user's requested media
# budget near 10 GiB. Tiny JSON/chroma caches are outside this bulk budget.
MEDIA_CACHE_MB = 5120
CACHE_VERSION = "media-1"

_LOCK = threading.RLock()
_KEY_LOCKS = [threading.Lock() for _ in range(64)]
_SIZE: Optional[int] = None
_SUFFIX = re.compile(r"^\.[a-z0-9]{1,8}$")
_NS_SAFE = re.compile(r"[^a-z0-9_-]+")
# Разделитель между разделом и отпечатком в имени файла. Двойное
# подчёркивание, а не дефис: сами разделы зовутся «anime-frame» и
# «cover-audio», и по дефису имя обратно не разобрать.
NS_SEP = "__"

# Что лежит в файле, видно по его первым байтам. Нужно дважды: чтобы класть
# скачанное под НАСТОЯЩИМ расширением (папка кэша была полна «.bin», которые
# ничем не открываются, — жалоба пользователя) и чтобы окно кэша умело
# показать такой файл, даже если он лёг туда давно.
_MAGIC = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"GIF8", ".gif"),
    (b"\x1a\x45\xdf\xa3", ".webm"),      # Matroska/WebM
    (b"OggS", ".ogg"),
    (b"fLaC", ".flac"),
    (b"ID3", ".mp3"),
    (b"\xff\xfb", ".mp3"),
    (b"\xff\xf3", ".mp3"),
    (b"\xff\xf2", ".mp3"),
    (b"%PDF", ".pdf"),
)
# Расширения, под которыми одна и та же запись могла лечь раньше и может лечь
# сейчас: по ним ищется файл, когда звавший не знает, что внутри.
SNIFFED_EXTS = (".bin", ".jpg", ".png", ".webp", ".gif", ".avif", ".m4a",
                ".mp4", ".webm", ".ogg", ".mp3", ".flac", ".pdf")


def sniff_ext(data: bytes, default: str = ".bin") -> str:
    """Расширение по первым байтам («.bin» — не узнали)."""
    head = bytes(data or b"")[:32]
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"avif", b"avis"):
            return ".avif"
        if brand.startswith(b"M4A"):
            return ".m4a"
        return ".mp4"
    for magic, ext in _MAGIC:
        if head.startswith(magic):
            return ext
    return default


def sniff_file(path: str, default: str = ".bin") -> str:
    """То же по файлу — окно кэша так узнаёт, чем открывать «.bin»."""
    try:
        with open(path, "rb") as stream:
            return sniff_ext(stream.read(32), default)
    except OSError:
        return default


def _digest(namespace: str, key: str) -> str:
    raw = f"{CACHE_VERSION}\0{namespace}\0{key}".encode("utf-8", "surrogatepass")
    return hashlib.sha256(raw).hexdigest()


def _ns_slug(namespace: str) -> str:
    return _NS_SAFE.sub("-", str(namespace or "other").strip().lower()) or "other"


def namespace_of(path: str) -> str:
    """Раздел кэша по имени файла («» — файл лёг до разделов в именах)."""
    name = os.path.basename(str(path or ""))
    head, sep, _tail = name.partition(NS_SEP)
    return head if sep else ""


def content_key(data: bytes, *settings) -> str:
    """Stable key for a deterministic transform of ``data``."""
    digest = hashlib.sha256(data).hexdigest()
    tail = "\0".join(str(value) for value in settings)
    return f"{digest}\0{tail}"


def _clean_suffix(suffix: str) -> str:
    suffix = str(suffix or ".bin").lower()
    return suffix if _SUFFIX.fullmatch(suffix) else ".bin"


def _path(namespace: str, key: str, suffix: str) -> str:
    """Имя файла: раздел, отпечаток ключа и расширение.

    Раздел попал в имя ради окна «Файлы кэша»: там были «Постеры» и «Медиа»
    одной кучей, и понять, что за файл перед тобой, было нельзя (жалоба
    пользователя). Записи со старым именем переезжают сюда сами при первом же
    обращении — качать их заново незачем."""
    return os.path.join(
        MEDIA_CACHE_DIR,
        f"{_ns_slug(namespace)}{NS_SEP}{_digest(namespace, key)}"
        f"{_clean_suffix(suffix)}")


def _legacy_path(namespace: str, key: str, suffix: str) -> str:
    """Как та же запись называлась до разделов в имени."""
    return os.path.join(MEDIA_CACHE_DIR,
                        _digest(namespace, key) + _clean_suffix(suffix))


def _adopt(path: str, namespace: str, key: str, suffix: str) -> str:
    """Найти запись под любым прежним именем и переименовать в нынешнее.

    Возвращает путь к готовому файлу или «». Перебираются и старое имя без
    раздела, и «.bin»: до того, как скачанное стали класть под настоящим
    расширением, всё ложилось именно так. Скачивать заново из-за переезда
    имён ничего не нужно — файл просто зовут иначе."""
    wanted = _clean_suffix(suffix)
    digest = _digest(namespace, key)
    tried, order = {path}, [_legacy_path(namespace, key, wanted),
                            _path(namespace, key, ".bin")]
    order += [os.path.join(MEDIA_CACHE_DIR, digest + ext)
              for ext in SNIFFED_EXTS]
    for candidate in order:
        if candidate in tried:
            continue
        tried.add(candidate)
        try:
            if os.path.getsize(candidate) <= 0:
                continue
        except OSError:
            continue
        # Просили «что угодно» — заодно назовём файл по его содержимому.
        target = (_path(namespace, key, sniff_file(candidate))
                  if wanted == ".bin" else path)
        try:
            if target != candidate:
                os.replace(candidate, target)
        except OSError:
            continue
        return target
    return ""


def migrate_names(limit: int = 0) -> int:
    """Старым записям — настоящее расширение вместо «.bin».

    Раздел по имени уже не восстановить (он спрятан в отпечатке ключа), а вот
    «.bin», который ничем не открывается, поправить можно: тип виден по первым
    байтам. Зовёт это окно «Файлы кэша» — там пользователь на такие файлы и
    смотрит. Поиск записи такие переименования переживает (см. _adopt)."""
    done = 0
    with _LOCK:
        for path, _size, _used in _entries():
            if namespace_of(path) or not path.lower().endswith(".bin"):
                continue
            ext = sniff_file(path)
            if ext == ".bin":
                continue
            target = path[:-len(".bin")] + ext
            if os.path.exists(target):
                continue
            try:
                os.replace(path, target)
            except OSError:
                continue
            done += 1
            if limit and done >= limit:
                break
    return done


def _entries() -> list[tuple[str, int, float]]:
    try:
        rows = list(os.scandir(MEDIA_CACHE_DIR))
    except OSError:
        return []
    out = []
    for row in rows:
        if not row.is_file() or row.name.endswith(".tmp"):
            continue
        try:
            stat = row.stat()
        except OSError:
            continue
        out.append((row.path, int(stat.st_size), float(stat.st_mtime)))
    return out


def _size_locked() -> int:
    global _SIZE
    if _SIZE is None:
        _SIZE = sum(size for _path, size, _used in _entries())
    return _SIZE


def read(namespace: str, key: str, suffix: str = ".bin") -> Optional[bytes]:
    """Return cached bytes, or ``None`` on a miss/corrupt empty entry."""
    path = find_path(namespace, key, suffix)
    if not path:
        return None
    try:
        with open(path, "rb") as stream:
            data = stream.read()
    except OSError:
        return None
    if not data:
        return None
    return data


def find_path(namespace: str, key: str, suffix: str = ".bin") -> str:
    """Return a usable cached file path without reading a large file.

    ``.bin`` значит «звавший не знает, что внутри»: такая запись могла лечь и
    под настоящим расширением, поэтому перебираем известные."""
    wanted = _clean_suffix(suffix)
    for ext in (SNIFFED_EXTS if wanted == ".bin" else (wanted,)):
        path = _path(namespace, key, ext)
        try:
            ready = os.path.getsize(path) > 0
        except OSError:
            ready = False
        if not ready and ext == wanted:
            path = _adopt(path, namespace, key, ext)
            ready = bool(path)
        if not ready:
            continue
        try:
            os.utime(path, None)
        except OSError:  # pragma: no cover - a concurrent cleanup is harmless
            pass
        return path
    return ""


def put(namespace: str, key: str, data: bytes,
        suffix: str = ".bin") -> str:
    """Atomically save bytes and return their path (empty string on error)."""
    global _SIZE
    if not key or not data:
        return ""
    # «.bin» значит «не знаю, что это»: узнаём по самим байтам, иначе папка
    # кэша наполняется файлами, которые ничем не открываются.
    suffix = _clean_suffix(suffix)
    if suffix == ".bin":
        suffix = sniff_ext(data)
    path = _path(namespace, key, suffix)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with _LOCK:
        try:
            os.makedirs(MEDIA_CACHE_DIR, exist_ok=True)
            # Та же запись могла лежать под прежним именем: подберём её под
            # нынешнее, иначе старый файл остался бы висеть мёртвым грузом.
            _adopt(path, namespace, key, suffix)
            current = _size_locked()
            old = os.path.getsize(path) if os.path.isfile(path) else 0
            with open(tmp, "wb") as stream:
                stream.write(data)
            os.replace(tmp, path)
            _SIZE = current - old + len(data)
            if _SIZE > MEDIA_CACHE_MB * 1024 * 1024:
                _prune_locked(MEDIA_CACHE_MB)
            return path
        except OSError:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            return ""


def get_or_load(namespace: str, key: str, loader: Callable[[], bytes],
                suffix: str = ".bin", minimum: int = 1) -> tuple[bytes, bool]:
    """Load one key once across worker threads; return ``(data, cache_hit)``."""
    lock = _KEY_LOCKS[int(_digest(namespace, key)[:8], 16) % len(_KEY_LOCKS)]
    with lock:
        data = read(namespace, key, suffix)
        if data is not None and len(data) >= max(1, int(minimum)):
            return data, True
        data = loader()
        if data and len(data) >= max(1, int(minimum)):
            put(namespace, key, data, suffix)
        return data, False


def _prune_locked(limit_mb: int) -> int:
    global _SIZE
    cap = max(0, int(limit_mb)) * 1024 * 1024
    rows = _entries()
    total = sum(size for _path, size, _used in rows)
    gone = 0
    for path, size, _used in sorted(rows, key=lambda item: item[2]):
        if total <= cap:
            break
        try:
            os.remove(path)
        except OSError:
            continue
        total -= size
        gone += 1
    _SIZE = total
    return gone


def prune(limit_mb: Optional[int] = None) -> int:
    with _LOCK:
        return _prune_locked(MEDIA_CACHE_MB if limit_mb is None else limit_mb)


def stats() -> tuple[int, int]:
    rows = _entries()
    return len(rows), sum(size for _path, size, _used in rows)


def entries() -> list[dict]:
    """Файлы для окна управления кэшем, без чтения тяжёлого содержимого."""
    return [{"path": path, "name": os.path.basename(path), "size": size,
             "modified": used, "namespace": namespace_of(path)}
            for path, size, used in _entries()]


def remove(path: str) -> bool:
    """Удалить один файл только внутри этой кладовой."""
    global _SIZE
    root = os.path.abspath(MEDIA_CACHE_DIR)
    target = os.path.abspath(str(path or ""))
    try:
        if os.path.commonpath((root, target)) != root:
            return False
    except (OSError, ValueError):
        return False
    with _LOCK:
        try:
            size = os.path.getsize(target)
            current = _size_locked()
            os.remove(target)
        except OSError:
            return False
        _SIZE = max(0, current - size)
    return True


def clear() -> int:
    global _SIZE
    gone = 0
    with _LOCK:
        for path, _size, _used in _entries():
            try:
                os.remove(path)
                gone += 1
            except OSError:
                pass
        _SIZE = 0
    return gone
