# -*- coding: utf-8 -*-
"""Лёгкие тайтлы, альтернативные вопросы и добор по реальному запасу."""
from collections import Counter

import animepack as ap
from si_hyx_parts.animepack.candidate_reserve import CandidateReserve, clean_copy
from si_hyx_parts.animepack.quota_balance import rebalance
from si_hyx_parts.animepack.candidate_options import available_kinds
from si_hyx_parts.animepack.generator_catalog import _franchise_marks
from test_animepack_mixed_streams import _generator, make_anime, make_song


def _candidate(number, level=4, kind=ap.FRAME_KIND, song=None):
    return ap.SongCandidate(
        song or {}, make_anime(number, statusesStats=[], related=[]), kind=kind,
        franchise_index=ap.INDEX_LEVELS[level - 1])


def _gen(tmp_path, monkeypatch, **over):
    return _generator(tmp_path, monkeypatch, [], [], **{
        "pct_songs": 0, "pct_frames": 50, "pct_chars": 50,
        "level_min": 1, "level_max": 8, "char_level_min": 1,
        "char_level_max": 5, "questions": 4, **over,
    })


def _source(generator, monkeypatch, candidates):
    def walk():
        for candidate in candidates:
            marks = _franchise_marks(candidate.anime)
            generator._used_franchise.update(marks)
            candidate._reserved = marks
            yield candidate
    monkeypatch.setattr(generator, "iter_candidates", walk)


def test_reserved_book_preserves_its_ru_popularity():
    from si_hyx_parts.animepack.candidate_reserve import clean_copy
    candidate = ap.SongCandidate(
        {}, make_anime(1, kind="manga"), media="manga", kind=ap.MANGA_KIND,
        ru_popularity={"ru_equivalent_book_index": ap.INDEX_LEVELS[2]})
    copied = clean_copy(candidate)
    assert copied.ru_popularity == candidate.ru_popularity
    assert copied.level == candidate.level


def test_easy_title_is_kept_for_narrow_character_quota(tmp_path, monkeypatch):
    gen = _gen(tmp_path, monkeypatch)
    quotas = gen.s.question_quotas
    counts = Counter({ap.CHAR_KIND: 1})
    easy = _candidate(1)
    assert gen._pick_kind(easy, counts, Counter(), quotas) == ap.CHAR_KIND
    counts[ap.CHAR_KIND] = 2
    assert gen._pick_kind(easy, counts, Counter(), quotas) == ap.FRAME_KIND
    assert gen._pick_kind(_candidate(2, 7), Counter(), Counter(), quotas) == ap.FRAME_KIND


def test_easy_titles_fill_characters_before_broad_frames(tmp_path, monkeypatch):
    gen = _gen(tmp_path, monkeypatch)
    _source(gen, monkeypatch, [_candidate(1), _candidate(2),
                               _candidate(3, 7), _candidate(4, 7)])
    monkeypatch.setattr(gen, "_fetch_media", lambda c: True)
    picked = gen.select_songs()
    assert Counter(c.kind for c in picked) == {ap.CHAR_KIND: 2, ap.FRAME_KIND: 2}
    assert {c.mal_id for c in picked if c.kind == ap.CHAR_KIND} == {1, 2}


def test_failed_plot_can_become_a_frame_and_fill_reassigned_slot(tmp_path, monkeypatch):
    # Перекладывать доли можно только без «сохранять состав».
    gen = _gen(tmp_path, monkeypatch, questions=2, pct_chars=0,
               pack_plot=True, pct_plot=50, plot_level_min=1, plot_level_max=5,
               preserve_composition=False)
    _source(gen, monkeypatch, [_candidate(1), _candidate(2)])
    tries = []

    def fetch(candidate):
        tries.append((candidate.mal_id, candidate.kind))
        if candidate.kind == ap.PLOT_KIND:
            candidate.plot_question = "Частично подготовленный сюжет"
            candidate.frame_name = "failed.avif"
            return False
        assert not candidate.plot_question and not candidate.frame_name
        return True

    monkeypatch.setattr(gen, "_fetch_media", fetch)
    picked = gen.select_songs()
    assert len(picked) == 2
    assert all(c.kind == ap.FRAME_KIND for c in picked)
    # A successful frame can finish before the failed plot. Its title then
    # needs no plot attempt; both completion orders must fill the same slots.
    assert len(tries) == len(set(tries))
    assert {(1, ap.FRAME_KIND), (2, ap.FRAME_KIND)} <= set(tries)
    assert 3 <= len(tries) <= 4


def test_candidates_without_slots_return_after_quota_redistribution(tmp_path, monkeypatch):
    gen = _gen(tmp_path, monkeypatch, preserve_composition=False)
    _source(gen, monkeypatch, [_candidate(1), _candidate(2, 7),
                               _candidate(3, 7), _candidate(4, 7)])
    lines = []
    gen._log = lines.append
    monkeypatch.setattr(gen, "_fetch_media", lambda c: True)
    picked = gen.select_songs()
    assert Counter(c.kind for c in picked) == {ap.CHAR_KIND: 1, ap.FRAME_KIND: 3}
    assert {c.mal_id for c in picked} == {1, 2, 3, 4}
    assert any("Добор по оставшимся тайтлам" in line for line in lines)


def test_all_failures_terminate_without_retrying_the_same_form(tmp_path, monkeypatch):
    gen = _gen(tmp_path, monkeypatch)
    _source(gen, monkeypatch, [_candidate(1), _candidate(2)])
    tries = []
    monkeypatch.setattr(gen, "_fetch_media", lambda c: tries.append(
        (c.mal_id, c.kind)) or False)
    assert gen.select_songs() == []
    assert len(tries) == len(set(tries)) == 4


def test_failed_silent_form_keeps_its_original_song_for_retry(tmp_path, monkeypatch):
    gen = _gen(tmp_path, monkeypatch, pct_songs=50, pct_frames=0)
    candidate = _candidate(1, kind="opening", song=make_song(1))
    reserve = CandidateReserve(gen, gen.s.question_quotas)
    from si_hyx_parts.animepack.candidate_reserve import remember
    remember(candidate)
    candidate.kind = ap.CHAR_KIND
    candidate._exact_duplicate = True
    candidate.rejected = True
    candidate.character = {"name": "Не выбранный герой"}
    reserve.park(candidate, failed=True)
    retry = reserve.take(Counter(), Counter(), gen.s.question_quotas)
    assert retry is not None
    assert gen._pick_kind(retry, Counter(), Counter(), gen.s.question_quotas) == "opening"
    assert not retry.character and not retry.rejected
    assert not getattr(retry, "_exact_duplicate", False)


def test_reserve_waits_for_a_franchise_then_rebooks_it(tmp_path, monkeypatch):
    gen = _gen(tmp_path, monkeypatch)
    candidate = _candidate(1)
    marks = _franchise_marks(candidate.anime)
    reserve = CandidateReserve(gen, gen.s.question_quotas)
    reserve.park(candidate)
    gen._used_franchise.update(marks)
    assert reserve.take(Counter(), Counter(), gen.s.question_quotas) is None
    gen._used_franchise.clear()
    retry = reserve.take(Counter(), Counter(), gen.s.question_quotas)
    assert gen._rebook_candidate(retry)
    assert set(marks) <= gen._used_franchise


def test_stock_counts_related_titles_only_once(tmp_path, monkeypatch):
    gen = _gen(tmp_path, monkeypatch)
    reserve = CandidateReserve(gen, gen.s.question_quotas)
    a, b = _candidate(1), _candidate(2)
    b.anime["franchise"] = a.anime["franchise"]
    reserve.park(a)
    reserve.park(b)
    assert len(reserve._stock()) == 1


def test_quota_matching_preserves_possible_narrow_slots():
    options = [{"frame", "character"}, {"character"}, {"frame"}, {"frame"}]
    quotas = {"frame": 1, "character": 2, "plot": 1}
    result = rebalance(options, quotas, Counter())
    assert result == {"frame": 2, "character": 2, "plot": 0}
    assert sum(result.values()) == sum(quotas.values())


def test_clean_copy_restores_original_title_after_character_lookup():
    original = _candidate(1)
    from si_hyx_parts.animepack.candidate_reserve import remember
    remember(original)
    original.anime = make_anime(99)
    original.kind = ap.CHAR_KIND
    retry = clean_copy(original, failed=True)
    assert retry.mal_id == 1
    assert ap.CHAR_KIND in retry._tried_kinds


def test_old_bench_entry_shares_the_history_of_failed_forms(tmp_path, monkeypatch):
    gen = _gen(tmp_path, monkeypatch)
    original = _candidate(1)
    retry = clean_copy(original)
    retry.kind = ap.CHAR_KIND
    clean_copy(retry, failed=True)
    assert ap.CHAR_KIND not in available_kinds(gen, original, gen.s.question_quotas)


def test_full_frame_quota_does_not_rescan_the_saved_hard_catalog(tmp_path, monkeypatch):
    gen = _gen(tmp_path, monkeypatch)
    reserve = CandidateReserve(gen, gen.s.question_quotas)
    for number in range(100):
        reserve.park(_candidate(number + 1, 7))
    inspected = []
    monkeypatch.setattr(gen, "_pick_kind", lambda *args: inspected.append(args))
    counts = Counter({ap.FRAME_KIND: gen.s.question_quotas[ap.FRAME_KIND]})
    assert reserve.take(counts, Counter(), gen.s.question_quotas) is None
    assert not inspected
