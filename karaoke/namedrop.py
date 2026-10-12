"""Неймдроп: название тайтла в словах караоке-отрезка.

В караоке слова песни идут на экране, и опенинг, который поёт название своего
аниме («…Shingeki no Kyojin…»), отвечает на вопрос сам. Отрезок с таким
словом не берётся — генератор ищет в той же песне другой (просьба
пользователя)."""
from __future__ import annotations

import re
import unicodedata

# Короче этого название не ищем: «Air», «K» и «Kon» слишком часто встречаются
# в словах песен сами по себе.
MIN_LETTERS = 4
# Без пробелов (romaji «shingekinokyojin») сравниваем только длинные
# названия: короткое склеенное сочетается из соседних слогов случайно.
MIN_COMPACT = 7


def _normalize(value) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = text.replace("ё", "е")
    text = "".join(c for c in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(c))
    return " ".join("".join(c if c.isalnum() else " " for c in text).split())


def variants(names) -> list[str]:
    """Названия в сравнимом виде, без повторов и слишком коротких."""
    out = []
    for name in names:
        value = _normalize(name)
        if len(value.replace(" ", "")) >= MIN_LETTERS and value not in out:
            out.append(value)
    return out


def mentioned(lines, titles) -> str:
    """Какое из названий звучит в строках отрезка («» — ни одно).

    Строка показывается целиком, даже если отрезок задевает её краем, поэтому
    проверяется весь её текст и переводы."""
    texts = []
    for line in lines:
        texts.append(line.text)
        texts.extend((line.translations or {}).values())
    spaced = " " + " ".join(_normalize(text) for text in texts) + " "
    compact = spaced.replace(" ", "")
    for title in titles:
        if re.search(r"(?<!\w)" + re.escape(title) + r"(?!\w)", spaced):
            return title
        joined = title.replace(" ", "")
        if len(joined) >= MIN_COMPACT and joined in compact:
            return title
    return ""
