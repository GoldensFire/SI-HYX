# -*- coding: utf-8 -*-
"""Подсказка «из чего сложился индекс» и компактная панель AMQ."""
import pytest

import animepack as ap
import animepack_tab
from si_hyx_parts.animepack_tab import index_tooltip
from test_animepack_tab_mix import _FakeMain

CARD = {"id": 1, "malId": 1, "russian": "Тест", "name": "Test",
        "airedOn": {"year": 2020}, "score": 8.1,
        "statusesStats": [{"status": "completed", "count": 100000},
                          {"status": "watching", "count": 5000},
                          {"status": "planned", "count": 20000}]}
SONG = {"songType": "Opening 1", "songName": "x", "songArtist": "y",
        "songDifficulty": 85.0, "audio": "a.mp3", "songLength": 90,
        "songCategory": "standard", "animeType": "TV",
        "linked_ids": {"myanimelist": 1}}


@pytest.fixture
def tab(qapp):
    widget = animepack_tab.AnimePackTab(main_window=_FakeMain())
    yield widget
    widget.cleanup()


def test_index_tooltip_shows_one_compact_calculation():
    cand = ap.SongCandidate(song=SONG, anime=CARD, kind="opening")
    text = index_tooltip.build_text(cand)
    assert "База: просмотрено 100 000×10" in text
    assert "Свой индекс:" in text and " × " in text
    assert f"Уровень: {cand.level}" in text
    assert "Множители:" not in text and "чел." not in text


def test_index_tooltip_puts_the_series_into_the_same_formula():
    cand = ap.SongCandidate(song=SONG, anime=CARD, kind="opening",
                            franchise_index=9_000_000.0)
    text = index_tooltip.build_text(cand)
    assert "max(свой" in text and "серия 9 000 000" in text
    assert "Взят индекс" not in text


def test_index_tooltip_is_empty_without_any_index():
    bare = {"id": 2, "malId": 2, "name": "Nobody", "airedOn": {"year": 2020}}
    cand = ap.SongCandidate(song=SONG, anime=bare, kind="opening")
    assert index_tooltip.build_text(cand) == ""


def test_the_pack_table_carries_the_breakdown_in_its_cell(tab):
    cand = ap.SongCandidate(song=SONG, anime=CARD, kind="opening")
    tab._fill_table([cand])
    item = tab.table.item(0, 8)
    assert item is not None
    assert "База: просмотрено" in str(item.data(index_tooltip.TIP_ROLE))
    # Окно состава пака копирует ячейки через clone() — подсказка едет с ними.
    assert item.clone().data(index_tooltip.TIP_ROLE) == item.data(
        index_tooltip.TIP_ROLE)


def test_the_redundant_band_summary_is_gone(tab):
    assert not hasattr(tab, "lbl_diff_bands")
