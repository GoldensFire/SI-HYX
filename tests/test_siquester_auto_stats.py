# -*- coding: utf-8 -*-
"""Тесты siquester/auto_stats.py — обёртка над SIStatistics с формулами SIOnline."""
import pytest

from siquester import auto_stats
from sigstats import stats_api


class TestFetch:
    def _patch(self, monkeypatch, stats):
        monkeypatch.setattr(stats_api, "get_package_stats",
                            lambda session, name, authors: stats)

    def test_none_when_not_found(self, monkeypatch):
        self._patch(monkeypatch, None)
        assert auto_stats.fetch("Пак", ["Автор"]) is None

    def test_summary_and_per_question(self, monkeypatch):
        stats = {
            "topLevelStats": {"startedGameCount": 100, "completedGameCount": 60},
            "questionStats": {
                "0:0:0": {"shownCount": 10, "answeredCount": 8,
                          "correctCount": 6, "wrongCount": 2},
                "0:1:2": {"shownCount": 20, "answeredCount": 5,
                          "correctCount": 4, "wrongCount": 1},
            },
        }
        self._patch(monkeypatch, stats)
        summary, per_q = auto_stats.fetch("Пак", ["Автор"])
        assert summary["started"] == 100
        assert summary["completed"] == 60
        assert summary["rate"] == pytest.approx(0.6)
        # tries% = answered/shown; right% = correct/(correct+wrong)
        assert per_q[(0, 0, 0)] == {"tries": 80, "right": 75}
        assert per_q[(0, 1, 2)] == {"tries": 25, "right": 80}

    def test_zero_shown_and_tries(self, monkeypatch):
        stats = {
            "topLevelStats": {"startedGameCount": 1, "completedGameCount": 0},
            "questionStats": {
                "0:0:0": {"shownCount": 0, "answeredCount": 0,
                          "correctCount": 0, "wrongCount": 0},
            },
        }
        self._patch(monkeypatch, stats)
        _, per_q = auto_stats.fetch("Пак", [])
        assert per_q[(0, 0, 0)] == {"tries": 0, "right": 0}

    def test_bad_key_skipped(self, monkeypatch):
        stats = {
            "topLevelStats": {"startedGameCount": 5, "completedGameCount": 5},
            "questionStats": {
                "мусор": {"shownCount": 10},
                "1:2": {"shownCount": 10},        # мало компонентов
                "0:0:0": {"shownCount": 10, "answeredCount": 10,
                          "correctCount": 10, "wrongCount": 0},
            },
        }
        self._patch(monkeypatch, stats)
        _, per_q = auto_stats.fetch("Пак", [])
        assert list(per_q.keys()) == [(0, 0, 0)]

    def test_missing_counts_default_zero(self, monkeypatch):
        stats = {
            "topLevelStats": {"startedGameCount": 3, "completedGameCount": 1},
            "questionStats": {"0:0:0": {}},
        }
        self._patch(monkeypatch, stats)
        _, per_q = auto_stats.fetch("Пак", [])
        assert per_q[(0, 0, 0)] == {"tries": 0, "right": 0}

    def test_empty_question_stats(self, monkeypatch):
        stats = {"topLevelStats": {"startedGameCount": 10, "completedGameCount": 2},
                 "questionStats": {}}
        self._patch(monkeypatch, stats)
        summary, per_q = auto_stats.fetch("Пак", [])
        assert per_q == {}
        assert summary["completed"] == 2
