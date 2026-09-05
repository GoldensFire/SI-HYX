# -*- coding: utf-8 -*-
"""Отвалившийся род вопросов не должен обрывать пак.

Живой случай пользователя: доля «по сюжету» встала (Gemini отказался разбирать
пересказ), после чего КАЖДЫЙ следующий кандидат уходил в неё впустую — база
кончилась, и в паке оказался 21 вопрос из 48. Здесь проверяется разбор той
беды: сорванный запрос больше не выключает весь род вопросов, а если род всё же
отвалился — его места достаются оставшимся.
"""
from collections import Counter

import pytest

import animepack
from animepack import ANAGRAM_KIND, PLOT_KIND, PackSettings, SongCandidate
from gemini_api import (GeminiAuthError, GeminiBlockedError, GeminiQuotaError,
                        _is_blocked)

from test_animepack_new_kinds import make_anime


def _gen(**over):
    s = PackSettings(**over)
    return animepack.AnimePackGenerator(s, session=object(), amq=object(),
                                        anisong=object(), mal=object(),
                                        shikimori=object(), tmdb=object())


# ── Gemini: беда одного текста ≠ беда ключа ──────────────────────────────────
BLOCKED = ("Input blocked: The prompt contains sensitive words that violate "
           "Google's Generative AI Prohibited Use policy.")


def test_blocked_prompt_is_not_a_key_problem():
    assert _is_blocked(BLOCKED) is True
    assert _is_blocked("API key not valid. Please pass a valid API key.") is False


def _plot_generator(monkeypatch, error):
    """Генератор с живым Fandom (пересказ есть всегда) и Gemini, который на
    каждый запрос отвечает заданной бедой."""
    gen = _gen(pct_songs=0, pack_plot=True, pct_plot=100, gemini_key="k")

    class Model:
        def generate_json(self, *a, **kw):
            raise error

    gen.gemini, gen.fandom = Model(), object()
    monkeypatch.setattr(animepack, "pick_plot",
                        lambda *a, **kw: {"text": "х" * 800, "page": "Серия 1",
                                          "wiki": "dn.fandom.com"})
    return gen


def test_blocked_answer_keeps_the_kind_alive(monkeypatch):
    """Пересказ не понравился модели — берём следующий тайтл, и только."""
    gen = _plot_generator(monkeypatch, GeminiBlockedError(BLOCKED))
    cand = SongCandidate(song={}, anime=make_anime(), kind=PLOT_KIND)
    assert gen.make_plot_question(cand) is False
    assert gen._dead_kinds == set()          # род вопросов жив
    assert gen.gemini is not None


@pytest.mark.parametrize("err", [GeminiAuthError("нет ключа"),
                                 GeminiQuotaError("квота")])
def test_key_trouble_switches_the_kind_off(monkeypatch, err):
    gen = _plot_generator(monkeypatch, err)
    cand = SongCandidate(song={}, anime=make_anime(), kind=PLOT_KIND)
    assert gen.make_plot_question(cand) is False
    assert gen._dead_kinds == {PLOT_KIND}
    # Кандидат ни в чём не виноват: медиа даже не трогали.
    assert cand.rejected is True


def test_dead_kind_without_a_client_is_noticed_at_once():
    gen = _gen(pct_songs=0, pack_plot=True, pct_plot=100)
    cand = SongCandidate(song={}, anime=make_anime(), kind=PLOT_KIND)
    assert gen.make_plot_question(cand) is False
    assert gen._dead_kinds == {PLOT_KIND} and cand.rejected is True


# ── Места отвалившегося рода уходят остальным ────────────────────────────────
def test_slots_of_a_dead_kind_go_to_the_living_ones():
    gen = _gen(pct_songs=0, pack_anagram=True, pct_anagram=50,
               pack_plot=True, pct_plot=50, gemini_key="k",
               rounds=1, themes=1, questions=48)
    quotas = gen.s.question_quotas
    assert quotas[PLOT_KIND] == 24 and quotas[ANAGRAM_KIND] == 24
    counts, inflight = Counter(), Counter()
    counts[PLOT_KIND] = 2                      # два вопроса успели собраться
    gen._drop_kind(PLOT_KIND)
    gen._share_out_dead(quotas, counts, inflight)
    assert quotas[PLOT_KIND] == 2
    assert quotas[ANAGRAM_KIND] == 46          # 24 своих + 22 осиротевших
    # Второй раз перекладывать нечего.
    gen._share_out_dead(quotas, counts, inflight)
    assert quotas[ANAGRAM_KIND] == 46


def test_a_dead_kind_is_never_picked_again():
    gen = _gen(pct_songs=0, pack_anagram=True, pct_anagram=50,
               pack_plot=True, pct_plot=50, gemini_key="k",
               rounds=1, themes=1, questions=48)
    quotas = gen.s.question_quotas
    counts, inflight = Counter(), Counter()
    cand = SongCandidate(song={}, anime=make_anime(), kind=PLOT_KIND)
    assert gen._pick_kind(cand, counts, inflight, quotas) in (PLOT_KIND,
                                                              ANAGRAM_KIND)
    gen._drop_kind(PLOT_KIND)
    assert gen._pick_kind(cand, counts, inflight, quotas) == ANAGRAM_KIND


def test_nothing_to_share_with_is_said_out_loud():
    lines = []
    gen = _gen(pct_songs=0, pack_plot=True, pct_plot=100, gemini_key="k",
               rounds=1, themes=1, questions=10)
    gen._log = lines.append
    quotas = gen.s.question_quotas
    gen._drop_kind(PLOT_KIND)
    gen._share_out_dead(quotas, Counter(), Counter())
    assert quotas[PLOT_KIND] == 0
    assert any("переложить их не на кого" in line for line in lines)
