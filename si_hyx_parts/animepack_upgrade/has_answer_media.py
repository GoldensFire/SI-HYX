# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""has_answer_media. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


def has_answer_media(q_el: _api.ET.Element) -> bool:
    """Есть ли в ответе своё медиа. Если есть — постер не ставим.

    Не только картинка: ролик или дорожка в ответе — это тоже готовое зрелище,
    которое автор пака собрал сам, и постер после него либо перебивает его, либо
    превращает ответ в слайд-шоу. Текст (в том числе реплика ведущего) за медиа
    не считается: рядом с ним постеру самое место."""
    params = _api.child(q_el, "params")
    for param in _api.children(params, "param"):
        if (param.get("name") or "") != "answer":
            continue
        for item in _api.children(param, "item"):
            if (item.get("type") or "") in _api.ANSWER_MEDIA_KINDS:
                return True
    scenario = _api.child(q_el, "scenario")
    seen_marker = False
    for atom in _api.children(scenario, "atom"):
        kind = (atom.get("type") or "")
        if kind == "marker":
            seen_marker = True
        elif seen_marker and kind in _api.ANSWER_MEDIA_KINDS:
            return True
    return False

has_answer_media.__module__ = _api.__name__
_api.has_answer_media = has_answer_media

def add_poster(q_el: _api.ET.Element, tag, ref: str) -> bool:
    """Кладёт картинку в ответ вопроса. False — класть было некуда.

    Формат берём тот, какой у вопроса: v5 — <item type="image" isRef="True">
    в параметре ответа, v4 — <atom type="image">@файл</atom> за маркером
    сценария. Таймера на постере нет: без duration он висит, пока ведущий не
    пойдёт дальше (просьба пользователя)."""
    if not ref:
        return False
    if _api.child(q_el, "params") is None and _api.child(q_el, "scenario") is not None:
        scenario = _api.scenario_answer_tail(q_el, tag)
        if scenario is None:
            return False
        atom = _api.ET.SubElement(scenario, tag("atom"), {"type": "image"})
        atom.text = "@" + ref
        return True
    item = _api.ET.SubElement(_api.answer_content(q_el, tag), tag("item"),
                         {"type": "image", "isRef": "True"})
    item.text = ref
    return True

add_poster.__module__ = _api.__name__
_api.add_poster = add_poster

def remove_poster(q_el: _api.ET.Element, ref: str) -> bool:
    """Убирает из вопроса картинку, которую туда положил add_poster.

    Нужно, когда постер уже вписан в ответ, а скачать или закодировать его так и
    не вышло: ссылка на файл, которого в паке нет, — это дырка в вопросе."""
    if not ref:
        return False
    for parent in q_el.iter():
        for el in list(parent):
            if _api.local(el.tag) in ("item", "atom") \
                    and (el.text or "").strip().lstrip("@") == ref:
                parent.remove(el)
                return True
    return False

remove_poster.__module__ = _api.__name__
_api.remove_poster = remove_poster

# ─────────────────────────────────────────────────────────────────────────────
# Функция 5: повторяющийся текст темы («Назвать аниме»)
# ─────────────────────────────────────────────────────────────────────────────
def question_items(q_el: _api.ET.Element) -> list[tuple[_api.ET.Element, _api.ET.Element,
                                                   str, str]]:
    """Содержимое САМОГО вопроса: [(родитель, элемент, тип, текст)].

    v5 держит его в <param name="question"> элементами <item>, v4 — в
    <scenario> атомами до маркера (всё, что после маркера, показывается уже как
    ответ, и к вопросу отношения не имеет). Тип по умолчанию — text: и там, и
    там его у текста обычно не пишут вовсе."""
    out: list[tuple[_api.ET.Element, _api.ET.Element, str, str]] = []
    for params in _api.children(q_el, "params"):
        for param in _api.children(params, "param"):
            if (param.get("name") or "") != "question":
                continue
            for item in _api.children(param, "item"):
                out.append((param, item, (item.get("type") or "text").lower(),
                            " ".join(str(item.text or "").split())))
    scenario = _api.child(q_el, "scenario")
    for atom in _api.children(scenario, "atom"):
        kind = (atom.get("type") or "text").lower()
        if kind == "marker":
            break
        out.append((scenario, atom, kind,
                    " ".join(str(atom.text or "").split())))
    return out

question_items.__module__ = _api.__name__
_api.question_items = question_items

def question_text_blocks(q_el: _api.ET.Element,
                         max_len: int = _api.REPEAT_TEXT_MAX_LEN) -> dict[str, str]:
    """{нормализованный текст: как он написан} — короткие текстовые блоки
    вопроса. Длинные не берём вовсе: это уже сам вопрос, а не подпись к нему."""
    out: dict[str, str] = {}
    for _parent, _el, kind, text in _api.question_items(q_el):
        key = _api.norm_title(text)
        if kind != "text" or not key or len(text) > max(1, int(max_len)):
            continue
        out.setdefault(key, text)
    return out

question_text_blocks.__module__ = _api.__name__
_api.question_text_blocks = question_text_blocks

def repeated_texts(questions: list, max_len: int = _api.REPEAT_TEXT_MAX_LEN
                   ) -> list[str]:
    """Тексты, стоящие в КАЖДОМ вопросе темы, — в порядке первого вопроса.

    Тема из одного вопроса не в счёт: «в каждом» там значит «в единственном», и
    убирать по такому правилу нечего."""
    if len(questions or []) < _api.REPEAT_MIN_QUESTIONS:
        return []
    first = _api.question_text_blocks(questions[0], max_len)
    if not first:
        return []
    common = set(first)
    for q in questions[1:]:
        common &= set(_api.question_text_blocks(q, max_len))
        if not common:
            return []
    return [text for key, text in first.items() if key in common]

repeated_texts.__module__ = _api.__name__
_api.repeated_texts = repeated_texts

def known_label_keys() -> set:
    """Известные подписи (KNOWN_LABELS) в сравнимом виде.

    Считается один раз на вызов — список короткий, а зовут функцию по разу на
    тему."""
    return {_api.norm_title(text) for text in _api.KNOWN_LABELS if _api.norm_title(text)}

known_label_keys.__module__ = _api.__name__
_api.known_label_keys = known_label_keys

def known_labels_in(questions: list, max_len: int = _api.REPEAT_TEXT_MAX_LEN
                    ) -> list[str]:
    """Известные подписи, встретившиеся в вопросах темы, — в порядке первого
    вопроса, где они попались.

    В отличие от repeated_texts, «в каждом вопросе» тут не требуется: подписи
    эти закрытым списком, и смысл у них один — сказать, что делать. Живой случай
    — тема «Hayami Saori»: «Назвать персонажа» стоит в семи вопросах из восьми, а
    восьмой спрашивает совсем другое; по правилу «в каждом» подпись оставалась
    во всех семи."""
    known = _api.known_label_keys()
    out: dict[str, str] = {}
    for q in questions or []:
        for key, text in _api.question_text_blocks(q, max_len).items():
            if key in known:
                out.setdefault(key, text)
    return list(out.values())

known_labels_in.__module__ = _api.__name__
_api.known_labels_in = known_labels_in

def drop_text_blocks(q_el: _api.ET.Element, keys: set) -> list[str]:
    """Убирает из вопроса текстовые блоки с такими текстами. Возвращает то, что
    реально убрано.

    Вопрос без содержимого не оставляем никогда: если убрать пришлось бы всё,
    что в нём есть, — не трогаем вовсе (пустой вопрос игре показать нечем)."""
    items = _api.question_items(q_el)
    doomed = [(parent, el, text) for parent, el, kind, text in items
              if kind == "text" and _api.norm_title(text) in (keys or set())]
    if not doomed or len(doomed) >= len(items):
        return []
    for parent, el, _text in doomed:
        parent.remove(el)
    return [text for _p, _el, text in doomed]

drop_text_blocks.__module__ = _api.__name__
_api.drop_text_blocks = drop_text_blocks
