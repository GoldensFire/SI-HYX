"""Shared title question labels.

«Зашифрованное название» (локальный сдвиг русского алфавита) из пака убрано
по просьбе пользователя: загадка решалась механически и в игре не работала.
"""

TITLE_LABELS = {
    "synonyms": "Синонимы названия",
    "antonyms": "Антонимы названия",
    "ukrainian": "Название на украинском",
    "definitions": "Название через определения",
}
TITLE_KINDS = tuple(TITLE_LABELS)
# Все оставшиеся загадки по названию делает Gemini.
GEMINI_TITLE_KINDS = TITLE_KINDS
