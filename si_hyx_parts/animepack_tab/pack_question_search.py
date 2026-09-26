# -*- coding: utf-8 -*-
"""Поиск по вопросам внутри SIQ-паков без зависимости от Qt."""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
import zipfile
from functools import lru_cache


_MEDIA_LABELS = {
    "audio": "Аудио", "image": "Изображение", "video": "Видео",
    "html": "HTML",
}


def _local(element) -> str:
    return str(element.tag).rsplit("}", 1)[-1].lower()


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def _param(question, name: str):
    for element in question.iter():
        if (_local(element) == "param"
                and str(element.get("name") or "").casefold() == name):
            return element
    return None


def _question_content(question) -> tuple[list[str], list[str]]:
    texts, media = [], []
    param = _param(question, "question")
    if param is None:
        return texts, media
    items = [item for item in param.iter() if _local(item) == "item"]
    if not items and _clean(param.text):
        texts.append(_clean(param.text))
    for item in items:
        value = _clean(item.text)
        if not value:
            continue
        kind = str(item.get("type") or "").casefold()
        is_ref = str(item.get("isRef") or "").casefold() == "true"
        if kind in _MEDIA_LABELS or is_ref:
            media.append(f"{_MEDIA_LABELS.get(kind, kind or 'Файл')}: "
                         f"{os.path.basename(value)}")
        elif str(item.get("placement") or "").casefold() != "replic":
            texts.append(value)
    return texts, media


def _answers(question) -> list[str]:
    values = []
    for group in question.iter():
        if _local(group) not in ("right", "answers"):
            continue
        for answer in group.iter():
            if _local(answer) == "answer" and _clean(answer.text):
                values.append(_clean(answer.text))
    return list(dict.fromkeys(values))


def read_questions(path: str) -> list[dict]:
    """Возвращает краткие карточки всех вопросов одного `.siq`."""
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("content.xml"))
    package = _clean(root.get("name")) or os.path.basename(path)
    rows = []
    for round_el in (element for element in root.iter()
                     if _local(element) == "round"):
        round_name = _clean(round_el.get("name"))
        for theme in (element for element in round_el.iter()
                      if _local(element) == "theme"):
            theme_name = _clean(theme.get("name"))
            for question in (element for element in theme.iter()
                             if _local(element) == "question"):
                texts, media = _question_content(question)
                answers = _answers(question)
                row = {
                    "path": path, "pack": package, "round": round_name,
                    "theme": theme_name,
                    "price": _clean(question.get("price")),
                    "question": " · ".join(texts),
                    "used": media,
                    "answers": answers,
                }
                row["haystack"] = "\n".join([
                    package, os.path.basename(path), round_name, theme_name,
                    row["question"], *media, *answers]).casefold()
                rows.append(row)
    return rows


@lru_cache(maxsize=64)
def _cached_questions(path: str, modified: int, size: int) -> tuple[dict, ...]:
    """Повторный ввод в поиске не распаковывает тот же пакет заново."""
    return tuple(read_questions(path))


def search_questions(paths, query: str, limit: int = 250) -> list[dict]:
    """Ищет все слова запроса в вопросах, ответах, темах и медиа."""
    words = _clean(query).casefold().split()
    if not words:
        return []
    found = []
    for path in paths:
        if not os.path.isfile(path):
            continue
        try:
            stat = os.stat(path)
            rows = _cached_questions(path, stat.st_mtime_ns, stat.st_size)
        except (OSError, KeyError, ET.ParseError, zipfile.BadZipFile):
            continue
        for row in rows:
            if all(word in row["haystack"] for word in words):
                found.append(row)
                if len(found) >= max(1, int(limit)):
                    return found
    return found
