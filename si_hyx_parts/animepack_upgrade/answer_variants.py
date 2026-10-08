# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Варианты названия в ответе: без года, уже записанные, добавление. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


def strip_year(text) -> str:
    """Название без хвостового «(2003)» — сколько бы их подряд ни стояло."""
    line = str(text or "").strip()
    while True:
        cut = _api._RE_YEAR_TAIL.sub("", line).strip()
        if cut == line:
            return line
        line = cut

strip_year.__module__ = _api.__name__
_api.strip_year = strip_year

def title_variants(card: dict, s: _api.Optional[_api.UpgradeSettings] = None) -> list[str]:
    """Названия тайтла, которые можно дописать в ответ.

    Берутся ВСЕ и всегда — ромадзи, английское, лицензионное, синонимы и русское
    (выбор их видов убран по просьбе пользователя: в паке нужен полный список).
    Порядок — как у генератора. Иероглифику не берём вовсе: ведущему её не
    прочитать, игроку не набрать (то же правило, что в animepack._dedup_answers).
    Год отрезаем: в ответе он не нужен, а Shikimori держит его в названии у части
    тайтлов."""
    out: list[str] = [card.get("name"), card.get("english"),
                      card.get("licenseNameRu")]
    out.extend(card.get("synonyms") or [])
    # Русское название дописываем последним: ответ мог быть записан ромадзи, и
    # тогда именно оно — самый нужный вариант.
    out.append(card.get("russian"))
    clean, seen = [], set()
    for name in out:
        text = _api.strip_year(name)
        key = _api.norm_title(text)
        if not text or not key or _api.has_cjk(text) or key in seen:
            continue
        seen.add(key)
        clean.append(text)
    return clean

title_variants.__module__ = _api.__name__
_api.title_variants = title_variants

def answers_of(q_el: _api.ET.Element) -> list[_api.ET.Element]:
    right = _api.child(q_el, "right")
    return _api.children(right, "answer")

answers_of.__module__ = _api.__name__
_api.answers_of = answers_of

def _already_written(existing: list[str], variant: str) -> bool:
    """Есть ли это название в паке — пусть и внутри более длинного ответа.

    Сравниваем по нормализованным словам: вариант «Багровые осколки» уже
    написан в ответе «Багровые осколки - Nee», и дописывать его второй строкой
    незачем (просьба пользователя). Проверка идёт по целым словам, поэтому
    «Ди» не считается написанным из-за ответа «Дигимон»."""
    needle = _api.norm_title(variant)
    if not needle:
        return True
    for text in existing:
        hay = _api.norm_title(text)
        if hay and f" {needle} " in f" {hay} ":
            return True
    return False

_already_written.__module__ = _api.__name__
_api._already_written = _already_written

def add_answers(q_el: _api.ET.Element, tag, variants: list[str]) -> list[str]:
    """Дописывает варианты в <right>. То, что в паке уже написано (пусть и
    внутри другого ответа), не повторяет. Возвращает реально добавленное."""
    right = _api.child(q_el, "right")
    if right is None:
        return []
    have = [(a.text or "") for a in _api.children(right, "answer")]
    added = []
    for text in variants:
        if _api._already_written(have, text):
            continue
        have.append(text)
        el = _api.ET.SubElement(right, tag("answer"))
        el.text = text
        added.append(text)
    return added

add_answers.__module__ = _api.__name__
_api.add_answers = add_answers
