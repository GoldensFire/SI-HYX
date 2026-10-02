# -*- coding: utf-8 -*-
"""A book may return from MangaMix while CandidateReserve still holds it."""
from collections import Counter

import animepack as ap
from si_hyx_parts.animepack.candidate_reserve import CandidateReserve
from test_animepack_manga_adaptation import _book
from test_animepack_mixed_streams import _generator
from test_animepack_manga_adaptation import manga_card
from test_animepack_mixed_streams import _name


def generator(tmp_path, monkeypatch):
    return _generator(tmp_path, monkeypatch, [], [], pct_songs=0, pct_frames=0,
                      pct_manga=100, pack_manga=True, questions=2,
                      manga_adapted_percent=0)


def test_a_reserved_book_can_be_rebooked_from_the_mix_bench(tmp_path, monkeypatch):
    gen = generator(tmp_path, monkeypatch)
    quotas = gen.s.question_quotas
    gen._manga_mix.sync(quotas[ap.MANGA_KIND])
    reserve = CandidateReserve(gen, quotas)
    reserve.park(_book(adapted=True))
    assert reserve.take(Counter(), Counter(), quotas) is None
    assert gen._manga_mix.bench_size == 1
    returned = gen._manga_mix.take_bench()[0]
    assert gen._rebook_candidate(returned)
    # Rebooking clears _bench_keys. This previously iterated over None.
    assert returned._bench_keys is None
    assert reserve._stock() == []
    reserve.withdraw(returned)
    assert not reserve


def test_selection_withdraws_a_book_returning_from_the_mix_bench(tmp_path, monkeypatch):
    gen = generator(tmp_path, monkeypatch)
    # Start with stock like a book that has failed one presentation already.
    original_init = CandidateReserve.__init__
    withdrawals = []
    original_withdraw = CandidateReserve.withdraw

    def seed(self, generator, quotas):
        original_init(self, generator, quotas)
        self.park(_book(adapted=True))

    def withdraw(self, candidate):
        if id(candidate._retry_seed) in self.candidates:
            withdrawals.append(candidate)
        original_withdraw(self, candidate)

    monkeypatch.setattr(CandidateReserve, "__init__", seed)
    monkeypatch.setattr(CandidateReserve, "withdraw", withdraw)
    monkeypatch.setattr(gen, "iter_candidates", lambda: iter(()))
    monkeypatch.setattr(gen, "_fetch_media", lambda candidate: True)
    selected = gen.select_songs()
    assert len(selected) == 1
    assert withdrawals == selected


def test_catalog_end_returns_books_parked_for_average_before_closing_quota(
        tmp_path, monkeypatch):
    gen = _generator(tmp_path, monkeypatch, [], [], pct_songs=0, pct_frames=0,
                     pct_manga=100, pack_manga=True, questions=6, level_avg=4,
                     manga_level_min=1, manga_level_max=8, manga_adapted_percent=-1,
                     manga_pct_manhwa=100, manga_pct_manhua=0)
    cards = [manga_card(200000, kind="manhwa", id=i, malId=i,
                        name=_name(i), russian=_name(i)) for i in range(1, 11)]
    monkeypatch.setattr(gen, "collect_manga_ids", lambda: [(i, []) for i in range(1, 11)])
    monkeypatch.setattr(gen, "_mangas_by_ids", lambda ids: [cards[i - 1] for i in ids])
    monkeypatch.setattr(gen, "_fetch_media", lambda candidate: True)
    selected = gen.select_songs()
    assert gen._level_benched > 0
    assert gen._level_reused > 0
    assert len(selected) == 6
    assert all(1 <= c.level <= 8 for c in selected)
