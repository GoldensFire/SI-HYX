# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Какие метки Pixiv отсекать — встроенные группы плюс правки пользователя.

Собирается один раз на прогон и живёт в клиенте (`PixivArtClient.rules`).
Отсюда берутся обе проверки: хвост минусов для самого запроса и отбор по
тегам уже пришедшей выдачи.

Правки с вкладки (см. окно «Исключаемые теги»):

* `pixiv_groups_off` — ключи целиком выключенных групп;
* `pixiv_tags_off` — отдельные снятые метки (из любой группы);
* `pixiv_tags_extra` — свои метки пользователя; они идут в запрос ПЕРВЫМИ,
  потому что просил их именно он, а места в запросе всего 256 символов.
"""
from __future__ import annotations

import pixiv_art_tags as tags


class TagRules:
    """Метки-исключения: отбор у себя (`hits`) и минусы в запрос (`query_tail`)."""

    def __init__(self, exact=(), fragments=(), minus=()):
        # Метки целиком сравниваются с тегом целиком: иначе «3d» находилось бы
        # внутри «3days». Обрывки ищутся подстрокой — их пишут слитно с
        # остальным текстом метки.
        self.exact = {str(t).casefold().replace(" ", "").replace("_", "")
                      for t in exact}
        self.fragments = tuple(str(t).casefold() for t in fragments)
        self.minus = tuple(minus)

    @classmethod
    def from_settings(cls, settings=None, allow_same_sex=False) -> "TagRules":
        """Правила по настройкам пака (без настроек — всё встроенное)."""
        off_groups = {str(k) for k in
                      (getattr(settings, "pixiv_groups_off", None) or [])}
        if allow_same_sex:
            # Однополые пары слушаются своей галочки на вкладке.
            off_groups.add(tags.SAME_SEX_GROUP)
        off_terms = {t.casefold() for t in
                     tags.clean_terms(getattr(settings, "pixiv_tags_off", None))}
        extra = tags.clean_terms(getattr(settings, "pixiv_tags_extra", None))
        exact, fragments, minus = set(extra), [], list(extra)
        for key, _title, _hint, group_tags, group_fragments, locked in tags.GROUPS:
            if key in off_groups and not locked:
                continue
            live_tags = [t for t in sorted(group_tags)
                         if t.casefold() not in off_terms]
            live_fragments = [t for t in group_fragments
                              if t.casefold() not in off_terms]
            exact.update(live_tags)
            fragments += live_fragments
            # В запрос метки идут группами по порядку: шок первым, дальше по
            # убыванию вреда. Что не влезло в 256 символов — отсеется у себя.
            minus += live_fragments + live_tags
        return cls(exact, fragments, minus)

    def hits(self, names) -> bool:
        """Есть ли среди меток работы хоть одна запрещённая."""
        flat = {str(n).casefold().replace(" ", "").replace("_", "")
                for n in names}
        if flat & self.exact:
            return True
        return any(fragment in name
                   for name in flat for fragment in self.fragments)

    def query_tail(self, word: str, limit: int = 0, first=()) -> str:
        """Хвост «-метка -метка …» под запрос, урезанный по длине.

        Минус понимает только поиск «по части тега», и длина всего запроса у
        Pixiv ограничена 256 символами — что не поместилось, отсечётся уже
        своим отбором. Метки с пробелом внутри пропускаем: Pixiv разберёт
        такую как «минус первое слово И обязательное второе», и выдача
        схлопнется в ноль.

        `first` — метки, которые должны уйти в запрос раньше остальных: туда
        кладётся R-18 в режиме «исключать». Одна эта метка убирает из выдачи
        больше работ, чем все списки вместе (замерено: 9 работ из 210 против
        8), и места в запросе стоит всего семь символов."""
        limit = limit or tags.QUERY_LIMIT
        out, size = [], len(word)
        seen = set()
        for term in list(first) + list(self.minus):
            term = str(term).strip()
            key = term.casefold()
            if not term or " " in term or key in seen:
                continue
            if size + len(term) + 2 > limit:
                break
            seen.add(key)
            out.append("-" + term)
            size += len(term) + 2
        return " ".join(out)
