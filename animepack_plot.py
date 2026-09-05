# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# animepack_plot.py — вопросы ПО СЮЖЕТУ: пересказ с фэндом-вики превращается в
# вопрос руками Gemini. Ни Qt, ни сети здесь нет: текст приносит
# animepack_api.FandomApi, в модель ходит gemini_api.GeminiClient (в тестах и
# то, и другое подменяется), а тут — только промпты и разбор ответа.
#
# Два рода вопроса (настройка «Вопрос по сюжету» на вкладке):
#   • «title» — ведущий читает эпизод сюжета, игроки называют ТАЙТЛ. Ответ и
#     цена считаются как у любого другого вопроса пака, ничего доверять модели
#     не приходится: название мы знаем сами. Название и имена героев из текста
#     вопроса вычищаются (mask_names) — иначе вопрос решается с первого слова.
#   • «detail» — вопрос про сам сюжет («Что сделал герой, когда…»), ответ —
#     короткая деталь, её называет модель. Тайтл в вопросе назван прямо.
#
# Модель обязана молчать (пустой вопрос), если пересказ невнятный: выдуманный
# сюжет в паке хуже, чем вопрос, которого нет — упавшего кандидата генератор
# просто заменит следующим.
from __future__ import annotations

import re
from typing import Any, Optional

# Что можно спросить по сюжету.
PLOT_MODES = ("title", "detail")
PLOT_MODE_LABELS = {"title": "Ответ — название аниме",
                    "detail": "Ответ — деталь сюжета"}

# Короче этого пересказ ни на что не годится: из двух строк аннотации вопроса
# не выйдет, а запрос к модели будет потрачен впустую.
MIN_PLOT_CHARS = 220
# Сколько страниц серий пробуем, прежде чем пойти в статью самого тайтла.
# Каждая страница — это запрос к вики, а раздел с пересказом есть далеко не у
# всякой (бывают заготовки в две строки).
EPISODE_TRIES = 5

SCHEMA_TITLE = {
    "type": "object",
    "properties": {
        "question": {
            "type": "string",
            "description": ("вопрос для игры: пересказ эпизода сюжета своими "
                            "словами, без названия и имён собственных"),
        },
        "ok": {
            "type": "boolean",
            "description": "false, если по этому тексту вопроса не выходит",
        },
    },
    "required": ["question", "ok"],
}

SCHEMA_DETAIL = {
    "type": "object",
    "properties": {
        "question": {"type": "string", "description": "вопрос по сюжету"},
        "answer": {"type": "string",
                   "description": "правильный ответ, 1–5 слов"},
        "alt": {
            "type": "array",
            "description": "другие написания того же ответа (можно пустой)",
            "items": {"type": "string"},
        },
        "ok": {"type": "boolean",
               "description": "false, если по этому тексту вопроса не выходит"},
    },
    "required": ["question", "answer", "ok"],
}

_RULES_COMMON = """Ты составляешь вопросы для игры «Своя игра» по аниме.
Тебе дают пересказ сюжета с фэндом-вики. Пиши ПО-РУССКИ, даже если пересказ на английском.

Общие правила:
1. Вопрос — одно-два предложения, не длиннее 300 символов. Живой человек должен прочитать его вслух за десять секунд.
2. Опирайся ТОЛЬКО на данный текст. Ничего не додумывай: выдуманный сюжет портит пак.
3. Если текст невнятный, обрывочный или это не пересказ событий (список серий, разметка, реклама вики) — верни ok=false и пустой вопрос.
4. Никакой разметки: ни звёздочек, ни ссылок, ни сносок."""

_RULES_TITLE = """
Вопрос должен описывать ЗАПОМИНАЮЩИЙСЯ эпизод сюжета так, чтобы смотревший узнал произведение, а не смотревший — нет.

Ещё правила:
5. НЕ называй ни само произведение, ни его героев по именам: игроки как раз и должны угадать тайтл. Вместо имён пиши «главный герой», «его напарница», «злодей».
6. Не пересказывай общеизвестную завязку из одной фразы («парень становится сильнейшим») — бери именно тот эпизод, который описан в тексте.
7. Начинай сразу с сути, без «В этом аниме…» и «Угадайте произведение…»."""

_RULES_DETAIL = """
Вопрос должен спрашивать КОНКРЕТНУЮ деталь сюжета, у которой один короткий ответ.

Ещё правила:
5. Произведение в вопросе называть МОЖНО и нужно — угадывают не его, а деталь.
6. Ответ — от одного до пяти слов (имя, предмет, место, число). Никаких «потому что…».
7. Ответ обязан прямо следовать из данного текста, дословно или почти. В alt положи другие написания того же ответа (перевод, ромадзи, сокращение) — или оставь список пустым.
8. Не спрашивай то, чего в тексте нет."""


def build_prompt(title: str, plot: str, mode: str = "title",
                 page: str = "") -> str:
    """Текст запроса к модели по одному тайтлу."""
    rules = _RULES_TITLE if mode != "detail" else _RULES_DETAIL
    head = [_RULES_COMMON + rules, ""]
    if mode == "detail":
        head.append(f"Произведение: {title}")
    if page:
        head.append(f"Страница вики: {page}")
    head += ["", "Пересказ сюжета:", str(plot or "").strip()]
    return "\n".join(head)


def _clean(text: Any) -> str:
    """Ответ модели в одну строку без разметки."""
    out = " ".join(str(text or "").split())
    out = re.sub(r"[*_`]+", "", out)
    return out.strip()


def mask_names(text: str, names) -> str:
    """Прячет названия и имена собственные в тексте вопроса.

    Модель иногда всё-таки называет тайтл («Как и в „Наруто“, герой…») — такой
    вопрос решается с первого слова. Вместо того чтобы выбрасывать вопрос
    целиком, затираем найденное многоточием: смысл остаётся, подсказка уходит.
    """
    out = str(text or "")
    words: list[str] = []
    for name in names or ():
        name = str(name or "").strip()
        if not name:
            continue
        words.append(name)
        # Отдельные слова названия тоже выдают тайтл («Атака титанов» →
        # «титанов»), но однобуквенные и служебные куски трогать нельзя.
        words += [w for w in re.split(r"[\s:,\-–—/]+", name) if len(w) >= 4]
    for word in sorted(set(words), key=len, reverse=True):
        out = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", "…", out,
                     flags=re.IGNORECASE)
    # Несколько затёртых слов подряд схлопываем в одно многоточие.
    out = re.sub(r"(?:…[\s«»\"'(),.]*){2,}", "… ", out)
    return " ".join(out.split()).strip(" ,;:")


def parse_answer(data: Any, mode: str = "title") -> tuple[str, list[str]]:
    """Ответ модели → (текст вопроса, варианты ответа).

    Пустой текст вопроса значит «не вышло»: генератор возьмёт следующий тайтл.
    Варианты ответа возвращаются только в режиме «detail» — в режиме «title»
    ответом служит само название тайтла, и берёт его сам генератор."""
    if not isinstance(data, dict):
        return "", []
    if data.get("ok") is False:
        return "", []
    question = _clean(data.get("question"))
    if not question:
        return "", []
    if mode != "detail":
        return question, []
    answers: list[str] = []
    for raw in [data.get("answer")] + list(data.get("alt") or []):
        text = _clean(raw)
        if text and text.casefold() not in {a.casefold() for a in answers}:
            answers.append(text)
    if not answers:
        return "", []
    return question, answers


def make_question(title: str, plot: str, client, *, mode: str = "title",
                  page: str = "", names=(),
                  temperature: float = 0.6) -> tuple[str, list[str]]:
    """Вопрос по пересказу сюжета: (текст, варианты ответа).

    («», []) — вопроса не вышло (пересказ короткий, модель отказалась). Ошибки
    самого gemini_api (нет ключа, кончилась квота) НЕ глушим: вкладке надо
    сказать пользователю, что именно случилось.

    temperature нарочно не нулевая: два вопроса подряд по похожим пересказам
    при нуле выходят близнецами."""
    text = str(plot or "").strip()
    if len(text) < MIN_PLOT_CHARS:
        return "", []
    schema = SCHEMA_DETAIL if mode == "detail" else SCHEMA_TITLE
    data = client.generate_json(build_prompt(title, text, mode, page), schema,
                                temperature=temperature)
    question, answers = parse_answer(data, mode)
    if question and mode != "detail":
        question = mask_names(question, names or (title,))
    if not question:
        return "", []
    return question, answers


def pick_plot(fandom, names, rng, *, log: Optional[Any] = None) -> dict:
    """Пересказ для одного тайтла: {"text", "page", "wiki"} или {}.

    Порядок такой: находим вики по названию (пробуем ромадзи, английское,
    русское — какое найдётся), берём случайную страницу СЕРИИ и из неё раздел
    с пересказом. Серий у вики может не быть вовсе (фильм, короткометражка) —
    тогда берём статью самого тайтла и её раздел «Сюжет».
    """
    names = [str(n or "").strip() for n in (names or ()) if str(n or "").strip()]
    wiki = fandom.find_wiki(names)
    if not wiki:
        return {}
    pages = list(fandom.episode_pages(wiki))
    rng.shuffle(pages)
    pages = pages[:EPISODE_TRIES]
    # Хвост подстрахует, если разделов с пересказом у серий не окажется (или
    # серий у вики нет вовсе — фильм, короткометражка): статья самого тайтла
    # есть всегда, и раздел «Сюжет» в ней тоже.
    if names:
        pages += [p for p in fandom.search(wiki, names[0], limit=3)
                  if p not in pages]
    for page in pages:
        body = fandom.page_text(wiki, page)
        chunk = fandom.plot_section(body)
        if len(chunk) >= MIN_PLOT_CHARS:
            return {"text": chunk, "page": page, "wiki": wiki}
    return {}
