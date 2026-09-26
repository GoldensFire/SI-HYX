# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_translit_fold. Public namespace: shikimori_tab."""
import shikimori_tab as _api


def _translit_fold(s: str) -> str:
    for a, b in _api._TRANSLIT_FOLDS:
        s = s.replace(a, b)
    return s

_translit_fold.__module__ = _api.__name__
_api._translit_fold = _translit_fold

def _norm_title(s: str) -> str:
    """Нормализация названия для сравнения с ответами паков: нижний регистр,
    схлопнутые пробелы, без хвостовой пунктуации/скобок-сезонов по краям.

    Хвостовой год-уточнитель в скобках убираем («hunter x hunter (1999)» →
    «hunter x hunter»): на Shikimori разные экранизации различаются годом
    («(1999)» и «(2011)»), и без снятия года исключение пака с одной версией
    не скрывало бы из выдачи другую (это и есть кейс «Охотник х Охотник»).

    Хвостовой маркер версии «√…» убираем («Токийский гуль √A» → «Токийский
    гуль»): √A/√R — это пометки сезонов, которых в названии пака обычно нет."""
    s = (s or "").lower().strip()
    s = _api.re.sub(r"\s+", " ", s)
    s = _api.re.sub(r"\s*[\(\[]\s*(?:19|20)\d{2}\s*[\)\]]\s*$", "", s)
    s = _api.re.sub(r"\s*√\s*\S*$", "", s)
    s = _api._translit_fold(s)
    s = s.strip(" .!?–—-:;\"'«»()[]")
    return s

_norm_title.__module__ = _api.__name__
_api._norm_title = _norm_title
