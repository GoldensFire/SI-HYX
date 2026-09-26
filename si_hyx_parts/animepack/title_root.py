# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""title_root. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


def title_root(name) -> str:
    """Корень названия: «Доктор Стоун: Научное будущее. Часть 3» → «доктор
    стоун». Пустая строка — корня нет (сравнивать не с чем)."""
    text = str(name or "").strip()
    if not text:
        return ""
    text = _api._RE_TITLE_TAIL.sub("", text)
    text = _api.re.sub(r"[\s.,!?:;]+$", "", text)     # хвостовая пунктуация
    text = _api._RE_TITLE_TRAIL_ABBR.sub("", text)    # «Покемон XY» → «Покемон»
    text = _api._RE_TITLE_TRAIL_NUM.sub("", text)
    text = _api.re.sub(r"[\s.,!?:;]+", " ", text).strip().casefold()
    # Слишком короткий корень («Ван», «Ай») схлопнул бы посторонние тайтлы.
    return text if len(text) >= 5 else ""

title_root.__module__ = _api.__name__
_api.title_root = title_root

def is_plain_title(name) -> bool:
    """Простое ли это название — без хвоста сезона, части и подзаголовка.

    «Мастера меча онлайн» — да; «Мастера меча онлайн: Порядковый ранг»,
    «Второй Мэйджор 2», «Трусливый велосипедист: Новое поколение», «Log
    Horizon: Entaku Houkai» — нет. Отличается от title_root тем, что ничего не
    обрезает, а отвечает на вопрос «обрезать вообще есть что?»: хвост нашёлся —
    значит перед нами продолжение или побочка.

    Нужно анаграммам (просьба пользователя): загадывать надо сам тайтл, а не
    его третий сезон с приставкой — по перемешанным буквам подзаголовка ответ
    всё равно никто не наберёт."""
    text = " ".join(str(name or "").split())
    if not text:
        return False
    # Восклицание в конце («Убийца Акамэ!», «Маленькие проказники!») — часть
    # самого названия, а не приписка: снимаем его с ОБЕИХ сравниваемых строк.
    bare = _api._RE_TRAIL_PUNCT.sub("", text)
    core = _api._RE_TITLE_TAIL.sub("", text)
    core = _api._RE_TRAIL_PUNCT.sub("", core)
    core = _api._RE_TITLE_TRAIL_NUM.sub("", core)          # «… 2», «… II»
    return " ".join(core.split()) == bare

is_plain_title.__module__ = _api.__name__
_api.is_plain_title = is_plain_title

def song_kind(song_type: str) -> _api.Optional[str]:
    """«Opening 1» → «opening». None — незнакомый тип."""
    head = str(song_type or "").split(" ")[0].lower()
    return head if head in _api.SONG_KINDS else None

song_kind.__module__ = _api.__name__
_api.song_kind = song_kind
