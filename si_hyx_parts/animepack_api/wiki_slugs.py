# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""wiki_slugs. Public namespace: animepack_api."""
from __future__ import annotations
import animepack_api as _api


def wiki_slugs(name: str) -> list[str]:
    """Адреса-кандидаты вики по названию тайтла.

    Fandom зовёт вики самим названием без пробелов («attackontitan») либо
    через дефис («kimetsu-no-yaiba») — оба написания и пробуем. Кириллица и
    иероглифы в адрес не годятся вовсе: русских вики по аниме на Fandom
    считаные, а адреса у них всё равно латиницей."""
    text = str(name or "").strip().lower()
    if not text:
        return []
    text = text.replace("'", "").replace("’", "")
    words = [w for w in _api.re.split(r"[^a-z0-9]+", text) if w]
    if not words:
        return []
    joined = "".join(words)
    if len(joined) < 3:
        return []
    out = [joined]
    dashed = "-".join(words)
    if dashed != joined:
        out.append(dashed)
    # Последняя надежда — самое длинное слово названия: «Neon Genesis
    # Evangelion» живёт на evangelion.fandom.com, «Mahou Shoujo Madoka Magica»
    # — на madoka.fandom.com. Семь букв уже достаточно: именно так «Grisaia no
    # Rakuen» находит общую grisaia.fandom.com. Однословный адрес всё равно
    # отдельно подтверждается поиском по названию в FandomApi._fits.
    if len(words) > 1:
        longest = max(words, key=len)
        if len(longest) >= 7 and longest not in out:
            out.append(longest)
    return out

wiki_slugs.__module__ = _api.__name__
_api.wiki_slugs = wiki_slugs

def plot_section(text: str, headings) -> str:
    """Раздел с пересказом из текста статьи («» — не нашёлся).

    Подходящих разделов бывает несколько («Short Summary» и «Long Summary» у
    вики One Piece) — берём САМЫЙ ДЛИННЫЙ: чем подробнее пересказ, тем есть о
    чём спрашивать. Слово-заголовок ищется целиком, поэтому годятся и
    «Summary», и «Long Summary», и «Plot Summary».

    Вынесено из класса, чтобы проверялось тестами без сети."""
    body = str(text or "")
    if not body:
        return ""
    wanted = [h.casefold() for h in headings]
    marks = list(_api._HEADING.finditer(body))
    best = ""
    for i, m in enumerate(marks):
        name = m.group(2).strip().casefold()
        if not any(_api.re.search(rf"(?<!\w){_api.re.escape(w)}(?!\w)", name)
                   for w in wanted):
            continue
        level = len(m.group(1))
        end = len(body)
        for nxt in marks[i + 1:]:
            if len(nxt.group(1)) <= level:
                end = nxt.start()
                break
        chunk = body[m.end():end].strip()
        if len(chunk) > len(best):
            best = chunk
    return best

plot_section.__module__ = _api.__name__
_api.plot_section = plot_section

def strip_wikitext(raw: str) -> str:
    """Грубая чистка разметки MediaWiki до читаемого текста.

    Задача не «сверстать статью», а отдать модели связные предложения: убираем
    шаблоны {{…}}, файлы, таблицы, теги и оставляем от ссылок их подпись."""
    text = str(raw or "")
    for _ in range(6):                      # шаблоны бывают вложенными
        new = _api.re.sub(r"\{\{[^{}]*\}\}", " ", text)
        if new == text:
            break
        text = new
    text = _api.re.sub(r"(?s)\{\|.*?\|\}", " ", text)          # таблицы
    text = _api.re.sub(r"(?s)<ref[^>]*>.*?</ref>", " ", text)  # сноски
    text = _api.re.sub(r"(?s)<!--.*?-->", " ", text)
    text = _api.re.sub(r"(?s)<[^>]+>", " ", text)
    text = _api.re.sub(r"\[\[(?:Файл|File|Image|Изображение):[^\]]*\]\]", " ", text,
                  flags=_api.re.IGNORECASE)
    text = _api.re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", text)   # [[цель|подпись]]
    text = _api.re.sub(r"\[\[([^\]]*)\]\]", r"\1", text)
    text = _api.re.sub(r"'{2,}", "", text)                          # ''курсив''
    text = _api.re.sub(r"^[*#:;]+", "", text, flags=_api.re.MULTILINE)
    text = _api.re.sub(r"[ \t]+", " ", text)
    # Вырезанные сноски и шаблоны оставляют после себя пробел перед точкой
    # («врага .») — на разбор моделью это не влияет, но лишний мусор в запросе
    # ни к чему.
    text = _api.re.sub(r"[ \t]+([,.:;!?)])", r"\1", text)
    return _api.re.sub(r"\n{3,}", "\n\n", text).strip()

strip_wikitext.__module__ = _api.__name__
_api.strip_wikitext = strip_wikitext
