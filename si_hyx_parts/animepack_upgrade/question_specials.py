# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Спецвопросы: цена, вид, наличие содержимого и превращение в обычный вопрос. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


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
