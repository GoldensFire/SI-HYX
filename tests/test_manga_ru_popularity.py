# -*- coding: utf-8 -*-
"""The correction adds evidence without changing either existing ladder."""
import pytest

import animepack as ap
from si_hyx_parts.animepack.ru_popularity_math import (
    RuPopularityConfig, correction, percentile, quantile, reliable_percentile)
from si_hyx_parts.animepack_api.ru_title_matching import match_title

BOOKS = [i * 200 for i in range(101)]


def observation(p=None, status="NORMAL", **extra):
    return {"percentile": p, "status": status, **extra}


def manga(**extra):
    return {"id": "77", "malId": "77", "name": "A distinctive English title",
            "russian": "Отдельное русское название", "kind": "manhwa", "score": 8,
            "airedOn": {"year": 2015},
            "statusesStats": [{"status": "completed", "count": 3}], **extra}


@pytest.mark.parametrize("status", ["ERROR", "NOT_FOUND", "AMBIGUOUS", "RIGHTS_RESTRICTED"])
def test_only_shikimori_exactly_preserves_old_result(status):
    candidate = ap.SongCandidate({}, manga(), media="manga", favorites=20)
    old = candidate.own_index * candidate.favorites_factor
    result = correction(old, .30, {"remanga": observation(None, status)}, BOOKS)
    candidate.ru_popularity = result
    assert candidate.book_index == old
    assert candidate.effective_book_index == old
    assert candidate.index == ap.manga_reach(old)
    assert candidate.level == ap.index_level(ap.manga_reach(old))


def test_known_manhwa_is_confirmed_by_both_russian_sources():
    result = correction(2300, .30, {"remanga": observation(.97),
                                  "mangalib": observation(.95)}, BOOKS)
    assert result["P_ru"] == pytest.approx(.956)
    assert result["ru_equivalent_book_index"] == pytest.approx(19120)
    assert result["effective_book_index"] > 2300
    assert ap.index_level(2300, manga=True) == 10
    assert ap.index_level(result["effective_book_index"], manga=True) == 7
    provided_example = correction(2300, .42, {"remanga": observation(.96),
                                            "mangalib": observation(.94)}, BOOKS)
    assert provided_example["P_ru"] == pytest.approx(.946)


def test_one_external_outlier_does_not_determine_difficulty():
    result = correction(2300, .30, {"remanga": observation(.98),
                                  "mangalib": observation(.35)}, BOOKS)
    assert result["P_ru"] == pytest.approx(.539)
    assert result["P_ru"] < .98


def test_one_available_external_source_is_anchored_by_shikimori():
    result = correction(2300, .3, {"remanga": observation(.98)}, BOOKS)
    assert result["P_ru"] == pytest.approx(.504)


def test_low_external_values_never_rewrite_original_book_index():
    result = correction(2300, .30, {"remanga": observation(0),
                                  "mangalib": observation(.1)}, BOOKS)
    assert result["effective_book_index"] == 2300
    assert "P_ru" not in result


def test_original_full_book_index_is_always_the_floor():
    result = correction(90000, .3, {"remanga": observation(.97),
                                   "mangalib": observation(.95)}, BOOKS)
    assert result["effective_book_index"] == 90000


def test_rights_restricted_is_absent_evidence_and_can_use_last_normal():
    restricted = observation(0, "RIGHTS_RESTRICTED")
    assert reliable_percentile(restricted) is None
    restricted["last_normal"] = {"percentile": .97}
    assert reliable_percentile(restricted) == .97
    result = correction(2300, .3, {"remanga": restricted,
                                  "mangalib": observation(.95)}, BOOKS)
    assert result["P_ru"] == pytest.approx(.956)


def test_error_not_found_and_ambiguous_never_use_old_positive_history():
    for status in ("ERROR", "NOT_FOUND", "AMBIGUOUS"):
        record = observation(0, status, last_normal={"percentile": .99})
        assert reliable_percentile(record) is None


def test_raw_shiki_readership_rank_precedes_all_corrections():
    card = manga(statusesStats=[{"status": key, "count": 1} for key in
                              ("completed", "watching", "dropped", "on_hold", "planned")])
    young = ap.SongCandidate({}, card, media="manga", favorites=0)
    old = ap.SongCandidate({}, card | {"airedOn": {"year": 1960}, "score": 2},
                           media="manga", favorites=1000)
    assert young.own_base == old.own_base == 32
    assert young.book_index != old.book_index
    assert percentile(list(range(101)), young.own_base) == .32


def test_mapping_uses_only_corresponding_source_distribution():
    values = [0, 10, 20, 20, 40]
    assert percentile(values, 20) == .625
    assert quantile(values, .625) == 20
    assert percentile(values, 100) == 1
    assert percentile(values, -1) is None
    assert quantile(values, 1) == 40
    assert quantile(values, float("nan")) is None


def test_adaptation_still_finishes_with_existing_max():
    book = ap.SongCandidate({}, manga(), media="manga", favorites=10)
    adaptation = manga(statusesStats=[{"status": "completed", "count": 10000}])
    ap.apply_adaptation(book, adaptation)
    book.ru_popularity = correction(book.book_index, .3,
                                   {"remanga": observation(.97),
                                    "mangalib": observation(.95)}, BOOKS)
    assert book.index == max(ap.manga_reach(book.effective_book_index), book.screen_index)
    assert book.effective_book_index >= book.book_index


def test_anime_questions_ignore_ru_correction():
    candidate = ap.SongCandidate({}, manga(kind="tv"), favorites=50, franchise_index=200)
    old_index = max(candidate.own_index, 200) * candidate.favorites_factor
    candidate.ru_popularity = {"ru_equivalent_book_index": 10 ** 9}
    assert candidate.book_index == candidate.effective_book_index == 0
    assert candidate.index == old_index
    assert candidate.level == ap.index_level(old_index)


def test_books_keep_existing_minimum_level():
    book = ap.SongCandidate({}, manga(), media="manga")
    book.ru_popularity = {"ru_equivalent_book_index": 10 ** 9}
    assert book.level == ap.MANGA_MIN_LEVEL == 6


def test_ambiguous_exact_aliases_and_fuzzy_titles_are_not_accepted():
    card = manga()
    row = {"id": "a", "kind": "manhwa", "year": 2015,
           "titles": [card["name"], card["russian"]]}
    assert match_title(card, [row, row | {"id": "b"}])[0] == "AMBIGUOUS"
    assert match_title(card, [row | {"titles": ["A distinctive English title 2"]}])[0] == "NOT_FOUND"
    assert match_title(card, [row | {"year": 2016}])[0] == "NOT_FOUND"


def test_single_title_requires_corroboration():
    card = manga()
    row = {"id": "a", "titles": [card["name"]], "kind": "manhwa"}
    assert match_title(card, [row])[0] == "AMBIGUOUS"
    assert match_title(card, [row | {"year": 2015}])[0] == "NORMAL"


def test_direct_mangalib_shiki_id_is_preferred_but_conflicts_are_rejected():
    card = manga()
    direct = {"id": "a", "titles": ["Different alias"], "shiki_id": 77}
    guessed = {"id": "b", "titles": [card["name"], card["russian"]], "kind": "manhwa"}
    assert match_title(card, [direct, guessed]) == ("NORMAL", direct)
    assert match_title(card, [guessed | {"shiki_id": 999}])[0] == "NOT_FOUND"
    assert match_title(card, [direct | {"kind": "manga"}])[0] == "AMBIGUOUS"


def test_configurable_weights_and_persistent_settings():
    config = RuPopularityConfig(highest_weight=.2, second_weight=.8)
    result = correction(0, .3, {"remanga": observation(.98),
                              "mangalib": observation(.35)}, BOOKS, config)
    assert result["P_ru"] == pytest.approx(.476)
    settings = ap.PackSettings.from_dict({"ru_popularity": {
        "highest_weight": .2, "second_weight": .8}})
    assert ap.PackSettings.from_dict(settings.to_dict()).ru_popularity == settings.ru_popularity
    with pytest.raises(ValueError):
        RuPopularityConfig(highest_weight=1, second_weight=0)


def test_gui_keeps_calibrated_weights(qapp):
    import animepack_tab
    from PyQt6.QtCore import QCoreApplication, QEvent
    tab = animepack_tab.AnimePackTab()
    try:
        weights = {"highest_weight": .2, "second_weight": .8}
        tab.apply_settings({"ru_popularity": weights})
        assert tab.collect().ru_popularity == weights
    finally:
        tab.cleanup()
        tab.deleteLater()
        QCoreApplication.sendPostedEvents(tab, QEvent.Type.DeferredDelete)
