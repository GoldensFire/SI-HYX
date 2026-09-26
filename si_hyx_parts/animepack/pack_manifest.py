# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Список спрошенного — отдельным файлом внутри собранного .siq.

Зачем. Настройка «не повторять франшизы из этих паков» читала чужой пак по
строкам правильного ответа: из «Наруто (2002)» получался корень «наруто», а по
нему — франшиза из каталога. У доброй половины вопросов такой ответ ни о чём
не говорит:

* «деталь сюжета» — там угадывают предмет или имя героя («партия в сёги»), а
  название произведения стоит только в ТЕКСТЕ вопроса;
* «угадай персонажа» — ответом идёт имя героя, и голое название туда нарочно
  не пишется;
* загадки по названию — ответом идёт разгаданное слово.

Из-за этого «Моя геройская академия» из первого пака спокойно приезжала в
четвёртый, хотя первый стоял в списке «не повторять» (просьба пользователя).

Поэтому пак теперь носит список спрошенного при себе: франшиза Shikimori,
корень названия и номера тайтла. Файл лежит рядом с `content.xml`, SIGame и
SIQuester его не касаются, а чтение стоит миллисекунды. У чужих и старых паков
его нет — для них остаётся прежний разбор ответов (см. answer_title).
"""
from __future__ import annotations

import json
import zipfile

# Как файл зовётся внутри архива. Имя с приставкой: рядом уже лежат
# «chiptune.json» и «covers.json», и путать их незачем.
MANIFEST_NAME = "si-hyx-pack.json"
# Версия формата: читатель обязан пережить пак, собранный будущей версией.
VERSION = 2


def build(songs) -> str:
    """Манифест пака строкой JSON («» — писать нечего)."""
    rows = []
    studios = set()
    seen = set()
    for cand in (songs or []):
        studios.update(str(name).strip().casefold()
                       for name in (getattr(cand, "studios", None) or [])
                       if str(name).strip())
        cards = [getattr(cand, "anime", None) or {}]
        cards += list(getattr(cand, "studio_cards", None) or [])
        for card in cards:
            _append_card(rows, seen, card)
    if not rows and not studios:
        return ""
    return json.dumps({"version": VERSION, "titles": rows,
                       "studios": sorted(studios)},
                      ensure_ascii=False, indent=1)


def _append_card(rows: list, seen: set, card: dict) -> None:
    if not isinstance(card, dict):
        return
    franchise = str(card.get("franchise") or "").strip()
    root = _root(card)
    try:
        shiki = int(card.get("id") or 0)
    except (TypeError, ValueError):
        shiki = 0
    try:
        mal = int(card.get("malId") or 0)
    except (TypeError, ValueError):
        mal = 0
    key = (franchise, root, shiki, mal)
    if key in seen or not any(key):
        return
    seen.add(key)
    rows.append({"franchise": franchise, "root": root,
                 "shikimori": shiki, "mal": mal,
                 "title": str(card.get("russian")
                              or card.get("name") or "")})


def read(path: str) -> dict:
    """{"roots": set, "franchises": set} из пака («пусто» — манифеста нет).

    Битый, чужой или старый пак — это не ошибка: вызывающий просто разберёт
    его по строкам ответов, как раньше. У пака, собранного до манифеста,
    названия всё же достаются — из имён медиафайлов (см. roots_from_media)."""
    empty = {"roots": set(), "franchises": set()}
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            raw = zf.read(MANIFEST_NAME) if MANIFEST_NAME in names else b""
    except Exception:  # noqa: BLE001 — битый или чужой файл просто пропускаем
        return empty
    if not raw:
        return {"roots": roots_from_media(names), "franchises": set()}
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return empty
    if not isinstance(data, dict):
        return empty
    roots, franchises = set(), set()
    for row in (data.get("titles") or []):
        if not isinstance(row, dict):
            continue
        root = str(row.get("root") or "").strip()
        franchise = str(row.get("franchise") or "").strip()
        if root:
            roots.add(root)
        if franchise:
            franchises.add(franchise)
    return {"roots": roots, "franchises": franchises}


def read_studios(path: str) -> set[str]:
    """Студии вопросов из нашего манифеста; у старого/чужого пака пусто."""
    try:
        with zipfile.ZipFile(path) as archive:
            raw = archive.read(MANIFEST_NAME)
        data = json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return set()
    if not isinstance(data, dict):
        return set()
    return {str(name).strip().casefold()
            for name in (data.get("studios") or []) if str(name).strip()}


def roots_from_media(names) -> set:
    """Корни названий по именам файлов в архиве — для паков без манифеста.

    Медиа в наших паках подписано названием тайтла:
    «Сгенерировано в SI-HYX(Моя геройская академия)_poster.avif» (см.
    _media_base). Это единственное место в СТАРОМ паке, где название есть у
    вопроса-персонажа и у «детали сюжета», — в ответе там стоит имя героя либо
    сама деталь. Название могло быть обрезано до 80 знаков и очищено от
    запрещённых в имени файла символов, поэтому корень иногда выходит короче
    настоящего; лишнего это не закрывает — корень сравнивается целиком."""
    import animepack as ap
    out = set()
    for name in (names or []):
        base = str(name).rsplit("/", 1)[-1]
        if not base.startswith(ap.MEDIA_NAME_PREFIX + "("):
            continue
        inner = base[len(ap.MEDIA_NAME_PREFIX) + 1:]
        cut = inner.rfind(")")
        if cut <= 0:
            continue
        root = ap.title_root(inner[:cut])
        if root:
            out.add(root)
    return out


def _root(card: dict) -> str:
    """Корень названия карточки — тем же кодом, что и у самого генератора."""
    import animepack as ap
    for name in (card.get("russian"), card.get("name"), card.get("english")):
        root = ap.title_root(name)
        if root:
            return root
    return ""
