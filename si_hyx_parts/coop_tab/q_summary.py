# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_q_summary. Public namespace: coop_tab."""
import coop_tab as _api


# ══════════════════════════════════════════════════════════════════════════════
# Извлечение текстового «обзора» пака (slepok) из распарсенного SiqPackage
# ══════════════════════════════════════════════════════════════════════════════
def _q_summary(q: dict) -> dict:
    """Свести один вопрос к: цена, текст вопроса, ответ, маркеры медиа.

    Сам медиаконтент НЕ трогаем — фиксируем лишь наличие файла (фото/аудио/видео)
    в вопросе (`qm`) и в ответе (`am`)."""
    price = int(q.get("price", 0) or 0)
    qtext_parts, qmedia, amedia = [], set(), set()
    for it in q.get("items", []):
        param = it.get("param", "") or ""
        typ = it.get("type", "text") or "text"
        is_ref = bool(it.get("is_ref", False))
        placement = it.get("placement", "") or ""
        text = (it.get("text") or "").strip()
        is_answer = (param == "answer")
        if typ in _api._MEDIA_KINDS and is_ref:
            (amedia if is_answer else qmedia).add(typ)
        elif typ == "text" and not is_ref and placement != "replic":
            # Контент вопроса: param 'question'/'' (старый формат) или фон.
            if param in ("question", "", "background") and text:
                qtext_parts.append(text)
    answers = [a.strip() for a in q.get("answers", []) if a and a.strip()]
    out = {
        "price": price,
        "q": " ".join(qtext_parts).strip(),
        "a": " / ".join(answers),
        "qm": sorted(qmedia),
        "am": sorted(amedia),
    }
    # Вопрос с выбором варианта: правильный ответ записан меткой («B»), а не
    # текстом. Помечаем, чтобы такие ответы не сравнивались между собой (см.
    # _is_option_answer). Ключ кладём только когда он есть — обзор уходит по
    # сети, лишнее поле на каждый вопрос ни к чему.
    if q.get("answer_options"):
        out["opt"] = True
    return out

_q_summary.__module__ = _api.__name__
_api._q_summary = _q_summary
