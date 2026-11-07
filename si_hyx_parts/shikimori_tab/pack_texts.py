# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Чтение ответов и текстов вопросов из .siq для исключения паков.

Разбор без Qt и без SiqPackage: нужны только строки, которые могли попасть в
вопрос. Поэтому медиа не извлекаются и длительности не считаются — большой пак
читается за доли секунды. Понимает оба формата содержимого: v5 (params/item) и
v4 (scenario/atom).
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
import zipfile
from functools import lru_cache

# content.xml чужого пака может быть огромным; защищаемся от чтения гигабайтов
# в память. У реальных паков он заметно меньше.
_MAX_CONTENT_BYTES = 50 * 1024 * 1024
_TRUE = frozenset(("true", "1", "yes"))


def _local(tag) -> str:
    return str(tag).rsplit("}", 1)[-1].casefold()


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def _is_ref(element) -> bool:
    return str(element.get("isRef") or "").strip().casefold() in _TRUE


def _is_text_item(item) -> bool:
    """Текстовый item: не ссылка на файл и не медиа.

    Устный текст (placement="replic") тоже считается: генератор кладёт
    название тайтла именно туда («Аниме: Тайные желания отвергнутых (2017)»
    рядом с видео), и без него пак ничего не исключал."""
    if _is_ref(item):
        return False
    kind = str(item.get("type") or "text").strip().casefold()
    return kind in ("", "text")


def _param_texts(question, name: str) -> list:
    """Текстовые item'ы всех param с указанным именем (без ссылок на файлы)."""
    texts = []
    for element in question.iter():
        if _local(element.tag) != "param":
            continue
        if str(element.get("name") or "").casefold() != name:
            continue
        items = [item for item in element if _local(item.tag) == "item"]
        if not items:
            value = _clean(element.text)
            if value:
                texts.append(value)
            continue
        for item in items:
            if not _is_text_item(item):
                continue
            value = _clean(item.text)
            if value:
                texts.append(value)
    return texts


def _answer_texts(question) -> list:
    """Правильные ответы и тексты param="answer" (как в редакторе SIQuester)."""
    texts = []
    for element in question.iter():
        tag = _local(element.tag)
        if tag in ("right", "answers"):
            for answer in element.iter():
                if _local(answer.tag) == "answer":
                    value = _clean(answer.text)
                    if value:
                        texts.append(value)
        elif tag == "param" and str(element.get("name") or "").casefold() == "answer":
            for item in element.iter():
                if (_local(item.tag) != "item"
                        or not _is_text_item(item)):
                    continue
                value = _clean(item.text)
                if value:
                    texts.append(value)
    return texts


def _scenario_texts(question) -> tuple[list, list]:
    """Тексты вопроса/ответа из формата v4: scenario/atom + marker."""
    scenario = next((element for element in question
                     if _local(element.tag) == "scenario"), None)
    if scenario is None:
        return [], []
    question_texts, answer_texts = [], []
    target = question_texts
    for atom in scenario:
        if _local(atom.tag) != "atom":
            continue
        atom_type = str(atom.get("type") or "text").strip().casefold()
        if atom_type == "marker":
            target = answer_texts
            continue
        raw = _clean(atom.text)
        if not raw or raw.startswith("@"):
            continue
        if atom_type in ("text", "say"):
            target.append(raw)
    return question_texts, answer_texts


def _question_texts(question) -> tuple[tuple, tuple]:
    """(ответы, тексты вопроса) одного вопроса."""
    has_params = any(_local(element.tag) == "params" for element in question)
    answers = _answer_texts(question)
    if has_params:
        questions = _param_texts(question, "question")
    else:
        questions, scenario_answers = _scenario_texts(question)
        answers.extend(scenario_answers)
    return (tuple(dict.fromkeys(answers)),
            tuple(dict.fromkeys(questions)))


def _read(path: str) -> tuple[tuple, tuple]:
    with zipfile.ZipFile(path) as archive:
        xml_name = next(
            (name for name in archive.namelist()
             if name.rsplit("/", 1)[-1].casefold() == "content.xml"), "")
        if not xml_name:
            raise ValueError("в архиве нет content.xml")
        info = archive.getinfo(xml_name)
        if info.file_size > _MAX_CONTENT_BYTES:
            raise ValueError("content.xml слишком большой")
        data = archive.read(info)
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    root = ET.fromstring(data)
    answers, questions = [], []
    for question in root.iter():
        if _local(question.tag) != "question":
            continue
        found_answers, found_questions = _question_texts(question)
        answers.extend(found_answers)
        questions.extend(found_questions)
    return (tuple(dict.fromkeys(answers)),
            tuple(dict.fromkeys(questions)))


@lru_cache(maxsize=64)
def _cached(path: str, modified: int, size: int) -> tuple[tuple, tuple]:
    """Повторный выбор того же файла не распаковывает пак заново."""
    return _read(path)


def read_pack_texts(path: str) -> tuple[tuple, tuple]:
    """Ответы и тексты вопросов одного `.siq`: (answers, questions).

    Бросает OSError/ValueError/ET.ParseError/zipfile.BadZipFile, если файл
    недоступен или повреждён — вызывающий решает, как это показать.
    """
    full = os.path.abspath(os.fspath(path))
    stat = os.stat(full)
    return _cached(os.path.normcase(full), stat.st_mtime_ns, stat.st_size)
