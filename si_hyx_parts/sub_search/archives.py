# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Распаковка архивов субтитров в памяти (zip, tar*, gz).

На диск ничего не извлекается — пути внутри архива никуда не склеиваются
(нет zip-slip); размеры ограничены (защита от zip-бомб), вложенные архивы —
до MAX_DEPTH уровней.
"""
from __future__ import annotations

import gzip
import io
import tarfile
import zipfile
from typing import Iterator

from .parsers import SUB_EXTS

ARCHIVE_EXTS = (".zip", ".tar", ".tgz", ".tar.gz", ".tbz2", ".tar.bz2",
                ".txz", ".tar.xz", ".gz")
MAX_MEMBER = 32 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_FILES = 5000
MAX_DEPTH = 3


class _Budget:
    def __init__(self) -> None:
        self.total = 0
        self.files = 0

    def take(self, size: int) -> bool:
        self.files += 1
        self.total += size
        return self.files <= MAX_FILES and self.total <= MAX_TOTAL


def _is_tar(data: bytes) -> bool:
    try:
        return tarfile.is_tarfile(io.BytesIO(data))
    except Exception:  # noqa: BLE001 — не tar
        return False


def _kind(name: str, data: bytes) -> str:
    low = name.lower()
    if data[:4] in (b"PK\x03\x04", b"PK\x05\x06"):
        return "zip"
    if data[:4] == b"Rar!" or data[:6] == b"7z\xbc\xaf\x27\x1c":
        return "unsupported"
    if data[:2] == b"\x1f\x8b" or data[:3] == b"BZh" or data[:6] == b"\xfd7zXZ\x00":
        return "tar" if (low.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tbz2",
                                       ".tar.xz", ".txz")) or _is_tar(data)) else "gz"
    if low.endswith(SUB_EXTS):
        return "sub"
    if low.endswith(".tar") and _is_tar(data):
        return "tar"
    return "other"


def _wanted(name: str) -> bool:
    low = name.lower()
    return low.endswith(SUB_EXTS) or low.endswith(ARCHIVE_EXTS)


def iter_subtitle_files(name: str, data: bytes, notes: list,
                        _depth: int = 0, _budget: _Budget | None = None
                        ) -> Iterator[tuple[str, bytes]]:
    """(путь внутри архива, байты) каждого SRT/ASS/SSA. Пропуски — в notes."""
    budget = _budget or _Budget()
    kind = _kind(name, data)
    if kind == "sub":
        yield name, data
        return
    if kind == "unsupported":
        notes.append("архив 7z/rar не поддерживается")
        return
    if kind == "other":
        return
    if _depth >= MAX_DEPTH:
        notes.append("слишком глубокая вложенность архивов")
        return

    def descend(member: str, blob: bytes):
        yield from iter_subtitle_files(f"{name}!{member}", blob, notes,
                                       _depth + 1, budget)

    try:
        if kind == "zip":
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for info in zf.infolist():
                    if info.is_dir() or not _wanted(info.filename):
                        continue
                    if info.file_size > MAX_MEMBER or (
                            info.compress_size and info.file_size > 1_000_000
                            and info.file_size / info.compress_size > 1000):
                        notes.append("файл в архиве слишком большой")
                        continue
                    if not budget.take(info.file_size):
                        notes.append("архив слишком большой")
                        return
                    with zf.open(info) as fh:
                        blob = fh.read(MAX_MEMBER + 1)
                    if len(blob) <= MAX_MEMBER:
                        yield from descend(info.filename, blob)
        elif kind == "tar":
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
                for ti in tf:
                    if not ti.isreg() or ti.size > MAX_MEMBER or not _wanted(ti.name):
                        continue
                    if not budget.take(ti.size):
                        notes.append("архив слишком большой")
                        return
                    fh = tf.extractfile(ti)
                    if fh is not None:
                        yield from descend(ti.name, fh.read(MAX_MEMBER + 1))
        elif kind == "gz":
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
                blob = gz.read(MAX_MEMBER + 1)
            if len(blob) <= MAX_MEMBER:
                inner = name[:-3] if name.lower().endswith(".gz") else name
                yield from iter_subtitle_files(inner, blob, notes, _depth + 1, budget)
    except (zipfile.BadZipFile, tarfile.TarError, OSError, EOFError,
            RuntimeError, ValueError) as exc:
        notes.append(f"битый архив ({type(exc).__name__})")
