# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Анаграмма названия: буквы нужного письма и перестановка. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


def _is_lang_script(text: str, lang: str) -> bool:
    """Написано ли название той письменностью, какой ждут от этого языка."""
    cyr = bool(_api._RE_CYRILLIC.search(text))
    lat = bool(_api._RE_LATIN.search(text))
    if lang == "russian":
        return cyr and not lat
    return lat and not cyr

_is_lang_script.__module__ = _api.__name__
_api._is_lang_script = _is_lang_script


def _letters_count(text: str) -> int:
    return sum(1 for ch in str(text or "") if _api._ANAGRAM_LETTER.match(ch))

_letters_count.__module__ = _api.__name__
_api._letters_count = _letters_count


def _letter_runs(text: str) -> list[list[int]]:
    """Позиции букв, разбитые по словам: подряд идущие буквы — одно слово.

    Всё, что буквой не считается (пробел, дефис, апостроф, двоеточие, цифра),
    слово обрывает и остаётся на своём месте."""
    runs: list[list[int]] = []
    cur: list[int] = []
    for i, ch in enumerate(text):
        if _api._ANAGRAM_LETTER.match(ch):
            cur.append(i)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return runs

_letter_runs.__module__ = _api.__name__
_api._letter_runs = _letter_runs


def make_anagram(title: str, rng: _api.Optional[_api.random.Random] = None) -> str:
    """Анаграмма названия: в каждом слове перемешаны ЕГО СОБСТВЕННЫЕ буквы.

    Буквы не переезжают из слова в слово (просьба пользователя): «Мастера меча
    онлайн» даёт «АРЕТСАМ АЧЕМ НЙАЛНО», и в каждом слове ровно тот набор букв,
    что был в нём. Раньше буквы мешались по всему названию сразу — «Охотник х
    Охотник» превращался в «ОКИТИХХ Х ОТНКОНО», где второе слово составлено из
    чужих букв, и разгадывать было нечем.

    Форма слов при этом сохраняется — сколько слов и какой длины было, столько
    и останется (знаки, цифры и пробелы стоят на прежних местах). Регистр
    приводим к прописным целиком: иначе заглавная буква выдавала бы начало
    настоящего слова.

    Результат гарантированно отличается от исходника; на пустое, слишком
    короткое или неперемешиваемое название («Я И ТЫ», «ААА») возвращается «»."""
    text = " ".join(str(title or "").split())
    if _api._letters_count(text) < _api.ANAGRAM_MIN_LETTERS:
        return ""
    rng = rng or _api.random.Random()
    upper = text.upper()
    out = list(upper)
    changed = False
    for spots in _api._letter_runs(upper):
        letters = [upper[i] for i in spots]
        # Одна буква или сплошь одинаковые («ААА») — мешать в этом слове нечего.
        if len(set(letters)) < 2:
            continue
        # Несколько попыток: у короткого слова перестановка запросто совпадает
        # с исходной, и одной попытки мало.
        for _ in range(12):
            shuffled = list(letters)
            rng.shuffle(shuffled)
            if shuffled != letters:
                for pos, ch in zip(spots, shuffled):
                    out[pos] = ch
                changed = True
                break
    return "".join(out) if changed else ""

make_anagram.__module__ = _api.__name__
_api.make_anagram = make_anagram


def anagram_seconds(text: str, chars_per_sec: float = _api.ANAGRAM_CHARS_PER_SEC) -> int:
    """Сколько секунд держать анаграмму на экране (0 — без таймера).

    Считаются ВСЕ символы вопроса, вместе с пробелами и знаками: игрок видит
    именно их. Дробь округляется ВВЕРХ — обрывать показ на середине секунды
    незачем, — а совсем короткому тексту достаётся ANAGRAM_MIN_SECONDS."""
    cps = max(0.0, float(chars_per_sec or 0.0))
    length = len(str(text or ""))
    if cps <= 0 or not length:
        return 0
    return max(_api.ANAGRAM_MIN_SECONDS, _api.math.ceil(length / cps))

anagram_seconds.__module__ = _api.__name__
_api.anagram_seconds = anagram_seconds


def anagram_source(anime: dict, lang: str = "russian",
                   max_chars: int = 0) -> str:
    """Название, из которого делается анаграмма («» — годного нет).

    Язык берётся с карточки Shikimori СТРОГО тот, что просят: русское —
    russian, английское — english, ромадзи — name. Подмены на соседний язык
    больше нет (просьба пользователя): раньше при отсутствующем, слишком
    коротком или слишком длинном русском названии вопрос молча уезжал на
    латиницу, и в русском паке всплывали анаграммы вида «HHA CEYIG MOR NN».
    Теперь такой тайтл просто уступает место следующему.

    Заодно проверяется сама письменность: у Shikimori в поле russian нередко
    лежит латиница («Ao Ashi»), а в name — иероглифы. Для русского нужны
    кириллические буквы и ни одной латинской, для английского и ромадзи —
    наоборот.

    Отсеиваются и продолжения с приписками — «Мастера меча онлайн:
    Порядковый ранг», «Второй Мэйджор 2», «Log Horizon: Entaku Houkai»
    (см. is_plain_title): в анаграмму идёт только простое название.

    max_chars (0 — без потолка) отсекает названия-простыни."""
    card = anime or {}
    by_lang = {"russian": card.get("russian"), "english": card.get("english"),
               "romaji": card.get("name")}
    key = lang if lang in _api.ANAGRAM_LANGS else "russian"
    text = " ".join(str(by_lang.get(key) or "").split())
    limit = max(0, int(max_chars or 0))
    if not text or (limit and len(text) > limit):
        return ""
    if _api.has_cjk(text) or not _api._is_lang_script(text, key):
        return ""
    if _api._letters_count(text) < _api.ANAGRAM_MIN_LETTERS or not _api.is_plain_title(text):
        return ""
    return text

anagram_source.__module__ = _api.__name__
_api.anagram_source = anagram_source
