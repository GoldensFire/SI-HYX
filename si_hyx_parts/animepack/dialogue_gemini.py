# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Выбор диалога через Gemini: модель читает ВСЮ серию и берёт узнаваемое.

Раньше отрывок выбирала эвристика (pick_excerpt): 2–4 длинные реплики с
вопросами. Она не знала, о чём аниме, и в пак шли разговоры вроде «Почему ты
вернулся так поздно?» — такое могло прозвучать где угодно, и угадать тайтл
было нельзя (просьба пользователя). Теперь Gemini получает пронумерованные
реплики всей серии и выбирает подряд идущий отрывок, по которому смотревший
реалистично узнает ИМЕННО это аниме: его понятия, устройство мира, приметные
ситуации и фразы, — но без названия и имён.

Модели верим только в выборе: текст реплик берётся из самих субтитров по
номерам, которые она назвала, а перевод (у Jimaku) проверяется построчно, как
раньше. Один ответ — один запрос из суточных двадцати, поэтому на кандидата
их не больше GEMINI_TRIES.
"""
from __future__ import annotations

import animepack as _api
from .dialogue_questions import (_clean, _ends_sentence, _name_leak,
                                 _sentence_rows, _starts_sentence,
                                 parse_subtitles)

# Сколько серий одного тайтла показать Gemini, прежде чем сдаться.
GEMINI_TRIES = 2
# Потолок текста серии в запросе: обычная серия — 15–25 тысяч знаков.
MAX_EPISODE_CHARS = 60000
MIN_LINES, MAX_LINES = 2, 4

DIALOGUE_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "start": {"type": "integer"},
        "count": {"type": "integer"},
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "translation": {"type": "string"},
                    "contains_name": {"type": "boolean"},
                },
                "required": ["translation", "contains_name"],
            },
        },
        "clue": {"type": "string"},
    },
    "required": ["found", "start", "count", "lines", "clue"],
}


def episode_lines(data: bytes, name: str) -> list[str]:
    """Все законченные реплики серии по порядку."""
    rows = _sentence_rows(parse_subtitles(data, name))
    lines, total = [], 0
    for _start, _end, text in rows:
        total += len(text) + 8
        if total > MAX_EPISODE_CHARS:
            break
        lines.append(text)
    return lines


def build_prompt(lines: list[str], title: str, episode: int,
                 translate: bool) -> str:
    numbered = "\n".join(f"{i}: {line}" for i, line in enumerate(lines))
    if translate:
        how = ("translation — перевод реплики на естественный русский язык "
               "без добавленных слов, пояснений и имён")
    else:
        how = "translation — та же реплика дословно, без изменений"
    return (
        "Ты готовишь вопрос для викторины «Угадай аниме по диалогу». Ниже — "
        f"все реплики {episode}-й серии аниме «{title}», пронумерованные по "
        "порядку. Прочитай серию целиком и пойми, что в ней происходит.\n\n"
        f"Выбери ОДИН отрывок из {MIN_LINES}–{MAX_LINES} реплик, идущих ПОДРЯД, "
        "по которому зритель, смотревший это аниме, реалистично узнает "
        "именно его. Отрывок должен опираться на то, что есть только в этом "
        "аниме: его особые понятия и термины, способности, устройство мира, "
        "узнаваемые ситуации, ключевые события или крылатые фразы. Общие "
        "бытовые разговоры, которые могли бы прозвучать в любом другом "
        "аниме, НЕ годятся. Отрывок не должен выдавать ответ слишком прямо: "
        "в нём нельзя название аниме, имена, фамилии и прозвища персонажей, "
        "обращения по имени. Реплики должны быть осмысленными и понятными "
        "без остальной серии.\n\n"
        "Если такого отрывка в серии нет — found=false. Иначе found=true, "
        "start — номер первой реплики отрывка, count — сколько реплик подряд, "
        f"lines — по одной записи на каждую реплику отрывка: {how}; "
        "contains_name — true, если в реплике есть имя, фамилия, прозвище или "
        "название. clue — одной фразой, чем отрывок выдаёт это аниме.\n\n"
        f"Реплики серии:\n{numbered}")


def accept(data, lines: list[str], names, translate: bool):
    """(реплики из субтитров, что показать игрокам); ([], []) — не годится."""
    if not isinstance(data, dict) or data.get("found") is not True:
        return [], []
    try:
        start, count = int(data.get("start")), int(data.get("count"))
    except (TypeError, ValueError):
        return [], []
    rows = data.get("lines")
    if (not MIN_LINES <= count <= MAX_LINES or start < 0
            or start + count > len(lines) or not isinstance(rows, list)
            or len(rows) != count):
        return [], []
    source = list(lines[start:start + count])
    if any(not isinstance(row, dict) or row.get("contains_name") is not False
           for row in rows):
        return [], []
    if translate:
        shown = []
        for text, row in zip(source, rows):
            value = _clean(row.get("translation") or "")
            if (not value or not _starts_sentence(value)
                    or not _ends_sentence(value)
                    or len(value) > max(180, len(text) * 3)):
                return [], []
            shown.append(value)
    else:
        # Русские субтитры показываем как есть: модель могла бы «поправить»
        # реплику, а в вопросе должен стоять настоящий текст серии.
        shown = source
    if _name_leak(source, names) or _name_leak(shown, names):
        return [], []
    return source, shown


def ask(self, cand, data: bytes, name: str, episode: int, names,
        translate: bool, budget: dict):
    """Спрашивает Gemini про одну серию.

    (реплики, показ) — отрывок выбран; ([], []) — в этой серии его нет;
    None — Gemini выключен или сломался, дальше не пробовать."""
    if self.gemini is None or budget.get("left", 0) <= 0:
        return None
    lines = episode_lines(data, name)
    if len(lines) < MIN_LINES:
        return [], []
    budget["left"] -= 1
    prompt = build_prompt(lines, cand.title_ru or str(names[0] or ""),
                          int(episode), translate)
    try:
        with self._timed("диалоги"):
            answer = self.gemini.generate_json(prompt, DIALOGUE_SCHEMA,
                                               temperature=0.2)
    except Exception as error:  # noqa: BLE001 — типы ошибок живут в gemini_api
        kind = type(error).__name__
        if kind in ("GeminiAuthError", "GeminiQuotaError"):
            self.gemini = None
            self._drop_kind(_api.DIALOGUE_KIND)
            cand.rejected = True
            self.log(f"Диалоги отключены: {error}")
            return None
        if kind == "GeminiBlockedError":
            return [], []
        self._log_rare("Выбор диалога", f"Gemini: {error}")
        return None
    return accept(answer, lines, names, translate)
