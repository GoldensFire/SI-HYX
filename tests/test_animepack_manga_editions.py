# -*- coding: utf-8 -*-
"""Манхва и маньхуа добираются отдельным запросом к каталогу Shikimori.

В общем каталоге книг они почти не попадаются (замерено: семь манхв и ни одной
маньхуа на пятьдесят карточек), поэтому доли изданий упирались не в фильтры, а
в пустой мешок кандидатов.
"""
from types import SimpleNamespace

from animepack import MANGA_KIND, PackSettings
from si_hyx_parts.animepack.manga_catalog_topup import (MAX_PAGES,
                                                        edition_want,
                                                        topup_editions)


class FakeShiki:
    """Каталог, где манхвы много, а маньхуа нет вовсе."""

    def __init__(self, per_kind=None):
        self.per_kind = per_kind or {"manhwa": 120, "manhua": 0}
        self.asked = []
        self._next = 1000

    def random_mangas(self, page, *, season="", kinds=(), score=0,
                      genres_exclude=()):
        kind = list(kinds)[0]
        self.asked.append((kind, page))
        left = self.per_kind.get(kind, 0) - (page - 1) * 50
        cards = []
        for _ in range(max(0, min(50, left))):
            self._next += 1
            cards.append({"id": self._next, "malId": self._next, "kind": kind,
                          "name": f"{kind} {self._next}"})
        return cards


def _generator(settings, shiki, cache=None):
    """То немногое от генератора, чем пользуется добор каталога."""
    said = []
    gen = SimpleNamespace(
        s=settings, shikimori=shiki, log=said.append, stopped=lambda: False,
        RANDOM_OVERSHOOT_MANGA=40, _manga_cache=dict(cache or {}),
        db_cache=SimpleNamespace(add_cards=lambda *a: None,
                                 save=lambda: None))
    gen.said = said
    return gen


def _take(gen):
    def take(cards):
        fresh = 0
        for card in cards:
            mal = int(card["malId"])
            if mal not in gen._manga_cache:
                gen._manga_cache[mal] = card
                fresh += 1
        return fresh
    return take


def _settings(**over):
    data = dict(pct_songs=0, pack_manga=True, pct_manga=100, rounds=1,
                themes=1, questions=10)
    data.update(over)
    return PackSettings(**data)


def test_manhwa_is_asked_for_by_its_own_kind():
    settings = _settings(manga_pct_manhwa=50)
    shiki = FakeShiki()
    gen = _generator(settings, shiki)
    topup_editions(gen, "sig", _take(gen))
    assert {kind for kind, _page in shiki.asked} == {"manhwa"}
    # Спрошено ровно столько страниц, сколько нужно доле (пять вопросов × 40).
    assert len(shiki.asked) == 4
    assert len(gen._manga_cache) == 120
    assert any("Манхва" in msg for msg in gen.said)


def test_empty_edition_stops_after_the_first_page():
    """Маньхуа в каталоге нет — страницы дальше не листаем."""
    settings = _settings(manga_pct_manhua=100)
    shiki = FakeShiki({"manhua": 0})
    gen = _generator(settings, shiki)
    topup_editions(gen, "sig", _take(gen))
    assert shiki.asked == [("manhua", 1)]
    assert len(shiki.asked) < MAX_PAGES


def test_nothing_is_asked_without_a_share_or_with_the_kind_switched_off():
    shiki = FakeShiki()
    gen = _generator(_settings(), shiki)             # доли изданий не заданы
    topup_editions(gen, "sig", _take(gen))
    assert shiki.asked == []

    settings = _settings(manga_pct_manhwa=50)
    settings.manga_kinds = dict(settings.manga_kinds, manhwa=False)
    gen = _generator(settings, shiki)
    topup_editions(gen, "sig", _take(gen))
    assert shiki.asked == []


def test_edition_already_in_the_bag_is_not_asked_twice():
    settings = _settings(manga_pct_manhwa=50)
    have = {i: {"malId": i, "kind": "manhwa"} for i in range(1, 400)}
    shiki = FakeShiki()
    gen = _generator(settings, shiki, cache=have)
    topup_editions(gen, "sig", _take(gen))
    assert shiki.asked == []


def test_edition_want_counts_cards_not_questions():
    settings = _settings(manga_pct_manhwa=25)
    gen = _generator(settings, FakeShiki())
    quota = settings.question_quotas[MANGA_KIND]
    assert gen.s.question_quotas[MANGA_KIND] == quota
    assert edition_want(gen, "manhwa") == round(quota * 0.25) * 40
    assert edition_want(gen, "manhua") == 0
