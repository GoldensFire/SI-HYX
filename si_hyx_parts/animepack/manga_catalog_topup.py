# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Добор манхвы и маньхуа в каталог книг. Namespace: animepack.

Зачем отдельный запрос. Каталог книг набирается одним общим запросом по всем
разрешённым типам, и каталог этот японский: на странице в пятьдесят карточек
попадается семь манхв и НИ ОДНОЙ маньхуа (замерено на живом API). Доли «манхва»
и «маньхуа» из настроек при этом считаются от книжной доли пака, и просьба
«четверть книг — корейские» упиралась не в фильтры, а в то, что подходящих
карточек в мешке просто не было: лишние японские книги уходили на скамейку,
каталог объявлялся просмотренным, скамейка шла в дело — и доли переставали
сторожиться вовсе (в логе пользователя: «подходящих книг в каталоге не
хватило — беру отложенные (1320 шт.)»).

Поэтому у Shikimori спрашиваем эти издания ОТДЕЛЬНО: `kind: "manhwa"` отдаёт
ровно манхву. Один-два десятка страниц — и доля набирается из настоящих
кандидатов, а не из того, что случайно попалось.
"""
from __future__ import annotations
import animepack as _api
from .manga_editions import shares


# Издания со своей долей в книжной части пака и их русские имена (те же, что
# в MANGA_KIND_LABELS у animepack_api).
EDITIONS = {"manhwa": "Манхва", "manhua": "Манхуа"}
# Столько страниц на издание — потолок. Пятьдесят карточек на страницу: даже
# десяти хватает на долю в сотню вопросов, а дальше каталог такого издания
# обычно и кончается.
MAX_PAGES = 20


def edition_want(self, edition: str) -> int:
    """Сколько карточек этого издания нужно в каталоге (0 — не нужно вовсе)."""
    quota = int(self.s.question_quotas.get(_api.MANGA_KIND, 0) or 0)
    pct = shares(self.s).get(edition, 0)
    if not quota or not pct or not self.s.manga_kinds.get(edition):
        return 0
    questions = int(round(quota * pct / 100.0))
    return questions * self.RANDOM_OVERSHOOT_MANGA


def topup_editions(self, sig: str, take) -> None:
    """Дочерпывает манхву и маньхуа, если их в мешке меньше, чем нужно доле.

    take — та же функция, что складывает карточки в мешок генератора; она же
    отсеивает повторы и возвращает, сколько карточек оказалось новыми."""
    season = f"{int(self.s.year_from)}_{int(self.s.year_to)}"
    for edition in EDITIONS:
        if self.stopped():
            return
        want = edition_want(self, edition)
        if not want:
            continue
        have = sum(1 for card in self._manga_cache.values()
                   if str(card.get("kind") or "") == edition)
        if have >= want:
            continue
        name = EDITIONS[edition]
        self.log(f"{name}: в общем каталоге нашлось {have} — беру ещё "
                 "отдельным запросом, иначе доля не наберётся.")
        for page in range(1, MAX_PAGES + 1):
            if self.stopped() or have >= want:
                break
            try:
                cards = self.shikimori.random_mangas(
                    page, season=season, kinds=[edition],
                    score=int(self.s.score_from),
                    genres_exclude=self.s.genres_exclude)
            except _api.AnimePackApiError as e:
                self.log(f"Shikimori ({name}): {e} — беру, что успел набрать")
                break
            if not cards:
                break
            fresh = take(cards)
            self.db_cache.add_cards("manga", sig, cards)
            have += sum(1 for card in cards
                        if str(card.get("kind") or "") == edition)
            if not fresh:
                break             # каталог этого издания кончился
        self.log(f"{name}: в каталоге теперь {have} карточек.")
        from .generation_checkpoint import checkpoint
        checkpoint(self)

