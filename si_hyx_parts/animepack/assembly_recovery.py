# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Готовые вопросы после ошибки отбора или упаковки.

После ошибки генератор сначала автоматически записывает SIQ из готовых
вопросов. Если записать архив не удалось ни в одну доступную папку, медиа
и вопросы переезжают сюда для повторной сборки кнопкой «Собрать сохранённое».

Хранится одна, последняя, попытка: каждая весит сотни мегабайт.
"""
from __future__ import annotations

import copy
import json
import os
import pickle
import shutil
import time
import uuid

import animepack as _api

SONGS_FILE = "songs.pickle"
META_FILE = "attempt.json"
# Версия формата: старую попытку другой версии программа не трогает.
VERSION = 1


def recovery_dir() -> str:
    """Рядом с кэшем каталога: тесты подменяют его путь, и попытки туда же."""
    return os.path.join(os.path.dirname(_api.SHIKI_CACHE_FILE), "animepack_recovery")


def save(generator, songs: list, error: str) -> str:
    """Переносит папку генерации в хранилище попытки; отдаёт её путь или ""."""
    folder = getattr(generator, "folder", "")
    if not songs or not folder or not os.path.isdir(folder):
        return ""
    # A failed snapshot or move must never turn cleanup into data loss.
    generator._preserve_media = True
    franchises = {str(c.anime.get("franchise") or "").strip() for c in songs}
    parts = getattr(generator, "_fr_parts", {}) or {}
    try:
        payload = pickle.dumps(
            {"songs": [_picklable(song) for song in songs],
             "franchise_parts": {k: parts[k] for k in franchises if k in parts}},
            protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as error:  # noqa: BLE001 — без снимка сохранять нечего
        generator.log(f"Готовые вопросы сохранить не удалось: {error}")
        return ""
    root = recovery_dir()
    target = os.path.join(root, time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex)
    pending = os.path.join(root, ".pending-" + uuid.uuid4().hex)
    previous = [os.path.join(root, name) for name in _names(root) if not name.startswith(".pending-")]
    meta = {"version": VERSION, "created": time.time(), "error": error,
            "title": generator.s.title, "questions": len(songs)}
    settings = generator.s.to_dict()
    meta['settings'] = {}
    for key, value in settings.items():
        if key.startswith('_') or any(word in key for word in ('key', 'token', 'password')):
            continue
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            continue
        meta['settings'][key] = value
    meta['actual_counts'] = dict(_api.Counter(song.kind for song in songs))
    log = getattr(generator, '_run_log', None)
    if log is not None:
        meta['log_path'] = str(log.path)
    started = getattr(generator, '_run_started', None)
    if started is not None:
        meta['elapsed_seconds'] = time.monotonic() - started
    try:
        # Write the complete snapshot before moving media or deleting the old one.
        with open(os.path.join(folder, SONGS_FILE), "wb") as f:
            f.write(payload)
        with open(os.path.join(folder, META_FILE), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        os.makedirs(root, exist_ok=True)
        shutil.move(folder, pending)
        os.replace(pending, target)
    except OSError as move_error:
        if os.path.isdir(pending) and not os.path.isdir(folder):
            generator.folder = pending
        generator.log(f"Готовые вопросы сохранить не удалось: {move_error}")
        return ""
    generator.folder = ""
    generator._preserve_media = False
    for old in previous:
        if os.path.realpath(old) == getattr(generator, '_recovery_source', ''):
            continue
        discard(old)
    return target


def keep_or_raise(generator, songs: list, error: Exception) -> None:
    """Preserve prepared questions and report the original generation failure."""
    text = (str(error) if isinstance(error, _api.AnimePackError)
            else f"{type(error).__name__}: {error}")
    source = getattr(generator, "_recovery_source", "")
    if source and os.path.isdir(source):
        # Пересборка сохранённой попытки: она сама и есть копия, вторую (на
        # сотни мегабайт) не заводим.
        raise _api.AnimePackError(
            f"{text}\n\nСохранённая попытка остаётся — после исправления снова "
            "нажмите «Собрать сохранённое».") from error
    kept = save(generator, songs, text)
    if kept:
        generator.log(f"Готовые вопросы ({len(songs)}) и их медиа сохранены: {kept}")
        raise _api.AnimePackError(
            f"{text}\n\nГотовые вопросы ({len(songs)}) сохранены. Исправьте "
            "настройки и нажмите «Собрать сохранённое» — отбор и загрузки "
            "повторять не придётся.") from error
    folder = getattr(generator, "folder", "")
    if getattr(generator, "_preserve_media", False) and os.path.isdir(folder):
        generator.log(f"Медиа готовых вопросов не удалены: {folder}")
        raise _api.AnimePackError(
            f"{text}\n\nНе удалось перенести готовые вопросы в хранилище. "
            f"Исходные данные сохранены в папке: {folder}") from error
    raise error


def _picklable(song):
    """Вопрос без служебных полей, которые не сохранить (загрузки в работе)."""
    try:
        pickle.dumps(song)
        return song
    except Exception:  # noqa: BLE001 — разбираемся по полям ниже
        clone = copy.copy(song)
    for name, value in list(vars(clone).items()):
        try:
            pickle.dumps(value)
        except Exception:  # noqa: BLE001
            if not name.startswith("_"):
                raise
            delattr(clone, name)
    return clone


def latest() -> dict:
    """Описание сохранённой попытки ({} — её нет или она чужой версии)."""
    root = recovery_dir()
    try:
        names = sorted(os.listdir(root), reverse=True)
    except OSError:
        return {}
    for name in names:
        if name.startswith(".pending-"):
            continue
        path = os.path.join(root, name)
        try:
            with open(os.path.join(path, META_FILE), encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            continue
        if meta.get("version") == VERSION and os.path.isfile(os.path.join(path, SONGS_FILE)):
            return {**meta, "path": path}
    return {}


def load(path: str) -> tuple[list, dict]:
    """(вопросы, части франшиз) сохранённой попытки."""
    with open(os.path.join(path, SONGS_FILE), "rb") as f:
        state = pickle.load(f)  # noqa: S301 — файл пишет только сама программа
    return list(state["songs"]), dict(state.get("franchise_parts") or {})


def discard(path: str = "") -> None:
    """Удаляет попытку path (по умолчанию — все сохранённые)."""
    root = recovery_dir()
    targets = [path] if path else [os.path.join(root, name) for name in _names(root)]
    for target in targets:
        resolved = os.path.realpath(target)
        base = os.path.realpath(root)
        if resolved == base or os.path.commonpath((base, resolved)) != base:
            raise ValueError("Путь попытки находится вне хранилища восстановления")
        shutil.rmtree(target, ignore_errors=True)


def _names(root: str) -> list:
    try:
        return os.listdir(root)
    except OSError:
        return []
