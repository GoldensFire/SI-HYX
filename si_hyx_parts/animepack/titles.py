# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Названия: ответ без года, корни ответов .siq, ключи франшиз и корни названий. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


def answer_title(text) -> str:
    """Название тайтла из строки правильного ответа (без песни, года и тега)."""
    line = str(text or "").strip()
    line = _api._RE_ANSWER_SONG.sub("", line)
    line = _api._RE_ANSWER_YEAR.sub("", line)
    line = _api._RE_ANSWER_TAG.sub("", line)
    return line.strip()

answer_title.__module__ = _api.__name__
_api.answer_title = answer_title

def siq_answer_roots(path: str) -> set[str]:
    """Корни названий, спрошенных в готовом паке .siq.

    Нужны для галочки «не повторять франшизы из этих паков»: читаем только
    content.xml (это миллисекунды, медиа из архива не достаём), берём ВСЕ
    варианты правильного ответа и сводим каждый к корню названия — так «Наруто:
    Ураганные хроники» схлопнется с «Наруто»."""
    roots: set[str] = set()
    try:
        with _api.zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith("content.xml")]
            if not names:
                return roots
            root_el = _api.ET.fromstring(zf.read(names[0]))
    except Exception:  # noqa: BLE001 — битый или чужой файл просто пропускаем
        return roots
    for ans in root_el.iter():
        if not ans.tag.rsplit("}", 1)[-1] == "answer":
            continue
        rt = _api.title_root(_api.answer_title(ans.text))
        if rt:
            roots.add(rt)
    return roots

siq_answer_roots.__module__ = _api.__name__
_api.siq_answer_roots = siq_answer_roots

def franchise_key(anime: dict) -> str:
    """Ключ франшизы. Пустая франшиза у Shikimori значит «одиночный тайтл» —
    такие нельзя схлопывать между собой, поэтому ключ делаем уникальным."""
    fr = str(anime.get("franchise") or "").strip()
    if fr == "science_adventure":
        branch = _api.franchise_branch_key(anime)
        if branch:
            return f"{fr}:{branch}"
    return fr or f"#{anime.get('malId') or anime.get('id')}"

franchise_key.__module__ = _api.__name__
_api.franchise_key = franchise_key


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


def has_cjk(text) -> bool:
    """Есть ли в строке иероглифы/кана/хангыль."""
    return bool(_api._RE_CJK.search(str(text or "")))

has_cjk.__module__ = _api.__name__
_api.has_cjk = has_cjk
