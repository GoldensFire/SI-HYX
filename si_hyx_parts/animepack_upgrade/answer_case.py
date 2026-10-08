# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Регистр и запись ответа: не хуже исходного, хвост ответа сценария. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


def _not_worse(was: str, now: str) -> bool:
    """Не понижаем заглавную букву в начале: «Mumei» → «mumei» это не
    исправление написания, а порча ответа (живой случай — у записи Shikimori
    японское название записано строчными)."""
    return not (was[:1].isupper() and now[:1].islower())

_not_worse.__module__ = _api.__name__
_api._not_worse = _not_worse

def recased(text: str, names: list[str]) -> _api.Optional[str]:
    """Тот же ответ, но написанный как на Shikimori, — или None, если и так так.

    Меняем ТОЛЬКО регистр: «наруто» → «Наруто», «НАРУТО» → «Наруто». Если бы
    разрешили менять и знаки, ответ «Стальной алхимик» превратился бы в
    «Стальной алхимик: Братство» — это уже другой ответ, а не написание."""
    line = str(text or "").strip()
    if not line:
        return None
    for name in names:
        name = str(name or "").strip()
        if (name and line != name and line.casefold() == name.casefold()
                and _api._not_worse(line, name)):
            return name
    # «наруто - Nee»: правим голову, песню за тире не трогаем.
    m = _api._RE_HEAD_TAIL.match(line)
    if m:
        head, tail = m.group(1).strip(), m.group(2)
        for name in names:
            name = str(name or "").strip()
            if (name and head != name and head.casefold() == name.casefold()
                    and _api._not_worse(head, name)):
                return name + tail
    return None

recased.__module__ = _api.__name__
_api.recased = recased

def fix_answer_case(q_el: _api.ET.Element, card: dict) -> list[tuple[str, str]]:
    """Переписывает ответы вопроса в написании Shikimori. Возвращает [(было,
    стало)] — пусто, если менять было нечего."""
    names = _api.spelling_names(card)
    changed: list[tuple[str, str]] = []
    for el in _api.answers_of(q_el):
        was = (el.text or "")
        now = _api.recased(was, names)
        if now is None:
            continue
        el.text = now
        changed.append((was.strip(), now))
    return changed

fix_answer_case.__module__ = _api.__name__
_api.fix_answer_case = fix_answer_case

# ─────────────────────────────────────────────────────────────────────────────
# Функция 4: постер тайтла в ответ
# ─────────────────────────────────────────────────────────────────────────────
def answer_content(q_el: _api.ET.Element, tag) -> _api.ET.Element:
    """Содержимое ответа вопроса — то, что показывают ПОСЛЕ ответа игроков.

    v5: <params><param name="answer" type="content">. Если такого параметра нет
    (в ответе не было ничего, кроме текста правильного ответа), заводим его.
    v4 сюда не заходит — там ответ живёт в <scenario> за маркером, см.
    scenario_answer_tail."""
    params = _api.child(q_el, "params")
    if params is None:
        params = _api.ET.SubElement(q_el, tag("params"))
    for param in _api.children(params, "param"):
        if (param.get("name") or "") == "answer":
            return param
    return _api.ET.SubElement(params, tag("param"),
                         {"name": "answer", "type": "content"})

answer_content.__module__ = _api.__name__
_api.answer_content = answer_content

def scenario_answer_tail(q_el: _api.ET.Element, tag) -> _api.Optional[_api.ET.Element]:
    """<scenario> вопроса формата v4 с гарантированным маркером в конце.

    В v4 вопрос и ответ лежат в одном сценарии, а разделяет их <atom
    type="marker"/>: всё, что после него, показывается уже как ответ. Нет
    сценария — нет и v4-вопроса, возвращаем None."""
    scenario = _api.child(q_el, "scenario")
    if scenario is None:
        return None
    if not any((a.get("type") or "") == "marker" for a in _api.children(scenario,
                                                                  "atom")):
        _api.ET.SubElement(scenario, tag("atom"), {"type": "marker"})
    return scenario

scenario_answer_tail.__module__ = _api.__name__
_api.scenario_answer_tail = scenario_answer_tail
