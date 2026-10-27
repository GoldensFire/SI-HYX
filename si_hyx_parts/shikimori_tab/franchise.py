# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Ключ франшизы и сравнение названий. Public namespace: shikimori_tab."""
import shikimori_tab as _api


def _franchise_key(s: str) -> str:
    """«Ключ франшизы» — базовое название без сезона/части И без подзаголовка:
    «Атака титанов 2» → «атака титанов», «Наруто: Ураганные хроники» → «наруто»,
    «Бездомный бог: Арагото» → «бездомный бог», «Shingeki no Kyojin Season 2» →
    «shingeki no kyojin». Нужен, чтобы схлопывать сезоны/части одной франшизы в
    выдаче и чтобы пак с «Наруто» прятал и «Наруто: Ураганные хроники»."""
    s = _api._SUBTITLE_RX.sub("", _api._norm_title(s)).strip()
    # Финальная зачистка пунктуации: после снятия сезона мог «обнажиться» хвостовой
    # знак, который _norm_title уже срезал у пака — иначе «Этот замечательный мир!»
    # (пак) ≠ «Этот замечательный мир! 2» (выдача) из-за «!».
    return _api._base_title(s).strip(" .!?–—-:;\"'«»()[]")

_franchise_key.__module__ = _api.__name__
_api._franchise_key = _franchise_key

def _title_words(s: str) -> list:
    """Слова названия (дефис = разделитель, как пробел): «девочки-мечтательницы»
    → [«девочки», «мечтательницы»], чтобы дефисные/пробельные варианты одного
    тайтла дробились на слова одинаково."""
    return [w for w in _api.re.split(r"[\s\-–—]+", s) if w]

_title_words.__module__ = _api.__name__
_api._title_words = _title_words

def _same_franchise_prefix(a: str, b: str, min_words: int = 4) -> bool:
    """True, если два «ключа франшизы» — это один длинный тайтл, различающийся
    лишь последним словом. Нужно для франшиз без сезонного маркера и подзаголовка-
    через-двоеточие, где части отличаются только хвостовым словом: «Этот глупый
    свин не понимает мечту девочки зайки» vs «…девочки-мечтательницы». Порог
    min_words=4 защищает короткие названия от ложного слияния."""
    aw, bw = _api._title_words(a), _api._title_words(b)
    if len(aw) < min_words or len(bw) < min_words or abs(len(aw) - len(bw)) > 1:
        return False
    n = 0
    for x, y in zip(aw, bw):
        if x != y:
            break
        n += 1
    # Общий префикс — всё, кроме последнего слова более короткого названия.
    return n >= min(len(aw), len(bw)) - 1

_same_franchise_prefix.__module__ = _api.__name__
_api._same_franchise_prefix = _same_franchise_prefix

def _franchise_prefix_index(keys, min_words: int = 4) -> set:
    """Индекс для _matches_franchise_prefix: (число слов, префикс без последнего
    слова) и (число слов, префикс без двух последних) каждого ключа. Перебор
    _same_franchise_prefix по всем исключённым франшизам на каждый тайтл
    вешал «По кэшу» на тысячах тайтлов × тысячах франшиз из паков."""
    index = set()
    for k in keys:
        w = _api._title_words(k)
        n = len(w)
        if n >= min_words:
            index.add((n, tuple(w[:n - 1])))
            index.add((n, tuple(w[:n - 2])))
    return index

_franchise_prefix_index.__module__ = _api.__name__
_api._franchise_prefix_index = _franchise_prefix_index

def _matches_franchise_prefix(key: str, index: set, min_words: int = 4) -> bool:
    """То же, что any(_same_franchise_prefix(key, ex) for ex in keys), но за
    O(1) по индексу _franchise_prefix_index(keys). Ключ длины m совпадает с
    ключом длины m (общие m-1 слов), m+1 (общие m-1) или m-1 (общие m-2)."""
    w = _api._title_words(key)
    m = len(w)
    if m < min_words or not index:
        return False
    head = tuple(w[:m - 1])
    return ((m, head) in index or (m + 1, head) in index
            or (m - 1 >= min_words and (m - 1, tuple(w[:m - 2])) in index))

_matches_franchise_prefix.__module__ = _api.__name__
_api._matches_franchise_prefix = _matches_franchise_prefix
