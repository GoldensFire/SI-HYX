# -*- coding: utf-8 -*-
"""Тесты sigstats/stats_api.py (клиент SIStatistics) и sigstats/export.py."""
import pandas as pd
import pytest

from sigstats import stats_api, export, config as scfg
from conftest import FakeResponse, FakeSession


@pytest.fixture(autouse=True)
def no_throttle(monkeypatch):
    monkeypatch.setattr(scfg, "STATS_DELAY", 0)


# ── _name_variants ───────────────────────────────────────────────────────────
class TestNameVariants:
    def test_basic(self):
        v = stats_api._name_variants("Пак")
        assert v[0] == "Пак"
        assert "Пак " in v
        assert " Пак" in v
        assert " Пак " in v

    def test_no_duplicates(self):
        v = stats_api._name_variants("Пак")
        assert len(v) == len(set(v))

    def test_collapsed_spaces_variant(self):
        v = stats_api._name_variants("Пак   с  пробелами")
        assert "Пак с пробелами" in v

    def test_empty(self):
        # для пустого имени остаются только непустые (пробельные) варианты,
        # само "" отфильтровано; None → базой становится "" → тоже пробелы
        for name in ("", None):
            v = stats_api._name_variants(name)
            assert "" not in v
            assert all(x.strip() == "" for x in v)


# ── get_package_stats ────────────────────────────────────────────────────────
STATS = {"topLevelStats": {"startedGameCount": 10, "completedGameCount": 4},
         "questionStats": {}}


class TestGetPackageStats:
    def test_first_variant_hits(self):
        s = FakeSession(routes=[("stats?name=", FakeResponse(json_data=STATS))])
        out = stats_api.get_package_stats(s, "Пак", ["Автор"])
        assert out == STATS
        assert len(s.calls) == 1
        url = s.calls[0][1]
        assert "authors=" in url and "%D0" in url  # авторы url-кодированы

    def test_second_variant_hits(self):
        calls = {"n": 0}

        def handler(url, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                return FakeResponse(status_code=404)
            return FakeResponse(json_data=STATS)
        s = FakeSession(routes=[("stats?name=", handler)])
        assert stats_api.get_package_stats(s, "Пак", []) == STATS
        assert calls["n"] == 2

    def test_all_variants_404(self):
        s = FakeSession(routes=[("stats?name=", FakeResponse(status_code=404))])
        assert stats_api.get_package_stats(s, "Пак", ["А"]) is None

    def test_network_error_none(self):
        import requests as req

        class Boom(FakeSession):
            def get(self, url, **kw):
                raise req.ConnectionError("сеть")
        assert stats_api.get_package_stats(Boom(), "Пак", []) is None

    def test_invalid_json_none(self):
        s = FakeSession(routes=[("stats?name=", FakeResponse(text="html", raise_json=True))])
        assert stats_api.get_package_stats(s, "Пак", []) is None

    def test_empty_authors_not_in_url(self):
        s = FakeSession(routes=[("stats?name=", FakeResponse(json_data=STATS))])
        stats_api.get_package_stats(s, "Пак", ["", None])
        assert "authors=" not in s.calls[0][1]


# ── summarize ────────────────────────────────────────────────────────────────
class TestSummarize:
    def test_none(self):
        assert stats_api.summarize(None) == {
            "has_stats": False, "started": 0, "completed": 0, "rate": None}

    def test_values(self):
        out = stats_api.summarize(STATS)
        assert out == {"has_stats": True, "started": 10, "completed": 4,
                       "rate": pytest.approx(0.4)}

    def test_zero_started(self):
        out = stats_api.summarize({"topLevelStats": {"startedGameCount": 0,
                                                     "completedGameCount": 0}})
        assert out["rate"] is None

    def test_missing_top(self):
        # непустой словарь без topLevelStats: has_stats True, счётчики нулевые
        out = stats_api.summarize({"что-то": 1})
        assert out["has_stats"] is True and out["started"] == 0

    def test_empty_dict_is_falsy(self):
        # {} — falsy → трактуется как «нет статистики»
        assert stats_api.summarize({})["has_stats"] is False


# ── export.py ────────────────────────────────────────────────────────────────
def _pkg_df():
    return pd.DataFrame([
        {"name": "Топ пак", "authors": ["Ася"], "has_stats": 1,
         "completion_rate": 0.9, "completion_pct": 90.0,
         "completion_rank_in_group": 95.0, "started_games": 100,
         "completed_games": 90, "question_count": 100,
         "length_group": "Средние", "download_count": 500},
        {"name": "Слабый пак", "authors": [], "has_stats": 1,
         "completion_rate": 0.1, "completion_pct": 10.0,
         "completion_rank_in_group": 5.0, "started_games": 10,
         "completed_games": 1, "question_count": 50,
         "length_group": "Короткие", "download_count": 100},
        {"name": "Без статистики", "authors": ["Вова"], "has_stats": 0,
         "completion_rate": None, "completion_pct": float("nan"),
         "completion_rank_in_group": float("nan"), "started_games": float("nan"),
         "completed_games": float("nan"), "question_count": 80,
         "length_group": "Короткие", "download_count": 5},
    ])


class TestExportPackages:
    def test_only_with_stats(self):
        text = export.build_packages_dump(_pkg_df())
        assert "Топ пак" in text and "Слабый пак" in text
        assert "Без статистики" not in text
        assert "Пакетов в выборке: 2" in text

    def test_include_all(self):
        text = export.build_packages_dump(_pkg_df(), only_with_stats=False)
        assert "Без статистики" in text
        assert "—" in text  # у пака без статистики прочерки

    def test_top_n(self):
        text = export.build_packages_dump(_pkg_df(), top_n=1)
        assert "Топ пак" in text
        assert "Слабый пак" not in text

    def test_sorted_best_first(self):
        text = export.build_packages_dump(_pkg_df())
        assert text.index("Топ пак") < text.index("Слабый пак")

    def test_details_formatted(self):
        text = export.build_packages_dump(_pkg_df())
        assert "90.0%" in text
        assert "Автор: Ася" in text
        assert "100 начато / 90 завершено" in text


def _theme_df():
    return pd.DataFrame([
        {"theme": "🎶Музыка", "n_packages": 10, "rarity": "частая",
         "avg_completion_pct": 66.0, "avg_pct_in_group": 70.0},
        {"theme": "Редкая тема", "n_packages": 1, "rarity": "редкая",
         "avg_completion_pct": 50.0, "avg_pct_in_group": 50.0},
        {"theme": "Без данных", "n_packages": 5, "rarity": "средняя",
         "avg_completion_pct": float("nan"), "avg_pct_in_group": float("nan")},
    ])


class TestExportThemes:
    def test_min_packages_filter(self):
        text = export.build_theme_dump(_theme_df(), min_packages=2)
        assert "🎶Музыка" in text
        assert "Редкая тема" not in text

    def test_nan_dash(self):
        text = export.build_theme_dump(_theme_df(), min_packages=1)
        assert "Без данных" in text
        assert "—" in text

    def test_top_n(self):
        text = export.build_theme_dump(_theme_df(), top_n=1, min_packages=1)
        assert "🎶Музыка" in text and "Без данных" not in text

    def test_format(self):
        text = export.build_theme_dump(_theme_df(), min_packages=1)
        assert "пакетов: 10 (частая)" in text
