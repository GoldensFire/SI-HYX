# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Чистка вопросов: склейка текста со звуком, пустые вопросы и темы. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


def merge_text_with_audio(q_el: _api.ET.Element) -> list[str]:
    """Текстовому блоку, за которым СРАЗУ идёт звук, ставит «играть
    одновременно». Возвращает тексты блоков, которые пришлось поправить.

    Так это записано у SIGame: v5 — waitForFinish="False" у <item> (по
    умолчанию true, ContentItem.cs), v4 — time="-1" у <atom> (Question.cs:
    WaitForFinish = atom.AtomTime != -1). Ни новых элементов, ни <params> тут не
    заводится — правится атрибут у того, что в вопросе уже есть, поэтому обоим
    форматам это безопасно.

    Уже включённое одновременное воспроизведение не трогаем: пользователь просил
    доделать за автором, а не переписать сделанное им."""
    items = _api.question_items(q_el)
    done: list[str] = []
    for i, (_parent, el, kind, text) in enumerate(items[:-1]):
        if kind not in _api.TEXT_KINDS or items[i + 1][2] not in _api.AUDIO_KINDS:
            continue
        if _api.local(el.tag) == "atom":
            if str(el.get("time") or "").strip() == "-1":
                continue
            el.set("time", "-1")
        else:
            if str(el.get("waitForFinish") or "").strip().lower() == "false":
                continue
            el.set("waitForFinish", "False")
        done.append(text)
    return done

merge_text_with_audio.__module__ = _api.__name__
_api.merge_text_with_audio = merge_text_with_audio

# ─────────────────────────────────────────────────────────────────────────────
# Функция «Удалить пустые вопросы»
# ─────────────────────────────────────────────────────────────────────────────
def is_empty_question(q_el: _api.ET.Element) -> bool:
    """Пусто ли в САМОМ вопросе: ни текста, ни картинки, ни звука, ни ролика.

    Ответ не в счёт нарочно (просьба пользователя: «даже если есть ответ»): на
    экране такой вопрос — пустота, играть в него нечем, сколько бы вариантов
    ответа под ним ни лежало. Содержимое берётся тем же question_items, что и
    уборка повторов: у v4 всё, что стоит ПОСЛЕ маркера, показывается уже как
    ответ, и вопросом не считается."""
    return not any(text.strip() for _parent, _el, _kind, text
                   in _api.question_items(q_el))

is_empty_question.__module__ = _api.__name__
_api.is_empty_question = is_empty_question

def empty_questions(root: _api.ET.Element) -> list[tuple]:
    """Пустые вопросы пака: [(раунд, тема, номер, контейнер, вопрос)].

    Контейнер (<questions>) отдаётся вместе с вопросом: в ElementTree элемент
    не знает своего родителя, а удалять его придётся именно из него. Номер —
    порядковый номер вопроса в паке, по нему правка встаёт в общую таблицу."""
    out: list[tuple] = []
    number = 0
    for r_idx, rnd in enumerate(_api.children(_api.child(root, "rounds"), "round")):
        rname = rnd.get("name") or f"Раунд {r_idx + 1}"
        for theme in _api.children(_api.child(rnd, "themes"), "theme"):
            box = _api.child(theme, "questions")
            for q in _api.children(box, "question"):
                if _api.is_empty_question(q):
                    out.append((rname, str(theme.get("name") or ""), number,
                                box, q))
                number += 1
    return out

empty_questions.__module__ = _api.__name__
_api.empty_questions = empty_questions

def drop_empty_themes(root: _api.ET.Element) -> list[tuple[str, str]]:
    """Убирает темы, оставшиеся без единого вопроса (и раунды без тем).

    Тему без вопросов SIGame показывает пустой строкой на табло, а раунд без тем
    и вовсе некуда играть. Возвращает [(раунд, тема)] убранного."""
    gone: list[tuple[str, str]] = []
    rounds_el = _api.child(root, "rounds")
    for r_idx, rnd in enumerate(_api.children(rounds_el, "round")):
        rname = rnd.get("name") or f"Раунд {r_idx + 1}"
        themes_el = _api.child(rnd, "themes")
        for theme in _api.children(themes_el, "theme"):
            if _api.children(_api.child(theme, "questions"), "question"):
                continue
            themes_el.remove(theme)
            gone.append((rname, str(theme.get("name") or "")))
        if rounds_el is not None and not _api.children(themes_el, "theme"):
            rounds_el.remove(rnd)
    return gone

drop_empty_themes.__module__ = _api.__name__
_api.drop_empty_themes = drop_empty_themes
